"""Procedural world generation pipeline.

Produces all terrain layers (height, water, splat, biome, topology, alpha)
for a recipe (theme + size + seed + options), ready to pack into a .map.

Every step is deterministic for a given seed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from ..layers import (
    SEA_LEVEL,
    TERRAIN_HEIGHT,
    Biome,
    Splat,
    Topology,
    heightmap_resolution,
    splatmap_resolution,
)
from . import noise
from .themes import THEMES, ThemeSpec

SEA_M = SEA_LEVEL * TERRAIN_HEIGHT  # 500m


@dataclass
class Recipe:
    size: int = 3000
    seed: int = 0
    theme: str = "classic"
    land_ratio: float = 0.45          # target fraction of map above sea level
    mountain_scale: float = 1.0       # vertical exaggeration of highlands
    beach_width: float = 1.0          # multiplier on beach band width
    river_density: float = 1.0        # 0 disables rivers
    erosion: bool = True
    biome_blacklist: list[str] = field(default_factory=list)   # e.g. ["arctic"]
    topology_blacklist: list[str] = field(default_factory=list)  # e.g. ["swamp"]
    water_level_offset: float = 0.0   # meters, raises/lowers the sea
    heightmap: np.ndarray | None = None  # optional user-uploaded base heightmap

    def rng(self, salt: int = 0) -> np.random.Generator:
        return np.random.default_rng((self.seed + salt * 7919) & 0xFFFFFFFF)


@dataclass
class GenerationResult:
    size: int
    height01: np.ndarray
    water01: np.ndarray
    splat: np.ndarray
    biome: np.ndarray
    topology: np.ndarray
    stats: dict


ProgressFn = Callable[[float, str], None]


def _noop_progress(_frac: float, _msg: str) -> None:
    pass


# ---------------------------------------------------------------------------
# morphology helpers (numpy only)
# ---------------------------------------------------------------------------

def dilate(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    m = mask.astype(bool)
    for _ in range(iterations):
        m = (
            m
            | np.roll(m, 1, 0) | np.roll(m, -1, 0)
            | np.roll(m, 1, 1) | np.roll(m, -1, 1)
        )
    return m


def erode_mask(mask: np.ndarray, iterations: int = 1) -> np.ndarray:
    return ~dilate(~mask.astype(bool), iterations)


def ring(mask: np.ndarray, width: int) -> np.ndarray:
    """Band around (outside) of a mask."""
    return dilate(mask, width) & ~mask.astype(bool)


def slope_deg(height01: np.ndarray, size: int) -> np.ndarray:
    meters_per_px = size / height01.shape[0]
    dz, dx = np.gradient(height01 * TERRAIN_HEIGHT, meters_per_px)
    return np.degrees(np.arctan(np.hypot(dx, dz)))


# ---------------------------------------------------------------------------
# terrain shaping
# ---------------------------------------------------------------------------

def _fit_land_ratio(height01: np.ndarray, target: float) -> np.ndarray:
    """Shift heights so `target` fraction of the map sits above sea level."""
    if target <= 0.01:
        return height01
    q = np.quantile(height01, 1.0 - target)
    shifted = height01 + (SEA_LEVEL - q)
    return np.clip(shifted, 0.0, 1.0)


def _thermal_erosion(height01: np.ndarray, iterations: int = 12, talus: float = 0.0012) -> np.ndarray:
    """Cheap thermal erosion: move material down steep slopes."""
    h = height01.astype(np.float32).copy()
    for _ in range(iterations):
        moved = np.zeros_like(h)
        for axis, shift in ((0, 1), (0, -1), (1, 1), (1, -1)):
            diff = h - np.roll(h, shift, axis)
            excess = np.maximum(diff - talus, 0.0) * 0.25
            moved -= excess
            moved += np.roll(excess, -shift, axis)
        h += moved * 0.5
    return h


def _carve_rivers(
    height01: np.ndarray,
    water01: np.ndarray,
    size: int,
    recipe: Recipe,
    river_topo: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Trace rivers downhill from highland sources; carve terrain + set water."""
    res = height01.shape[0]
    rng = recipe.rng(5)
    land = height01 > SEA_LEVEL
    high = height01 > np.quantile(height01[land], 0.75) if land.any() else np.zeros_like(land)
    candidates = np.argwhere(high)
    if len(candidates) == 0:
        return height01, water01
    n_rivers = int(np.clip(size / 900, 1, 8) * recipe.river_density)
    if n_rivers <= 0:
        return height01, water01
    h = height01.copy()
    w = water01.copy()
    depth = 1.8 / TERRAIN_HEIGHT       # ~1.8 m channel
    half_width = max(1, res // 512)
    for _ in range(n_rivers):
        z, x = candidates[rng.integers(len(candidates))]
        visited = set()
        for _step in range(res * 2):
            if h[z, x] <= SEA_LEVEL - 2.0 / TERRAIN_HEIGHT:
                break
            visited.add((z, x))
            z0, z1 = max(0, z - half_width), min(res, z + half_width + 1)
            x0, x1 = max(0, x - half_width), min(res, x + half_width + 1)
            bank = h[z0:z1, x0:x1]
            level = bank.min() - depth * 0.3
            h[z0:z1, x0:x1] = np.minimum(bank, bank * 0.2 + (level + depth * 0.3) * 0.8) - depth * 0.2
            w[z0:z1, x0:x1] = np.maximum(w[z0:z1, x0:x1], level)
            river_topo[z0:z1, x0:x1] = True
            # choose lowest neighbor (with tiny jitter to avoid loops)
            best = None
            best_h = np.inf
            for dz in (-1, 0, 1):
                for dx in (-1, 0, 1):
                    if dz == 0 and dx == 0:
                        continue
                    nz, nx = z + dz, x + dx
                    if not (0 <= nz < res and 0 <= nx < res) or (nz, nx) in visited:
                        continue
                    cand = h[nz, nx] + rng.random() * 1e-5
                    if cand < best_h:
                        best_h = cand
                        best = (nz, nx)
            if best is None:
                break
            z, x = best
    return h, w


# ---------------------------------------------------------------------------
# biome / splat / topology
# ---------------------------------------------------------------------------

def _biome_weights(res: int, height01: np.ndarray, recipe: Recipe, theme: ThemeSpec) -> np.ndarray:
    biome = np.zeros((5, res, res), dtype=np.float32)
    if theme.fixed_biome is not None:
        biome[theme.fixed_biome] = 1.0
    else:
        # latitude: row 0 = south (arid) -> row res-1 = north (arctic), noise-warped
        lat = np.linspace(0.0, 1.0, res, dtype=np.float32)[:, None] * np.ones((1, res), np.float32)
        lat = lat + 0.16 * noise.fbm(res, recipe.seed + 41, octaves=4, scale=2.5)
        # altitude pushes colder
        alt = np.maximum(height01 - (SEA_LEVEL + 120 / TERRAIN_HEIGHT), 0) * TERRAIN_HEIGHT / 260.0
        t = np.clip(lat + alt * 0.35, 0.0, 1.0)
        edges = theme.biome_edges  # [arid_end, temperate_end, tundra_end]
        soft = 0.045
        arid = 1.0 - noise.smoothstep(edges[0] - soft, edges[0] + soft, t)
        temperate = noise.smoothstep(edges[0] - soft, edges[0] + soft, t) * (
            1.0 - noise.smoothstep(edges[1] - soft, edges[1] + soft, t))
        tundra = noise.smoothstep(edges[1] - soft, edges[1] + soft, t) * (
            1.0 - noise.smoothstep(edges[2] - soft, edges[2] + soft, t))
        arctic = noise.smoothstep(edges[2] - soft, edges[2] + soft, t)
        biome[Biome.ARID] = arid
        biome[Biome.TEMPERATE] = temperate
        biome[Biome.TUNDRA] = tundra
        biome[Biome.ARCTIC] = arctic
        if theme.jungle and "jungle" not in recipe.biome_blacklist:
            jm = noise.fbm(res, recipe.seed + 303, octaves=4, scale=3.0) > 0.38
            jm &= t < edges[0] * 1.35  # warm latitudes only
            biome[Biome.JUNGLE][jm] = 1.0
            for idx in (Biome.ARID, Biome.TEMPERATE, Biome.TUNDRA, Biome.ARCTIC):
                biome[idx][jm] *= 0.1

    # blacklist + renormalize
    name_to_idx = {b.name.lower(): int(b) for b in Biome}
    for name in recipe.biome_blacklist:
        idx = name_to_idx.get(name.lower())
        if idx is not None:
            biome[idx] = 0.0
    total = biome.sum(axis=0)
    fallback = np.argmax(biome.sum(axis=(1, 2)))  # most common remaining biome
    dead = total < 1e-6
    biome[fallback][dead] = 1.0
    total = biome.sum(axis=0)
    biome /= np.maximum(total, 1e-6)
    return biome


def _splat_weights(
    res: int,
    height01: np.ndarray,
    water01: np.ndarray,
    biome: np.ndarray,
    recipe: Recipe,
    theme: ThemeSpec,
    forest_mask: np.ndarray,
) -> np.ndarray:
    splat = np.zeros((8, res, res), dtype=np.float32)
    h_m = height01 * TERRAIN_HEIGHT
    slope = slope_deg(height01, recipe.size)
    sea = SEA_M + recipe.water_level_offset

    beach_band = 4.0 * recipe.beach_width * theme.beach_scale
    sand = np.clip(1.0 - np.abs(h_m - sea) / max(beach_band, 0.5), 0.0, 1.0)
    sand = np.maximum(sand, (h_m < sea) & (h_m > sea - 14.0))  # shallow seabed
    rock = noise.smoothstep(theme.rock_slope - 8, theme.rock_slope + 10, slope)
    rock = np.maximum(rock, noise.smoothstep(0.78, 0.92, height01) * 0.8)
    dirt = noise.smoothstep(theme.rock_slope - 22, theme.rock_slope - 4, slope) * (1 - rock)
    dirt = np.maximum(dirt, (noise.fbm(res, recipe.seed + 77, octaves=4, scale=5.0) > 0.30) * 0.5)
    stones = (noise.fbm(res, recipe.seed + 88, octaves=3, scale=7.0) > 0.42) * rock * 0.8
    gravel = (noise.fbm(res, recipe.seed + 99, octaves=3, scale=6.0) > 0.48) * 0.4

    snowline = (biome[Biome.ARCTIC] > 0.5) | (height01 > theme.snow_height)
    snow = np.where(snowline, 1.0, 0.0) * (1 - sand)
    forest = forest_mask.astype(np.float32) * 0.9

    grass = np.ones((res, res), dtype=np.float32) * 0.8
    grass *= 1.0 - biome[Biome.ARID] * 0.55        # arid -> more dirt/sand
    dirt = np.maximum(dirt, biome[Biome.ARID] * 0.5)

    if theme.barren:  # moon/mars: no grass/forest/snow unless theme says so
        grass *= 0.0
        forest *= 0.0
        if not theme.snow:
            snow *= 0.0
        if theme.palette == "grey":      # lunar regolith
            rock = np.maximum(rock, 0.55)
            gravel = np.maximum(gravel, 0.3)
            stones = np.maximum(stones, 0.18)
            dirt *= 0.05
            sand *= 0.1
        else:                            # red/tan (mars)
            dirt = np.maximum(dirt, 0.55)
            rock = np.maximum(rock, 0.28)
            gravel = np.maximum(gravel, 0.15)

    splat[Splat.SAND] = sand
    splat[Splat.ROCK] = rock * (1 - sand)
    splat[Splat.DIRT] = dirt * (1 - sand) * (1 - rock)
    splat[Splat.GRASS] = grass * (1 - sand) * (1 - rock) * (1 - snow)
    splat[Splat.FOREST] = forest * (1 - sand) * (1 - rock) * (1 - snow)
    splat[Splat.SNOW] = snow * (1 - sand * 0.7)
    splat[Splat.STONES] = stones
    splat[Splat.GRAVEL] = gravel * (1 - sand)

    total = splat.sum(axis=0)
    empty = total < 1e-5
    splat[Splat.DIRT][empty] = 1.0
    splat /= np.maximum(splat.sum(axis=0), 1e-6)
    return splat


def _topology(
    res: int,
    height01: np.ndarray,
    water01: np.ndarray,
    splat: np.ndarray,
    biome: np.ndarray,
    recipe: Recipe,
    theme: ThemeSpec,
    forest_mask: np.ndarray,
    river_mask: np.ndarray,
) -> np.ndarray:
    topo = np.zeros((res, res), dtype=np.int64)
    h_m = height01 * TERRAIN_HEIGHT
    sea = SEA_M + recipe.water_level_offset
    slope = slope_deg(height01, recipe.size)
    px_per_m = res / recipe.size

    land = h_m > sea
    ocean = ~land & ~river_mask
    deep = h_m < sea - 15.0

    topo[ocean] |= Topology.OCEAN
    topo[deep & ocean] |= Topology.OFFSHORE

    beach = land & (h_m < sea + 3.2 * recipe.beach_width * theme.beach_scale) & (slope < 22)
    coast_ring = dilate(ocean, max(1, int(14 * px_per_m)))
    beach &= coast_ring
    topo[beach] |= Topology.BEACH
    beachside = ring(beach, max(1, int(10 * px_per_m))) & land
    topo[beachside] |= Topology.BEACHSIDE

    oceanside = dilate(ocean, max(1, int(42 * px_per_m))) & land
    topo[oceanside] |= Topology.OCEANSIDE

    topo[land] |= Topology.MAINLAND

    cliff = slope > 45
    topo[cliff] |= Topology.CLIFF
    cliffside = ring(cliff, max(1, int(8 * px_per_m))) & land & ~cliff
    topo[cliffside] |= Topology.CLIFFSIDE

    if land.any():
        land_h = h_m[land]
        summit = land & (h_m > np.quantile(land_h, 0.985))
        hilltop = land & (h_m > np.quantile(land_h, 0.94)) & ~summit
        mountain = land & (h_m > np.quantile(land_h, 0.88))
        topo[summit] |= Topology.SUMMIT
        topo[hilltop] |= Topology.HILLTOP
        topo[mountain] |= Topology.MOUNTAIN

    forest = forest_mask & land
    topo[forest] |= Topology.FOREST
    forestside = ring(forest, max(1, int(10 * px_per_m))) & land & ~forest
    topo[forestside] |= Topology.FORESTSIDE

    field_ = land & ~forest & ~beach & ~cliff & (slope < 18)
    topo[field_] |= Topology.FIELD

    decor = land & ~beach & (noise.fbm(res, recipe.seed + 404, octaves=3, scale=6.0) > 0.05)
    topo[decor] |= Topology.DECOR
    clutter = land & (noise.fbm(res, recipe.seed + 505, octaves=3, scale=8.0) > 0.25)
    topo[clutter] |= Topology.CLUTTER
    alt = forest & (noise.fbm(res, recipe.seed + 606, octaves=3, scale=5.0) > 0.3)
    topo[alt] |= Topology.ALT

    if "swamp" not in recipe.topology_blacklist and theme.swamps:
        swamp = (
            land
            & (h_m < sea + 2.0)
            & (slope < 6)
            & ~beach
            & (biome[Biome.TEMPERATE] + biome[Biome.JUNGLE] > 0.5)
            & (noise.fbm(res, recipe.seed + 707, octaves=3, scale=4.0) > 0.3)
        )
        topo[swamp] |= Topology.SWAMP

    if river_mask.any():
        topo[river_mask] |= Topology.RIVER
        riverside = ring(river_mask, max(1, int(12 * px_per_m))) & land
        topo[riverside] |= Topology.RIVERSIDE

    # tier zones: south -> Tier0, middle -> Tier1, north -> Tier2 (vanilla-like)
    lat = np.linspace(0.0, 1.0, res, dtype=np.float32)[:, None] * np.ones((1, res), np.float32)
    lat = lat + 0.1 * noise.fbm(res, recipe.seed + 42, octaves=3, scale=2.0)
    topo[lat < 0.40] |= Topology.TIER0
    topo[(lat >= 0.40) & (lat < 0.72)] |= Topology.TIER1
    topo[lat >= 0.72] |= Topology.TIER2

    # guarantee valid player spawns: every beach gets Tier0 (spawn needs
    # TIER0 | BEACH | OCEANSIDE | MAINLAND overlap)
    topo[beach] |= Topology.TIER0

    # fallback: if the combined spawn mask is too small (tiny-island themes),
    # force-paint the full spawn flag set on flat land near the coast
    spawn_flags = int(Topology.TIER0 | Topology.BEACH | Topology.OCEANSIDE | Topology.MAINLAND)
    m2_per_px = (recipe.size / res) ** 2
    spawn_area = ((topo & spawn_flags) == spawn_flags).sum() * m2_per_px
    if spawn_area < 20000:
        coastal_flat = dilate(ocean, max(1, int(30 * px_per_m))) & land & (slope < 40)
        topo[coastal_flat] |= spawn_flags

    name_to_flag = {t.name.lower(): int(t) for t in Topology}
    for name in recipe.topology_blacklist:
        flag = name_to_flag.get(name.lower())
        if flag:
            topo &= ~flag

    return topo.astype(np.int32)


# ---------------------------------------------------------------------------
# main entry
# ---------------------------------------------------------------------------

def generate(recipe: Recipe, progress: ProgressFn = _noop_progress) -> GenerationResult:
    theme = THEMES.get(recipe.theme)
    if theme is None:
        raise ValueError(f"unknown theme '{recipe.theme}' (have: {sorted(THEMES)})")
    size = int(np.clip(recipe.size, 1000, 6000))
    h_res = heightmap_resolution(size)
    s_res = splatmap_resolution(size)

    progress(0.05, "Shaping terrain")
    if recipe.heightmap is not None:
        from ..heightmap_io import resample
        height01 = resample(recipe.heightmap, h_res)
    else:
        height01 = theme.build_height(h_res, recipe)
        if not theme.dry:  # dry themes control their own floor (no crater lakes)
            height01 = _fit_land_ratio(height01, recipe.land_ratio * theme.land_ratio_scale)

    if recipe.erosion and theme.erosion:
        progress(0.25, "Eroding terrain")
        height01 = _thermal_erosion(height01, iterations=10)

    # flatten a gentle shelf around the shoreline for spawnable beaches:
    # compress the vertical zone around sea level so coasts meet the water
    # at a walkable grade
    sea = SEA_LEVEL + recipe.water_level_offset / TERRAIN_HEIGHT
    band = 0.004 * recipe.beach_width * theme.beach_scale
    if theme.shelf > 0 and band > 0:
        blend_zone = band * 4.0
        t = noise.smoothstep(sea - blend_zone, sea + blend_zone, height01)
        flattened = (sea - band) + t * 2.0 * band
        w = np.clip(1.0 - np.abs(height01 - sea) / blend_zone, 0.0, 1.0) * theme.shelf
        height01 = height01 * (1 - w) + flattened * w

    water01 = np.full_like(height01, SEA_LEVEL + recipe.water_level_offset / TERRAIN_HEIGHT)
    river_mask_h = np.zeros_like(height01, dtype=bool)
    if theme.rivers and recipe.river_density > 0:
        progress(0.35, "Carving rivers")
        height01, water01 = _carve_rivers(height01, water01, size, recipe, river_mask_h)

    height01 = np.clip(height01, 0.0, 1.0).astype(np.float32)

    # --- layer-space (splat res) -----------------------------------------
    progress(0.5, "Painting biomes")
    from ..heightmap_io import resample
    h_layer = resample(height01, s_res)
    w_layer = resample(water01, s_res)
    river_mask = resample(river_mask_h.astype(np.float32), s_res) > 0.4

    biome = _biome_weights(s_res, h_layer, recipe, theme)

    progress(0.62, "Painting ground textures")
    forest_noise = noise.warped_fbm(s_res, recipe.seed + 9001, octaves=4, scale=theme.forest_scale)
    land_layer = h_layer > SEA_LEVEL + recipe.water_level_offset / TERRAIN_HEIGHT
    forest_mask = (forest_noise > theme.forest_threshold) & land_layer
    forest_mask &= slope_deg(h_layer, size) < 32
    if theme.barren:
        forest_mask &= False

    splat = _splat_weights(s_res, h_layer, w_layer, biome, recipe, theme, forest_mask)

    progress(0.78, "Marking topology")
    topology = _topology(s_res, h_layer, w_layer, splat, biome, recipe, theme, forest_mask, river_mask)

    progress(0.9, "Validating")
    spawn = (topology & (Topology.TIER0 | Topology.BEACH | Topology.OCEANSIDE | Topology.MAINLAND))
    spawn_ok = (spawn == int(Topology.TIER0 | Topology.BEACH | Topology.OCEANSIDE | Topology.MAINLAND))
    land_frac = float(land_layer.mean())
    m2_per_px = (size / s_res) ** 2
    stats = {
        "size": size,
        "seed": recipe.seed,
        "theme": recipe.theme,
        "heightmap_resolution": h_res,
        "layer_resolution": s_res,
        "land_percent": round(land_frac * 100, 2),
        "spawn_area_m2": int(spawn_ok.sum() * m2_per_px),
        "spawn_valid": bool(spawn_ok.sum() * m2_per_px > 5000),
        "biome_percent": {
            b.name.lower(): round(float(biome[b][land_layer].mean() if land_layer.any() else 0) * 100, 2)
            for b in Biome
        },
        "max_height_m": round(float(height01.max()) * TERRAIN_HEIGHT - SEA_M, 1),
        "ocean_depth_m": round(SEA_M - float(height01.min()) * TERRAIN_HEIGHT, 1),
    }
    progress(1.0, "Done")
    return GenerationResult(
        size=size,
        height01=height01,
        water01=np.clip(water01, 0.0, 1.0).astype(np.float32),
        splat=splat,
        biome=biome,
        topology=topology,
        stats=stats,
    )
