"""
themes.red_glossy — Tema "Red Glossy" (UI originale di OC Profiles Manager).

Questo è il tema storico dell'applicazione: sidebar verticale, finestra
frameless con effetto vetro su Windows, accent color rosso, layout a pagine
con QStackedWidget.

Per chi vuole creare un nuovo tema: usa questa cartella come riferimento.
La struttura tipica è:
    themes/<id>/
        __init__.py       ← registra il tema (questo file)
        style.py          ← THEME dict + stylesheet (può anche non esistere)
        widgets.py        ← widget custom del tema (opzionale)
        main_window.py    ← QMainWindow del tema
"""

from __future__ import annotations

from themes import ThemeRegistry
from themes.base import AppContext, ThemeDescriptor

# Lazy: la MainWindow viene importata solo quando serve davvero (factory),
# così se un tema è registrato ma non selezionato, non paghiamo l'import.


def _factory(ctx: AppContext):
    from .main_window import OCProfilesManager
    return OCProfilesManager(ctx)


ThemeRegistry.register(
    ThemeDescriptor(
        id="red_glossy",
        name="Red Glossy",
        author="OC Profiles Team",
        version="2.5.0",
        description=(
            "Tema originale dell'applicazione. Sidebar verticale, finestra "
            "frameless con effetto vetro, accent rosso, layout multi-pagina."
        ),
        factory=_factory,
    ),
)
