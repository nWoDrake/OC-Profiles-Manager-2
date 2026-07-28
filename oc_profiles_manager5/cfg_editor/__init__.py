"""
CFG Editor — Modulo integrato per editing avanzato file .cfg MSI Afterburner.

Gestisce parsing, encoding e editing interattivo della curva VF.
"""

from cfg_editor.cfg_model import AfterburnerCfgFile, AfterburnerProfile
from cfg_editor.vfcurve import (
    VFPoint,
    decode_vfcurve,
    encode_vfcurve,
    apply_single_point_edit_ab_like,
    compile_ab_cfg_points_for_save,
)

__all__ = [
    "AfterburnerCfgFile",
    "AfterburnerProfile",
    "VFPoint",
    "decode_vfcurve",
    "encode_vfcurve",
    "apply_single_point_edit_ab_like",
    "compile_ab_cfg_points_for_save",
]
