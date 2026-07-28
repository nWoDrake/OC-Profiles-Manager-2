"""
OC Profiles Manager - History strutturata.

Persiste cambio profilo con timestamp per statistiche di utilizzo.
Salvataggio JSON atomico, retention 30 giorni configurabile.
"""

from __future__ import annotations

import csv
import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from oc_utils import atomic_write_json, safe_read_json

logger = logging.getLogger(__name__)


# ============================================================================
# ENTRY
# ============================================================================

class ProfileHistoryEntry:
    """Singola voce nella history (memory-efficient via __slots__)."""

    __slots__ = ("profile", "timestamp", "exe", "duration_sec")

    def __init__(
        self,
        profile: str,
        timestamp: str,
        exe: str = "",
        duration_sec: float = 0.0,
    ):
        self.profile = profile
        self.timestamp = timestamp
        self.exe = exe
        self.duration_sec = duration_sec

    def to_dict(self) -> dict:
        return {
            "profile": self.profile,
            "timestamp": self.timestamp,
            "exe": self.exe,
            "duration_sec": self.duration_sec,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ProfileHistoryEntry":
        return cls(
            profile=d.get("profile", ""),
            timestamp=d.get("timestamp", ""),
            exe=d.get("exe", ""),
            duration_sec=float(d.get("duration_sec", 0.0) or 0.0),
        )

    def __repr__(self) -> str:
        return (
            f"ProfileHistoryEntry(profile={self.profile!r}, "
            f"timestamp={self.timestamp!r}, exe={self.exe!r}, "
            f"duration_sec={self.duration_sec:.1f})"
        )


# ============================================================================
# HISTORY
# ============================================================================

class ProfileHistory:
    """
    Gestisce history di utilizzo profili.

    Salvataggio JSON con entries degli ultimi `MAX_DAYS` giorni.
    Thread-safe (lock interno su mutazioni).
    """

    MAX_DAYS: int = 30

    def __init__(self, history_path: Path, max_days: Optional[int] = None):
        self._path: Path = Path(history_path)
        self._entries: List[ProfileHistoryEntry] = []
        self._current_profile: Optional[str] = None
        self._current_start: Optional[datetime] = None
        self._lock = threading.Lock()
        if max_days is not None:
            self.MAX_DAYS = max_days
        self._load()

    # --- IO ---

    def _load(self) -> None:
        data = safe_read_json(self._path, default=None)
        if not isinstance(data, dict):
            return
        try:
            raw_entries = data.get("entries", []) or []
            self._entries = [
                ProfileHistoryEntry.from_dict(d)
                for d in raw_entries
                if isinstance(d, dict)
            ]
            self._prune_old()
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore caricamento history: {e}")
            self._entries = []

    def _save(self) -> None:
        data = {"entries": [e.to_dict() for e in self._entries]}
        atomic_write_json(self._path, data, indent=2, retries=3)

    def _prune_old(self) -> None:
        cutoff_str = (datetime.now() - timedelta(days=self.MAX_DAYS)).isoformat()
        self._entries = [e for e in self._entries if e.timestamp >= cutoff_str]

    # --- Recording ---

    def record_switch(self, profile_name: str, exe_name: str = "") -> None:
        """Registra un cambio di profilo, chiudendo la entry precedente."""
        with self._lock:
            now = datetime.now()
            self._close_current_locked(now)

            entry = ProfileHistoryEntry(
                profile=profile_name,
                timestamp=now.isoformat(),
                exe=exe_name,
                duration_sec=0.0,
            )
            self._entries.append(entry)
            self._current_profile = profile_name
            self._current_start = now
            self._prune_old()
            self._save()

    def close_session(self) -> None:
        """
        Chiude la entry corrente (chiamare allo shutdown applicazione).
        Senza questa chiamata l'ultimo profilo non avrebbe duration_sec.
        """
        with self._lock:
            if self._current_profile and self._current_start:
                self._close_current_locked(datetime.now())
                self._current_profile = None
                self._current_start = None
                self._save()

    def _close_current_locked(self, now: datetime) -> None:
        """Aggiorna duration_sec dell'ultima entry (deve essere in lock)."""
        if self._current_profile and self._current_start and self._entries:
            duration = (now - self._current_start).total_seconds()
            # Aggiorna SOLO se l'ultima entry corrisponde al profilo aperto
            last = self._entries[-1]
            if last.profile == self._current_profile and last.duration_sec == 0.0:
                last.duration_sec = max(0.0, duration)

    # --- Read API ---

    def get_recent_entries(self, count: int = 50) -> List[ProfileHistoryEntry]:
        with self._lock:
            return list(self._entries[-count:])

    def get_all_entries(self) -> List[ProfileHistoryEntry]:
        with self._lock:
            return list(self._entries)

    def get_usage_last_n_days(self, days: int = 7) -> Dict[str, float]:
        """Ritorna {profile_name: hours} negli ultimi N giorni."""
        cutoff_str = (datetime.now() - timedelta(days=days)).isoformat()
        usage: Dict[str, float] = {}
        with self._lock:
            for entry in self._entries:
                if entry.timestamp >= cutoff_str and entry.duration_sec > 0:
                    hours = entry.duration_sec / 3600.0
                    usage[entry.profile] = usage.get(entry.profile, 0.0) + hours
        return usage

    def get_daily_breakdown(self, days: int = 7) -> Dict[str, Dict[str, float]]:
        """Ritorna {YYYY-MM-DD: {profile: hours}}."""
        cutoff_str = (datetime.now() - timedelta(days=days)).isoformat()
        daily: Dict[str, Dict[str, float]] = {}
        with self._lock:
            for entry in self._entries:
                if entry.timestamp < cutoff_str or entry.duration_sec <= 0:
                    continue
                try:
                    date_str = entry.timestamp[:10]
                    hours = entry.duration_sec / 3600.0
                    daily.setdefault(date_str, {})
                    daily[date_str][entry.profile] = (
                        daily[date_str].get(entry.profile, 0.0) + hours
                    )
                except Exception:  # noqa: BLE001
                    continue
        return daily

    def get_summary_stats(self, days: int = 7) -> Dict[str, float]:
        """
        Statistiche riassuntive per il periodo richiesto.

        Returns:
            {
                "total_hours": float,
                "switch_count": int,
                "avg_session_minutes": float,
                "top_profile": str,
                "top_profile_hours": float,
            }
        """
        cutoff_str = (datetime.now() - timedelta(days=days)).isoformat()
        total_seconds = 0.0
        switch_count = 0
        per_profile: Dict[str, float] = {}

        with self._lock:
            for entry in self._entries:
                if entry.timestamp < cutoff_str:
                    continue
                switch_count += 1
                if entry.duration_sec > 0:
                    total_seconds += entry.duration_sec
                    per_profile[entry.profile] = (
                        per_profile.get(entry.profile, 0.0) + entry.duration_sec
                    )

        top_profile, top_seconds = self._argmax(per_profile)
        avg_minutes = (total_seconds / switch_count / 60.0) if switch_count else 0.0
        return {
            "total_hours": total_seconds / 3600.0,
            "switch_count": float(switch_count),
            "avg_session_minutes": avg_minutes,
            "top_profile": top_profile,  # type: ignore[dict-item]
            "top_profile_hours": top_seconds / 3600.0,
        }

    @staticmethod
    def _argmax(d: Dict[str, float]) -> Tuple[str, float]:
        if not d:
            return ("—", 0.0)
        k = max(d, key=lambda x: d[x])
        return (k, d[k])

    # --- Export ---

    def export_csv(self, path: Path) -> bool:
        """Esporta tutte le entries in formato CSV."""
        path = Path(path)
        try:
            with path.open("w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["timestamp", "profile", "exe", "duration_sec"])
                with self._lock:
                    entries = list(self._entries)
                for e in entries:
                    writer.writerow([e.timestamp, e.profile, e.exe, f"{e.duration_sec:.2f}"])
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Errore export CSV: {e}")
            return False

    def clear(self) -> bool:
        """Cancella tutta la history."""
        with self._lock:
            self._entries.clear()
            self._current_profile = None
            self._current_start = None
            self._save()
        return True
