"""1:1 NumPy port of Facepunch's MapImageRenderer (decompiled Assembly-CSharp).

Produces the exact 2D map image the game / RustMaps generate, driven purely by
the heightmap, splat map and water level — plus overlay renderers for layers
(biome, topology, spawn masks) used by the web UI.
"""
from __future__ import annotations

import io

import numpy as np
from PIL import Image

from .layers import SEA_LEVEL, TERRAIN_HEIGHT, Biome, Splat, Topology

# --- exact constants from MapImageRenderer ---------------------------------
START_COLOR = np.array([0.28627452, 23 / 85, 0.24705884, 1.0], dtype=np.float32)
WATER_COLOR = np.array([0.16941601, 0.31755757, 0.36200002, 1.0], dtype=np.float32)
GRAVEL_COLOR = np.array([0.25, 37 / 152, 0.22039475, 1.0], dtype=np.float32)
DIRT_COLOR = np.array([0.6, 0.47959462, 0.33, 1.0], dtype=np.float32)
SAND_COLOR = np.array([0.7, 0.65968585, 0.5277487, 1.0], dtype=np.float32)
GRASS_COLOR = np.array([0.35486364, 0.37, 0.2035, 1.0], dtype=np.float32)
FOREST_COLOR = np.array([0.24843751, 0.3, 9 / 128, 1.0], dtype=np.float32)
ROCK_COLOR = np.array([0.4, 0.39379844, 0.37519377, 1.0], dtype=np.float32)
SNOW_COLOR = np.array([0.86274517, 0.9294118, 0.94117653, 1.0], dtype=np.float32)
PEBBLE_COLOR = np.array([7 / 51, 0.2784314, 0.2761563, 1.0], dtype=np.float32)
OFFSHORE_COLOR = np.array([0.04090196, 0.22060032, 14 / 51, 1.0], dtype=np.float32)
SUN_DIRECTION = np.array([0.95, 2.87, 2.37], dtype=np.float32)
SUN_DIRECTION /= np.linalg.norm(SUN_DIRECTION)
SUN_POWER = 0.65
BRIGHTNESS = 1.05
CONTRAST = 0.94
OCEAN_WATER_LEVEL = 0.0

# splat blend order used by the renderer: (channel index, color)
_SPLAT_BLEND = [
    (Splat.GRAVEL, GRAVEL_COLOR),
    (Splat.STONES, PEBBLE_COLOR),
    (Splat.ROCK, ROCK_COLOR),
    (Splat.DIRT, DIRT_COLOR),
    (Splat.GRASS, GRASS_COLOR),
    (Splat.FOREST, FOREST_COLOR),
    (Splat.SAND, SAND_COLOR),
    (Splat.SNOW, SNOW_COLOR),
]


def _bilinear(grid: np.ndarray, u: np.ndarray, v: np.ndarray) -> np.ndarray:
    """Bilinear sample grid[z, x] at normalized coords u (x), v (z) with clamping."""
    res_z, res_x = grid.shape
    fx = np.clip(u, 0.0, 1.0) * (res_x - 1)
    fz = np.clip(v, 0.0, 1.0) * (res_z - 1)
    x0 = np.floor(fx).astype(np.int32)
    z0 = np.floor(fz).astype(np.int32)
    x1 = np.minimum(x0 + 1, res_x - 1)
    z1 = np.minimum(z0 + 1, res_z - 1)
    tx = (fx - x0).astype(np.float32)
    tz = (fz - z0).astype(np.float32)
    g00 = grid[z0, x0]
    g10 = grid[z0, x1]
    g01 = grid[z1, x0]
    g11 = grid[z1, x1]
    return (g00 * (1 - tx) + g10 * tx) * (1 - tz) + (g01 * (1 - tx) + g11 * tx) * tz


