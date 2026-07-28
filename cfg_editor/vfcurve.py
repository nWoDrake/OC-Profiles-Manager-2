"""
Decode/encode della VFCurve di MSI Afterburner.
Gestisce editing interattivo AB-like dei punti della curva.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import List


@dataclass
class VFPoint:
    v_mv: float      # Voltage in mV (es. 762.5)
    f_mhz: float     # Frequency in MHz
    c_delta: float    # Local delta (Afterburner writes here)


def _snap(value: float, step: int) -> float:
    """Snappa un valore al multiplo più vicino di step."""
    return round(value / step) * step


def decode_vfcurve(vf_hex: str, n_points: int = 127) -> List[VFPoint]:
    """
    Decodifica la stringa hex VFCurve in una lista di punti.
    Formato: 3 float header, poi triplette (V, F_base, C_delta) * n_points.
    """
    if not vf_hex:
        raise ValueError("Empty VFCurve")
    b = bytes.fromhex(vf_hex)
    floats = struct.unpack("<" + "f" * (len(b) // 4), b)
    pts: List[VFPoint] = []
    base = 3  # Skip header (3 float)
    for i in range(n_points):
        idx = base + i * 3
        if idx + 2 >= len(floats):
            break
        v = float(floats[idx + 0])
        f = float(floats[idx + 1])
        c = float(floats[idx + 2])
        pts.append(VFPoint(v, f, c))
    return pts


def encode_vfcurve(original_hex: str, points: List[VFPoint]) -> str:
    """
    Encode i punti nella stringa hex VFCurve, preservando header e struttura.
    """
    b = bytes.fromhex(original_hex)
    floats = list(struct.unpack("<" + "f" * (len(b) // 4), b))
    base = 3
    for i, p in enumerate(points):
        idx = base + i * 3
        if idx + 2 >= len(floats):
            break
        floats[idx + 0] = float(p.v_mv)
        floats[idx + 1] = float(p.f_mhz)
        floats[idx + 2] = float(p.c_delta)
    out = struct.pack("<" + "f" * len(floats), *floats)
    return out.hex()


def apply_single_point_edit_ab_like(
    base_points: List[VFPoint],
    point_index: int,
    delta_mhz: int,
    snap_mhz: int = 15,
    left_gap_max_mhz: int = 60,
) -> List[VFPoint]:
    """
    Editing AB-like di un singolo punto:
    - Imposta la frequenza target sul punto selezionato
    - Right smoothing: i punti a destra diventano non-decrescenti (plateau)
    - Left smoothing: i punti a sinistra rispettano il gap massimo
    """
    if point_index < 0 or point_index >= len(base_points):
        raise IndexError("point_index out of range")

    delta_mhz = int(_snap(delta_mhz, snap_mhz))
    pts = [VFPoint(p.v_mv, p.f_mhz, 0.0) for p in base_points]

    base_f = base_points[point_index].f_mhz
    target = float(_snap(base_f + delta_mhz, snap_mhz))
    pts[point_index].f_mhz = target

    # Right smoothing: non-decrescente, almeno pari a target
    for i in range(point_index + 1, len(pts)):
        newf = max(base_points[i].f_mhz, target, pts[i - 1].f_mhz)
        pts[i].f_mhz = float(_snap(newf, snap_mhz))

    # Left smoothing: gap massimo rispetto al punto a destra
    right_ref = pts[point_index].f_mhz
    for i in range(point_index - 1, -1, -1):
        allowed_min = right_ref - left_gap_max_mhz
        newf = max(base_points[i].f_mhz, allowed_min)
        pts[i].f_mhz = float(_snap(newf, snap_mhz))
        right_ref = pts[i].f_mhz

    return pts


def compile_ab_cfg_points_for_save(
    base_points: List[VFPoint],
    preview_points: List[VFPoint],
    edited_index: int,
    delta_mhz: int,
) -> List[VFPoint]:
    """
    Converte la curva preview in formato file AB:
    - B[k] torna al valore base per il punto editato
    - C[k] = delta per il punto editato
    - Tutti gli altri: B = valore preview, C = 0
    """
    if edited_index < 0 or edited_index >= len(base_points):
        raise IndexError("edited_index out of range")
    if len(preview_points) != len(base_points):
        raise ValueError("preview_points length mismatch")

    out = [VFPoint(p.v_mv, p.f_mhz, 0.0) for p in preview_points]
    out[edited_index].c_delta = float(delta_mhz)
    out[edited_index].f_mhz = float(base_points[edited_index].f_mhz)

    return out
