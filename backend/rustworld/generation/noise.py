"""Vectorized gradient (Perlin) noise + fractal combinators, NumPy only.

All functions are deterministic for a given seed.
"""
from __future__ import annotations

import numpy as np


def _perm(seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed & 0xFFFFFFFF)
    p = np.arange(256, dtype=np.int32)
    rng.shuffle(p)
    return np.concatenate([p, p])


_GRADS = np.array(
    [(1, 1), (-1, 1), (1, -1), (-1, -1), (1, 0), (-1, 0), (0, 1), (0, -1)],
    dtype=np.float32,
)


def perlin(x: np.ndarray, y: np.ndarray, seed: int) -> np.ndarray:
    """2D Perlin gradient noise in ~[-1, 1] for float coordinate grids."""
    perm = _perm(seed)
    xi = np.floor(x).astype(np.int32)
    yi = np.floor(y).astype(np.int32)
    xf = (x - xi).astype(np.float32)
    yf = (y - yi).astype(np.float32)
    xi &= 255
    yi &= 255

    def grad_dot(hash_: np.ndarray, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
        g = _GRADS[hash_ & 7]
        return g[..., 0] * gx + g[..., 1] * gy

    def fade(t: np.ndarray) -> np.ndarray:
        return t * t * t * (t * (t * 6 - 15) + 10)

    aa = perm[perm[xi] + yi]
    ab = perm[perm[xi] + yi + 1]
    ba = perm[perm[xi + 1] + yi]
    bb = perm[perm[xi + 1] + yi + 1]

    u = fade(xf)
    v = fade(yf)

    n00 = grad_dot(aa, xf, yf)
    n10 = grad_dot(ba, xf - 1, yf)
    n01 = grad_dot(ab, xf, yf - 1)
    n11 = grad_dot(bb, xf - 1, yf - 1)

    nx0 = n00 * (1 - u) + n10 * u
    nx1 = n01 * (1 - u) + n11 * u
    return (nx0 * (1 - v) + nx1 * v) * np.float32(1.41421356)


def grid(res: int, scale: float) -> tuple[np.ndarray, np.ndarray]:
    """Coordinate grids covering `scale` noise periods across res x res."""
    c = np.linspace(0.0, scale, res, dtype=np.float32)
    return np.meshgrid(c, c)


def fbm(res: int, seed: int, octaves: int = 5, scale: float = 3.0,
        persistence: float = 0.5, lacunarity: float = 2.0) -> np.ndarray:
    """Fractal Brownian motion in ~[-1, 1]."""
    x, y = grid(res, scale)
    total = np.zeros((res, res), dtype=np.float32)
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for i in range(octaves):
        total += amp * perlin(x * freq + i * 17.17, y * freq - i * 9.3, seed + i * 1013)
        norm += amp
        amp *= persistence
        freq *= lacunarity
    return total / norm


def ridged(res: int, seed: int, octaves: int = 5, scale: float = 3.0,
           persistence: float = 0.5, lacunarity: float = 2.0) -> np.ndarray:
    """Ridged multifractal in [0, 1] — sharp mountain ridges."""
    x, y = grid(res, scale)
    total = np.zeros((res, res), dtype=np.float32)
    amp = 1.0
    freq = 1.0
    norm = 0.0
    for i in range(octaves):
        n = perlin(x * freq + i * 31.7, y * freq + i * 11.1, seed + 7919 + i * 877)
        total += amp * (1.0 - np.abs(n))
        norm += amp
        amp *= persistence
        freq *= lacunarity
    return np.clip(total / norm, 0.0, 1.0)


def warped_fbm(res: int, seed: int, octaves: int = 5, scale: float = 3.0,
               warp: float = 0.35) -> np.ndarray:
    """Domain-warped fBm — more organic coastlines/landforms."""
    x, y = grid(res, scale)
    wx = fbm(res, seed + 101, octaves=3, scale=scale * 0.6)
    wy = fbm(res, seed + 202, octaves=3, scale=scale * 0.6)
    total = np.zeros((res, res), dtype=np.float32)
    amp, freq, norm = 1.0, 1.0, 0.0
    for i in range(octaves):
        total += amp * perlin(
            (x + wx * warp * scale) * freq + i * 13.7,
            (y + wy * warp * scale) * freq - i * 5.9,
            seed + i * 2029,
        )
        norm += amp
        amp *= 0.5
        freq *= 2.0
    return total / norm


def smoothstep(edge0: float, edge1: float, x: np.ndarray) -> np.ndarray:
    t = np.clip((x - edge0) / (edge1 - edge0 + 1e-9), 0.0, 1.0)
    return t * t * (3 - 2 * t)


def radial_falloff(res: int, power: float = 2.2, radius: float = 0.92) -> np.ndarray:
    """1 at center -> 0 at map edge; guarantees ocean borders."""
    c = np.linspace(-1.0, 1.0, res, dtype=np.float32)
    x, y = np.meshgrid(c, c)
    d = np.sqrt(x * x + y * y) / radius
    return np.clip(1.0 - d**power, 0.0, 1.0)


def square_falloff(res: int, margin: float = 0.12) -> np.ndarray:
    """1 inside, fading to 0 within `margin` of each edge."""
    c = np.linspace(0.0, 1.0, res, dtype=np.float32)
    x, y = np.meshgrid(c, c)
    fx = np.minimum(x, 1 - x) / margin
    fy = np.minimum(y, 1 - y) / margin
    return np.clip(np.minimum(fx, fy), 0.0, 1.0) ** 1.5


def blur(a: np.ndarray, passes: int = 1) -> np.ndarray:
    """Cheap separable 3x3 box blur."""
    out = a.astype(np.float32)
    for _ in range(passes):
        out = (np.roll(out, 1, 0) + out + np.roll(out, -1, 0)) / 3.0
        out = (np.roll(out, 1, 1) + out + np.roll(out, -1, 1)) / 3.0
    return out
