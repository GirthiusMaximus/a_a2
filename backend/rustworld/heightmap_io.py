"""Heightmap import/export: 16-bit grayscale PNG and RAW (RustEdit compatible).

RustEdit imports 16-bit grayscale heightmaps at 513/1025/2049/4097 and raw
little-endian uint16 files. Exported PNGs are north-up (row 0 = north);
internal arrays are height01[z, x] with row 0 = south, so files are flipped.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

VALID_RESOLUTIONS = (513, 1025, 2049, 4097)


def export_png16(height01: np.ndarray) -> bytes:
    h = np.clip(height01, 0.0, 1.0)
    data = (h * 65535.0 + 0.5).astype(np.uint16)[::-1]  # north-up
    img = Image.fromarray(data, mode="I;16")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def export_raw16(height01: np.ndarray) -> bytes:
    h = np.clip(height01, 0.0, 1.0)
    return (h * 65535.0 + 0.5).astype("<u2")[::-1].tobytes()


def import_heightmap(data: bytes, filename: str = "") -> np.ndarray:
    """Load an uploaded heightmap (16/8-bit PNG, or raw 16-bit square) to [0,1]."""
    name = filename.lower()
    if name.endswith(".raw") or name.endswith(".r16"):
        arr = np.frombuffer(data, dtype="<u2")
        res = int(round(len(arr) ** 0.5))
        if res * res != len(arr):
            raise ValueError("RAW heightmap is not square 16-bit data")
        return (arr.reshape(res, res).astype(np.float32) / 65535.0)[::-1]

    img = Image.open(io.BytesIO(data))
    if img.mode in ("I;16", "I;16B", "I"):
        arr = np.array(img, dtype=np.float32)
        arr /= 65535.0
    else:
        arr = np.array(img.convert("L"), dtype=np.float32) / 255.0
    if arr.shape[0] != arr.shape[1]:
        side = min(arr.shape[:2])
        arr = arr[:side, :side]
    return np.clip(arr, 0.0, 1.0)[::-1]  # file north-up -> internal south-first


def resample(height01: np.ndarray, res: int) -> np.ndarray:
    """Bilinear resample a heightmap to res x res."""
    if height01.shape == (res, res):
        return height01.astype(np.float32)
    src = height01.astype(np.float32)
    coords = np.linspace(0.0, 1.0, res, dtype=np.float32)
    u, v = np.meshgrid(coords, coords)
    sres_z, sres_x = src.shape
    fx = u * (sres_x - 1)
    fz = v * (sres_z - 1)
    x0 = np.floor(fx).astype(np.int32)
    z0 = np.floor(fz).astype(np.int32)
    x1 = np.minimum(x0 + 1, sres_x - 1)
    z1 = np.minimum(z0 + 1, sres_z - 1)
    tx = fx - x0
    tz = fz - z0
    return ((src[z0, x0] * (1 - tx) + src[z0, x1] * tx) * (1 - tz)
            + (src[z1, x0] * (1 - tx) + src[z1, x1] * tx) * tz)
