"""
OC Profiles Manager - Theme System: Base contract.

Definisce l'interfaccia che ogni tema deve implementare e l'AppContext
condiviso che racchiude tutti i controller di dominio.

Un "tema" qui NON è solo un set di colori: è una UI completa, autonoma,
con widget propri, layout proprio e main window propria. Il sistema temi
permette di avere GUI radicalmente diverse selezionabili a runtime.

Architettura:
    main.py
       │ legge tema attivo da config
       ▼
    ThemeRegistry.get(<id>) ──► ThemeDescriptor
       │                         (metadata + factory)
       ▼
    create_main_window(AppContext) ──► QMainWindow del tema
                                         (ognuno fa quello che vuole)
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from PySide6.QtWidgets import QMainWindow

    from oc_controller import ProfileController
    from oc_core import (
        ConfigManager,
        GPUMonitor,
        MSIAfterburnerController,
        ProcessMonitorLogic,
        ProfileManager,
    )

logger = logging.getLogger(__name__)


# ============================================================================
# APP CONTEXT — il "ponte" tra logica di business e UI dei temi
# ============================================================================

@dataclass
class AppContext:
    """
    Bundle di tutti i controller/manager di dominio.

    Viene istanziato UNA SOLA VOLTA in main.py prima di lanciare il tema.
    Ogni tema riceve questo context e lo usa per parlare con la logica:
    non deve mai istanziare ConfigManager, ProfileManager, ecc. da solo.

    Questo garantisce che cambiare tema NON tocchi mai la logica.
    """

    # --- Paths ---
    base_dir: Path
    config_path: Path

    # --- Domain controllers ---
    config_mgr: "ConfigManager"
    profile_mgr: "ProfileManager"
    msi_ctrl: "MSIAfterburnerController"
    gpu_monitor: "GPUMonitor"
    process_logic: "ProcessMonitorLogic"
    controller: "ProfileController"

    # --- App metadata ---
    app_name: str = ""
    app_version: str = ""

    # --- Runtime flags ---
    start_minimized: bool = False

    # --- Optional log callback (UI può sovrascriverlo) ---
    log_callback: Optional[Callable[[str], None]] = field(default=None)


# ============================================================================
# THEME DESCRIPTOR — metadati statici di un tema
# ============================================================================

@dataclass
class ThemeDescriptor:
    """
    Metadati descrittivi di un tema. Vengono dichiarati nel __init__.py
    del tema stesso ed esposti al sistema tramite la funzione register().

    Attributi:
        id: identificativo univoco (usato in config e nel filesystem).
            Deve coincidere col nome della cartella sotto themes/.
        name: nome leggibile mostrato all'utente nelle impostazioni.
        author: autore del tema.
        version: versione del tema (può differire dalla versione dell'app).
        description: descrizione breve mostrata all'utente.
        preview_image: path opzionale a uno screenshot (per anteprima futura).
        factory: callable che riceve AppContext e ritorna la QMainWindow.
    """

    id: str
    name: str
    author: str = ""
    version: str = "1.0.0"
    description: str = ""
    preview_image: Optional[Path] = None
    factory: Optional[Callable[[AppContext], "QMainWindow"]] = None

    def create_window(self, ctx: AppContext) -> "QMainWindow":
        if self.factory is None:
            raise RuntimeError(
                f"Theme '{self.id}' has no factory registered. "
                "Did you call register() correctly?",
            )
        logger.info(f"Creazione MainWindow del tema '{self.id}' (v{self.version})")
        return self.factory(ctx)


# ============================================================================
# BASE THEME MAIN WINDOW — interfaccia consigliata (NON obbligatoria)
# ============================================================================

class IThemeMainWindow(ABC):
    """
    Interfaccia "morbida" che la MainWindow di un tema dovrebbe rispettare.

    NON è ereditata forzatamente (Qt + ABC giocano male insieme): è una
    documentazione del contratto. Ogni tema può comunque scegliere di
    ereditare da QMainWindow direttamente e implementare i metodi qui sotto.

    Lo scopo è: garantire che chi scrive un nuovo tema sappia esattamente
    quali "hook" deve fornire perché il resto del sistema funzioni.
    """

    @abstractmethod
    def show_window(self) -> None:
        """Mostra la finestra principale (chiamato da main.py se non minimized)."""

    @abstractmethod
    def shutdown(self) -> None:
        """
        Cleanup pulito: stop timer, thread, chiusura sessione history.
        Chiamato prima dell'uscita dell'applicazione.
        """


__all__ = [
    "AppContext",
    "ThemeDescriptor",
    "IThemeMainWindow",
]
