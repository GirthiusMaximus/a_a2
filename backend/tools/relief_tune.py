"""Fast terrain-relief harness.

Runs only the shaping stages of the pipeline (build -> land-ratio fit ->
erosion -> shoreline shelf) so the classic height builder can be calibrated
against real-map statistics without paying for splat/topology/paint.

Usage:  python -m tools.relief_tune [seeds...]
"""
from __future__ import annotations

import sys

import numpy as np

from rustworld.generation import noise
from rustworld.generation.pipeline import Recipe, _fit_land_ratio, _thermal_erosion
from rustworld.generation.themes import THEMES
from rustworld.layers import SEA_LEVEL, TERRAIN_HEIGHT, heightmap_resolution

# Target bands derived from real Rust procedural maps -- see
# docs/PROCGEN_RESEARCH.md section 5.  Cliff share uses Facepunch's own
# GenerateCliffTopology threshold of 30 degrees.
TARGETS = {
    "peak_m": (190.0, 285.0),
    "mean_m": (30.0, 70.0),
    "p50_m": (18.0, 55.0),
    "p90_m": (80.0, 145.0),
    "cliff_pct": (5.0, 18.0),
    "slope_deg": (8.0, 20.0),
    "above15_pct": (55.0, 92.0),
}


def shape(seed: int, size: int = 3000, theme_key: str = "classic", **kw) -> tuple[np.ndarray, int]:
    theme = THEMES[theme_key]
    recipe = Recipe(seed=seed, size=size, theme=theme_key, **kw)
    res = heightmap_resolution(size)
    h = theme.build_height(res, recipe)
    if not theme.dry:
        h = _fit_land_ratio(h, recipe.effective_land_ratio(theme))
    if recipe.erosion and theme.erosion:
        h = _thermal_erosion(h, iterations=10)
    sea = SEA_LEVEL
    band = 0.004 * recipe.beach_width * theme.beach_scale
    if theme.shelf > 0 and band > 0:
        bz = band * 4.0
        t = noise.smoothstep(sea - bz, sea + bz, h)
        flattened = (sea - band) + t * 2.0 * band
        w = np.clip(1.0 - np.abs(h - sea) / bz, 0.0, 1.0) * theme.shelf
        h = h * (1 - w) + flattened * w
    return h, size


def stats(h: np.ndarray, size: int) -> dict:
    land = h > SEA_LEVEL
    m = (h - SEA_LEVEL) * TERRAIN_HEIGHT
    step = size / h.shape[0]
    gz, gx = np.gradient(h * TERRAIN_HEIGHT, step)
    slope = np.degrees(np.arctan(np.hypot(gz, gx)))
    lm = m[land]
    return {
        "land_pct": float(land.mean() * 100),
        "peak_m": float(lm.max()),
        "mean_m": float(lm.mean()),
        "p50_m": float(np.percentile(lm, 50)),
        "p90_m": float(np.percentile(lm, 90)),
        "cliff_pct": float((slope[land] > 30.0).mean() * 100),
        "slope_deg": float(slope[land].mean()),
        "above15_pct": float((lm > 15.0).mean() * 100),
    }


def row(tag: str, st: dict) -> str:
    parts = [f"land {st['land_pct']:4.1f}%"]
    for k, (lo, hi) in TARGETS.items():
        v = st[k]
        parts.append(f"{'OK' if lo <= v <= hi else '--'} {k.split('_')[0]}={v:6.1f}")
    return f"{tag:<16} " + " ".join(parts)


def main() -> int:
    seeds = [int(a) for a in sys.argv[1:]] or [1337, 42, 912156065, 2025]
    bad = 0
    for sd in seeds:
        h, size = shape(sd)
        st = stats(h, size)
        print(row(f"seed {sd}", st))
        bad += sum(1 for k, (lo, hi) in TARGETS.items() if not lo <= st[k] <= hi)
    print(f"\n{bad} metric(s) outside target across {len(seeds)} seeds")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
