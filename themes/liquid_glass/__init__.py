"""
themes.liquid_glass — Tema "Liquid Glass" (v2.7).

Estetica ispirata al design language "Liquid Glass": superfici traslucide
ad alta trasparenza, bordi luminosi sottili, raggi ampi, accento ciano
freddo e micro-animazioni fluide (fade-in finestra, transizioni di pagina
con dissolvenza, acrylic Windows con tinta blu).

Architettura: riusa la MainWindow di red_glossy (stessa logica, zero
duplicazione) ma ne sostituisce interamente la pelle: palette THEME,
stylesheet rigenerato, layer QSS aggiuntivo e una subclass che aggiunge
le animazioni. Vedi main_window.py per i dettagli tecnici.
"""

from __future__ import annotations

from themes import ThemeRegistry
from themes.base import AppContext, ThemeDescriptor

# Lazy: la MainWindow (e tutta la pipeline di re-skin) viene importata solo
# quando il tema è effettivamente selezionato.


def _factory(ctx: AppContext):
    from .main_window import LiquidGlassManager
    return LiquidGlassManager(ctx)


ThemeRegistry.register(
    ThemeDescriptor(
        id="liquid_glass",
        name="Liquid Glass",
        author="OC Profiles Team",
        version="1.0.0",
        description=(
            "Superfici traslucide stile liquid glass: alta trasparenza, "
            "bordi luminosi, accento ciano e animazioni fluide (fade "
            "finestra, transizioni di pagina, acrylic con tinta blu)."
        ),
        factory=_factory,
    ),
)