def _normals(height_m: np.ndarray, meters_per_px: float) -> np.ndarray:
    """Per-texel world-space normals (y-up) from a heightmap in meters."""
    dz, dx = np.gradient(height_m, meters_per_px)
    n = np.stack([-dx, np.ones_like(dx), -dz], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return n.astype(np.float32)


def render_map_image(
    size: int,
    height01: np.ndarray,
    splat: np.ndarray,          # (8, res, res) float weights 0..1
    water01: np.ndarray | None = None,
    image_res: int | None = None,
    ocean_margin_frac: float = 0.08,
) -> Image.Image:
    """Render the official map preview. Returns a PIL image, north up."""
    if image_res is None:
        image_res = int(np.clip(size // 2, 256, 2048))
    margin = int(image_res * ocean_margin_frac)
    full = image_res + margin * 2

    # sample grid in map UV space (may extend past [0,1]; clamped like the game)
    coord = (np.arange(full, dtype=np.float32) - margin) / image_res
    u, v = np.meshgrid(coord, coord)  # u = x, v = z (row)

    height_m = (_bilinear(height01, u, v) * TERRAIN_HEIGHT) - SEA_LEVEL * TERRAIN_HEIGHT
    if water01 is not None:
        water_m = (_bilinear(water01, u, v) * TERRAIN_HEIGHT) - SEA_LEVEL * TERRAIN_HEIGHT
    else:
        water_m = np.zeros_like(height_m)
    water_m = np.maximum(water_m, OCEAN_WATER_LEVEL)

    # sun term from heightmap normals (sampled at image res)
    meters_per_px = size / image_res
    hm_img = _bilinear(height01, u, v) * TERRAIN_HEIGHT
    normals = _normals(hm_img, meters_per_px)
    sun = np.maximum(normals @ SUN_DIRECTION, 0.0).astype(np.float32)

    color = np.broadcast_to(START_COLOR[:3], (full, full, 3)).astype(np.float32).copy()
    for channel, c4 in _SPLAT_BLEND:
        w = (_bilinear(splat[channel], u, v) * c4[3]).astype(np.float32)[..., None]
        color = color * (1 - w) + c4[:3] * w

    depth = water_m - height_m
    underwater = depth > 0.0

    # land shading
    shade = color + (sun[..., None] - 0.5) * SUN_POWER * color
    shade = (shade - 0.5) * CONTRAST + 0.5
    # water blend
    wblend = np.clip(0.5 + depth / 5.0, 0.0, 1.0).astype(np.float32)[..., None]
    oblend = np.clip(depth / 50.0, 0.0, 1.0).astype(np.float32)[..., None]
    water_px = color * (1 - wblend) + WATER_COLOR[:3] * wblend
    water_px = water_px * (1 - oblend) + OFFSHORE_COLOR[:3] * oblend

    out = np.where(underwater[..., None], water_px, shade) * BRIGHTNESS
    out = np.clip(out, 0.0, 1.0)

    img = (out * 255 + 0.5).astype(np.uint8)
    # row 0 of our arrays = world -z (south); images are drawn north-up
    return Image.fromarray(img[::-1])


# ---------------------------------------------------------------------------
# overlay renderers (web UI layers)
# ---------------------------------------------------------------------------

BIOME_COLORS = {
    Biome.ARID: (218, 180, 90),
    Biome.TEMPERATE: (96, 160, 72),
    Biome.TUNDRA: (140, 134, 100),
    Biome.ARCTIC: (235, 240, 245),
    Biome.JUNGLE: (26, 120, 54),
}


def render_biome_image(biome: np.ndarray) -> Image.Image:
    """Dominant-biome color image with weight blending."""
    channels = biome.shape[0]
    res = biome.shape[1]
    out = np.zeros((res, res, 3), dtype=np.float32)
    total = np.maximum(biome.sum(axis=0), 1e-6)
    for idx in range(channels):
        c = np.array(BIOME_COLORS[Biome(idx)], dtype=np.float32)
        out += (biome[idx] / total)[..., None] * c
    return Image.fromarray(np.clip(out, 0, 255).astype(np.uint8)[::-1])


def render_mask_overlay(mask: np.ndarray, rgba: tuple[int, int, int, int]) -> Image.Image:
    """Transparent PNG with `rgba` wherever mask is truthy."""
    res = mask.shape[0]
    out = np.zeros((res, res, 4), dtype=np.uint8)
    out[mask.astype(bool)] = rgba
    return Image.fromarray(out[::-1])


def render_topology_overlay(topology: np.ndarray, flag: int, rgba: tuple[int, int, int, int]) -> Image.Image:
    return render_mask_overlay((topology & flag) != 0, rgba)


# ---------------------------------------------------------------------------
# spawn heuristic masks (see docs/RESEARCH.md §3)
# ---------------------------------------------------------------------------

def player_spawn_mask(topology: np.ndarray) -> np.ndarray:
    need = Topology.TIER0 | Topology.BEACH | Topology.OCEANSIDE | Topology.MAINLAND
    return (topology & need) == need


def ore_spawn_mask(topology: np.ndarray) -> np.ndarray:
    ore_topo = Topology.CLIFFSIDE | Topology.DECOR | Topology.CLUTTER
    blocked = (
        Topology.ROAD | Topology.BUILDING | Topology.MONUMENT
        | Topology.CLIFF | Topology.OCEAN | Topology.LAKE | Topology.RIVER
    )
    return ((topology & ore_topo) != 0) & ((topology & blocked) == 0)


def animal_spawn_mask(topology: np.ndarray) -> np.ndarray:
    blocked = (
        Topology.ROAD | Topology.BUILDING | Topology.MONUMENT | Topology.CLIFF
        | Topology.OCEAN | Topology.LAKE | Topology.RIVER | Topology.RAIL
    )
    return ((topology & Topology.MAINLAND) != 0) & ((topology & blocked) == 0)


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
