"""
OC Profiles Manager - Theme System: Registry & Discovery.

Il registry è il punto centrale per:
- Scoprire i temi disponibili (scansione della cartella themes/)
- Registrarli con i loro metadati
- Recuperare il tema attivo a runtime

Uso tipico:
    from themes import ThemeRegistry

    ThemeRegistry.discover()                       # all'avvio
    available = ThemeRegistry.list_descriptors()   # per la UI di selezione
    theme = ThemeRegistry.get("red_glossy")        # tema attivo
    window = theme.create_window(app_ctx)          # istanzia MainWindow

Per registrare un nuovo tema, basta:
1. Creare una sottocartella themes/<id>/
2. Nel suo __init__.py chiamare ThemeRegistry.register(ThemeDescriptor(...))
"""

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import Dict, List, Optional

from .base import AppContext, IThemeMainWindow, ThemeDescriptor

logger = logging.getLogger(__name__)


# ID del tema di fallback se quello in config non esiste / non è caricabile.
# DEVE corrispondere a un tema sempre presente nel pacchetto.
DEFAULT_THEME_ID: str = "red_glossy"


class ThemeRegistry:
    """Singleton statico per registrazione e accesso ai temi disponibili."""

    _themes: Dict[str, ThemeDescriptor] = {}
    _discovered: bool = False

    # ------------------------------------------------------------------
    # REGISTRATION
    # ------------------------------------------------------------------

    @classmethod
    def register(cls, descriptor: ThemeDescriptor) -> None:
        """Registra un tema. Chiamato dal __init__.py di ogni tema."""
        if descriptor.id in cls._themes:
            logger.warning(
                f"Tema '{descriptor.id}' già registrato — sovrascrivo "
                f"({cls._themes[descriptor.id].name} → {descriptor.name})",
            )
        cls._themes[descriptor.id] = descriptor
        logger.info(
            f"Registrato tema: id='{descriptor.id}' name='{descriptor.name}' "
            f"v{descriptor.version}",
        )

    # ------------------------------------------------------------------
    # DISCOVERY
    # ------------------------------------------------------------------

    @classmethod
    def discover(cls, force: bool = False) -> None:
        """
        Scansiona la cartella themes/ e importa ogni sotto-package.
        Ogni package registra se stesso al momento dell'import.
        """
        if cls._discovered and not force:
            return

        themes_dir = Path(__file__).parent
        logger.info(f"Discovery temi in: {themes_dir}")

        # Itera tutti i sub-package
        for module_info in pkgutil.iter_modules([str(themes_dir)]):
            if not module_info.ispkg:
                continue  # solo cartelle (con __init__.py)
            name = module_info.name
            full_name = f"themes.{name}"
            try:
                importlib.import_module(full_name)
            except Exception as e:  # noqa: BLE001
                logger.error(f"Errore caricamento tema '{name}': {e}", exc_info=True)

        cls._discovered = True
        logger.info(f"Discovery completata: {len(cls._themes)} tema/i caricato/i")

    # ------------------------------------------------------------------
    # ACCESS
    # ------------------------------------------------------------------

    @classmethod
    def get(cls, theme_id: str) -> Optional[ThemeDescriptor]:
        """Ritorna il descriptor di un tema, o None se non trovato."""
        if not cls._discovered:
            cls.discover()
        return cls._themes.get(theme_id)

    @classmethod
    def get_or_default(cls, theme_id: str) -> ThemeDescriptor:
        """
        Come get() ma con fallback robusto al tema di default.
        Solleva RuntimeError se neanche il default è disponibile.
        """
        if not cls._discovered:
            cls.discover()
        desc = cls._themes.get(theme_id)
        if desc is not None:
            return desc
        if theme_id != DEFAULT_THEME_ID:
            logger.warning(
                f"Tema '{theme_id}' non trovato — fallback a '{DEFAULT_THEME_ID}'",
            )
            fallback = cls._themes.get(DEFAULT_THEME_ID)
            if fallback is not None:
                return fallback
        raise RuntimeError(
            f"Nessun tema disponibile (richiesto: '{theme_id}', "
            f"default: '{DEFAULT_THEME_ID}'). "
            f"Verifica che la cartella themes/ contenga almeno un tema valido.",
        )

    @classmethod
    def list_descriptors(cls) -> List[ThemeDescriptor]:
        """Lista ordinata dei temi disponibili, per la UI di selezione."""
        if not cls._discovered:
            cls.discover()
        # Ordina: default per primo, poi alfabetico per nome leggibile
        items = list(cls._themes.values())
        items.sort(key=lambda d: (d.id != DEFAULT_THEME_ID, d.name.lower()))
        return items

    @classmethod
    def list_ids(cls) -> List[str]:
        return [d.id for d in cls.list_descriptors()]


__all__ = [
    "AppContext",
    "ThemeDescriptor",
    "IThemeMainWindow",
    "ThemeRegistry",
    "DEFAULT_THEME_ID",
]
