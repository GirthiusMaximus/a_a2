"""Grid-search the classic relief parameters against real-map statistics.

Evaluated at size 1500 because ``heightmap_resolution`` makes the cell size
there (1500/1025) identical to size 3000 (3000/2049), so slope statistics
transfer directly.  Noise scales are expressed in cycles-per-map, so they are
rescaled by size/3000 to keep feature wavelengths fixed in metres.
"""
from __future__ import annotations

import itertools

import numpy as np

from rustworld.generation import noise
from rustworld.generation.pipeline import _fit_land_ratio, _thermal_erosion
from rustworld.layers import SEA_LEVEL, TERRAIN_HEIGHT, heightmap_resolution

SIZE = 1500
K = SIZE / 3000.0  # wavelength-preserving scale factor
RES = heightmap_resolution(SIZE)

TARGETS = {
    "peak_m": (190.0, 285.0),
    "mean_m": (30.0, 70.0),
    "p50_m": (18.0, 55.0),
    "p90_m": (80.0, 145.0),
    "cliff_pct": (5.0, 18.0),
    "slope_deg": (8.0, 20.0),
}


def build(seed, *, ridge_scale, crest_lo, crest_exp, mt_amp, detail_amp,
          base_scale, roll_amp, foot_amp, region_lo, region_span, erosion):
    from rustworld.facepunch import axis_projection, biome_axis_angle

    res = RES
    border = noise.square_falloff(res, margin=0.13)
    lobes = noise.fbm(res, seed + 2, octaves=5, scale=4.4 * K)
    inland = noise.smoothstep(0.26, 0.54, border + lobes * 0.30)

    baxis = axis_projection(res, biome_axis_angle(seed))
    region = region_lo + region_span * baxis

    base = noise.warped_fbm(res, seed, octaves=6, scale=base_scale * K, warp=0.5)
    rolling = noise.smoothstep(-0.50, 0.50, base)

    ridge = noise.ridged(res, seed + 1, octaves=5, scale=ridge_scale * K)
    crest = np.clip((ridge - crest_lo) / (1.0 - crest_lo), 0.0, 1.0) ** crest_exp
    rangemask = noise.smoothstep(0.22, 0.74, noise.fbm(res, seed + 3, octaves=4, scale=1.9 * K) + 0.5)
    mountains = crest * rangemask
    foothills = noise.smoothstep(0.0, 0.85, crest) * noise.smoothstep(0.1, 0.7, rangemask)

    detail = noise.fbm(res, seed + 5, octaves=4, scale=10.0 * K)

    h = (SEA_LEVEL - 0.052 + inland * (
        0.020 + rolling * roll_amp * region + foothills * foot_amp * region
        + mountains * mt_amp * region + detail * detail_amp))
    h = np.clip(h, 0.0, 1.0)
    h = _fit_land_ratio(h, 0.652)
    h = _thermal_erosion(h, iterations=erosion)
    return h


def score(h):
    land = h > SEA_LEVEL
    m = (h - SEA_LEVEL) * TERRAIN_HEIGHT
    step = SIZE / h.shape[0]
    gz, gx = np.gradient(h * TERRAIN_HEIGHT, step)
    slope = np.degrees(np.arctan(np.hypot(gz, gx)))
    lm = m[land]
    st = {
        "peak_m": float(lm.max()), "mean_m": float(lm.mean()),
        "p50_m": float(np.percentile(lm, 50)), "p90_m": float(np.percentile(lm, 90)),
        "cliff_pct": float((slope[land] > 30).mean() * 100),
        "slope_deg": float(slope[land].mean()),
    }
    pen = 0.0
    for k, (lo, hi) in TARGETS.items():
        v = st[k]
        mid = 0.5 * (lo + hi)
        if v < lo:
            pen += ((lo - v) / (mid - lo)) ** 2
        elif v > hi:
            pen += ((v - hi) / (hi - mid)) ** 2
    return pen, st


BASE = dict(ridge_scale=2.6, crest_lo=0.44, crest_exp=1.30, mt_amp=0.190,
            detail_amp=0.011, base_scale=3.2, roll_amp=0.058, foot_amp=0.040,
            region_lo=0.62, region_span=0.76, erosion=10)

GRID = {
    "ridge_scale": [1.3, 1.7, 2.1],
    "detail_amp": [0.003, 0.006],
    "crest_exp": [1.0, 1.5],
    "erosion": [10, 26],
}


def main():
    seeds = [1337, 42]
    keys = list(GRID)
    results = []
    for combo in itertools.product(*(GRID[k] for k in keys)):
        p = dict(BASE, **dict(zip(keys, combo)))
        tot, sts = 0.0, []
        for sd in seeds:
            pen, st = score(build(sd, **p))
            tot += pen
            sts.append(st)
        avg = {k: float(np.mean([s[k] for s in sts])) for k in sts[0]}
        results.append((tot, dict(zip(keys, combo)), avg))
        print(f"pen {tot:7.3f}  " + " ".join(f"{k}={v}" for k, v in zip(keys, combo))
              + "  | " + " ".join(f"{k.split('_')[0]}={avg[k]:.1f}" for k in TARGETS))
    results.sort(key=lambda r: r[0])
    print("\nBEST:")
    for tot, combo, avg in results[:4]:
        print(f"  pen {tot:7.3f}  {combo}")
        print("      " + " ".join(f"{k.split('_')[0]}={avg[k]:.1f}" for k in TARGETS))


if __name__ == "__main__":
    main()
