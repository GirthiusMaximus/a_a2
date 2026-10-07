"""Theme definitions: parameter presets + height-field builders.

Each builder's landform rules come from reference-imagery research documented
in docs/THEMES.md (vanilla Rust renders, atolls, cinder cones, Kornati,
Canyonlands NP, lunar/martian orbital photos, floating-island art).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional, TYPE_CHECKING

import numpy as np

from ..layers import SEA_LEVEL, TERRAIN_HEIGHT, Biome
from . import noise

if TYPE_CHECKING:
    from .pipeline import Recipe

HeightBuilder = Callable[[int, "Recipe"], np.ndarray]


@dataclass
class ThemeSpec:
    key: str
    label: str
    description: str
    build_height: HeightBuilder
    biome_edges: tuple[float, float, float] = (0.35, 0.62, 0.8)  # arid|temp|tundra|arctic
    fixed_biome: Optional[int] = None
    jungle: bool = True
    swamps: bool = True
    rivers: bool = True
    erosion: bool = True
    barren: bool = False          # no grass/forest (moon, mars)
    dry: bool = False             # builder owns the sea/land split (skip ratio fit)
    palette: str = "default"      # barren splat palette: "grey" | "red" | "default"
    snow: bool = False            # allow snow even when barren
    rock_slope: float = 38.0      # degrees where rock splat takes over
    snow_height: float = 0.82     # normalized height snowline
    forest_scale: float = 4.0
    forest_threshold: float = 0.22
    beach_scale: float = 1.0
    shelf: float = 0.85           # strength of shoreline flattening
    land_ratio_scale: float = 1.0
    biome_rotation: float = 0.0   # max radians of seed-random biome-axis tilt


def _amp(recipe: "Recipe") -> float:
    return 0.11 * recipe.mountain_scale


def _centered(res: int) -> tuple[np.ndarray, np.ndarray]:
    c = np.linspace(-1.0, 1.0, res, dtype=np.float32)
    return np.meshgrid(c, c)


# --- height builders -------------------------------------------------------

def classic(res: int, recipe: "Recipe") -> np.ndarray:
    """Vanilla-style: landmass fills the square, heavily lobed coast,
    lowland interior with scattered hill clusters (see docs/THEMES.md)."""
    s = recipe.seed
    border = noise.square_falloff(res, margin=0.13)
    lobes = noise.fbm(res, s + 2, octaves=5, scale=4.4)
    inland = noise.smoothstep(0.26, 0.54, border + lobes * 0.30)

    base = noise.warped_fbm(res, s, octaves=6, scale=3.8, warp=0.45)
    hills = noise.ridged(res, s + 1, octaves=5, scale=3.1)
    hillmask = noise.smoothstep(0.05, 0.62, noise.fbm(res, s + 3, octaves=3, scale=2.2))

    h = (
        SEA_LEVEL - 0.036
        + inland * (0.048 + base * 0.006)
        + hills * hillmask * inland * 0.105 * recipe.mountain_scale
    )
    return np.clip(h, 0.0, 1.0)


def circular_isle(res: int, recipe: "Recipe") -> np.ndarray:
    """Atoll-style: round island, bright shallow reef shelf ring with
    sandbars, then a sharp drop to deep ocean."""
    s = recipe.seed
    x, y = _centered(res)
    d = np.sqrt(x * x + y * y)
    d_w = d + 0.09 * noise.fbm(res, s + 5, octaves=4, scale=3.0)

    core = noise.smoothstep(0.64, 0.30, d_w)
    peak = noise.smoothstep(0.50, 0.08, d_w)
    base = noise.fbm(res, s, octaves=5, scale=3.2)

    deep = SEA_LEVEL - 0.05
    shelf_level = SEA_LEVEL - 0.0035 + 0.0012 * noise.fbm(res, s + 6, octaves=3, scale=8.0)
    ring_t = noise.smoothstep(0.99, 0.86, d_w)
    sea_floor = deep + (shelf_level - deep) * ring_t
    bars = noise.smoothstep(0.66, 0.78, noise.fbm(res, s + 7, octaves=4, scale=5.5))
    sea_floor = sea_floor + bars * ring_t * (1.0 - core) * 0.0045

    island = deep + core * (SEA_LEVEL + 0.012 - deep) + peak * (
        0.030 + 0.065 * recipe.mountain_scale) + core * base * 0.014
    h = np.maximum(sea_floor, island)
    return np.clip(h, 0.0, 1.0)


def volcano(res: int, recipe: "Recipe") -> np.ndarray:
    """Cinder-cone island: steep central edifice with a flat caldera and
    radial gullies, broad low lava apron, secondary flank cones."""
    s = recipe.seed
    rng = recipe.rng(21)
    x, y = _centered(res)
    cx0 = (rng.random() - 0.5) * 0.2
    cy0 = (rng.random() - 0.5) * 0.2
    dx, dy = x - cx0, y - cy0
    d = np.sqrt(dx * dx + dy * dy)
    az = np.arctan2(dy, dx)

    gully = 1.0 + 0.055 * np.sin(az * 9.0 + noise.fbm(res, s + 4, octaves=3, scale=3.0) * 4.0)
    cone = np.clip(1.0 - (d * gully) / 0.46, 0.0, 1.0) ** 1.9
    crater = noise.smoothstep(0.085, 0.048, d)

    apron = np.clip(1.0 - d / 1.02, 0.0, 1.0) ** 1.15
    rough = noise.fbm(res, s, octaves=5, scale=4.0)

    ms = recipe.mountain_scale
    h = (
        SEA_LEVEL - 0.034
        + apron * (0.040 + rough * 0.010)
        + cone * 0.185 * ms
        - crater * 0.060 * ms
    )
    # secondary cinder cones on the flanks
    for i in range(2):
        ang = rng.random() * 2 * np.pi
        r0 = 0.42 + rng.random() * 0.25
        scx, scy = np.cos(ang) * r0, np.sin(ang) * r0
        sd = np.sqrt((x - scx) ** 2 + (y - scy) ** 2)
        sc = np.clip(1.0 - sd / (0.055 + rng.random() * 0.03), 0.0, 1.0) ** 1.6
        svent = noise.smoothstep(0.016, 0.009, sd)
        h = h + sc * 0.030 * ms - svent * 0.012 * ms
    return np.clip(h, 0.0, 1.0)


def archipelago(res: int, recipe: "Recipe") -> np.ndarray:
    """Kornati-style: elongated islands aligned along a seed-random axis —
    drowned parallel ridgelines with narrow straits."""
    s = recipe.seed
    theta = float(recipe.rng(31).random()) * np.pi
    x, y = _centered(res)
    u = np.cos(theta) * x + np.sin(theta) * y      # along chain axis
    v = -np.sin(theta) * x + np.cos(theta) * y     # across chains
    wx = noise.fbm(res, s + 101, octaves=3, scale=2.6)
    wy = noise.fbm(res, s + 202, octaves=3, scale=2.6)
    chains = noise.fbm_at(u * 1.15 + wx * 0.7, v * 4.4 + wy * 0.7, s, octaves=4)
    detail = noise.warped_fbm(res, s + 9, octaves=4, scale=4.5, warp=0.4)
    base = chains * 0.75 + detail * 0.3
    border = noise.square_falloff(res, margin=0.08)
    h = SEA_LEVEL - 0.042 + (base + 0.10) * _amp(recipe) * 1.2 * border
    return np.clip(h, 0.0, 1.0)


def canyonlands(res: int, recipe: "Recipe") -> np.ndarray:
    """Canyonlands NP: flat high plateau cut by branching gorge networks with
    terraced vertical walls."""
    s = recipe.seed
    border = noise.square_falloff(res, margin=0.14)
    lobes = noise.fbm(res, s + 2, octaves=4, scale=3.6)
    inland = noise.smoothstep(0.10, 0.50, border + lobes * 0.25)

    ms = recipe.mountain_scale
    top_relief = noise.fbm(res, s, octaves=5, scale=3.0)
    plateau = SEA_LEVEL - 0.030 + inland * (0.052 + 0.020 * ms + top_relief * 0.004)

    # canyon networks: warped single-octave ridge lines at two scales
    x, y = noise.grid(res, 2.7)
    wx = noise.fbm(res, s + 51, octaves=3, scale=2.4) * 0.5
    wy = noise.fbm(res, s + 52, octaves=3, scale=2.4) * 0.5
    gorge = noise.ridged_at(x + wx, y + wy, s + 4, octaves=1)
    x2, y2 = noise.grid(res, 5.2)
    trib = noise.ridged_at(x2 + wx * 1.4, y2 + wy * 1.4, s + 5, octaves=1)
    carve = (
        noise.smoothstep(0.74, 0.92, gorge) * (0.042 + 0.014 * ms)
        + noise.smoothstep(0.82, 0.94, trib) * 0.018
    ) * inland
    h = plateau - carve

    above = h - SEA_LEVEL
    terr = noise.terrace(np.maximum(above, 0.0), 0.016, 5.0)
    h = np.where(above > 0, SEA_LEVEL + terr, h)
    return np.clip(h, 0.0, 1.0)


def _crater_field(
    res: int,
    recipe: "Recipe",
    count: int,
    r_min: float,
    r_max: float,
    salt: int = 11,
    size_bias: float = 2.8,
    peak_r: float = 0.05,
) -> np.ndarray:
    """Impact craters with power-law sizes, flat floors, raised rims and
    central peaks in the large ones (lunar reference)."""
    rng = recipe.rng(salt)
    c = np.linspace(0.0, 1.0, res, dtype=np.float32)
    x, y = np.meshgrid(c, c)
    out = np.zeros((res, res), dtype=np.float32)
    for _ in range(count):
        cx, cy = rng.random(), rng.random()
        r = r_min * (r_max / r_min) ** (rng.random() ** size_bias)
        d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / r
        inside = d < 1.6
        if not inside.any():
            continue
        depth = r * 7.0
        wall = noise.smoothstep(0.45, 0.95, d)          # flat floor -> rim
        rim = np.exp(-((d - 1.0) ** 2) * 16.0) * 0.38
        bowl = (wall - 1.0) * noise.smoothstep(1.35, 1.05, d)
        crater = (bowl + rim) * depth
        if r > peak_r:
            crater = crater + np.exp(-((d * 3.4) ** 2)) * 0.55 * depth
        out += crater
    return out


def _dry_floor(h: np.ndarray, island: np.ndarray) -> np.ndarray:
    """Flatten crater floors at a dry level just above the sea, inland only."""
    floor = SEA_LEVEL + 0.004
    inland = island > 0.30
    return np.where(inland, np.maximum(h, floor), h)


def moon(res: int, recipe: "Recipe") -> np.ndarray:
    """Lunar: power-law crater saturation, central peaks, smooth maria
    basins against rough highlands."""
    s = recipe.seed
    rolling = noise.fbm(res, s, octaves=5, scale=3.4) * 0.5
    craters = _crater_field(res, recipe, count=110, r_min=0.011, r_max=0.105)

    # maria: broad smooth basins
    rng = recipe.rng(13)
    c = np.linspace(0.0, 1.0, res, dtype=np.float32)
    x, y = np.meshgrid(c, c)
    maria = np.zeros((res, res), dtype=np.float32)
    for _ in range(2):
        mx, my = 0.2 + rng.random() * 0.6, 0.2 + rng.random() * 0.6
        mr = 0.16 + rng.random() * 0.14
        md = np.sqrt((x - mx) ** 2 + (y - my) ** 2) / mr
        maria = np.maximum(maria, np.exp(-md * md))

    island = noise.radial_falloff(res, power=2.2, radius=1.12)
    island = np.clip(island + 0.10 * noise.fbm(res, s + 2, octaves=4, scale=3.2), 0.0, 1.0)
    relief = rolling * 0.55 * (1.0 - maria * 0.85) + craters * (1.0 - maria * 0.45) - maria * 0.30
    h = SEA_LEVEL - 0.02 + island * 0.047 + relief * _amp(recipe) * island
    return np.clip(_dry_floor(h, island), 0.0, 1.0)


def mars(res: int, recipe: "Recipe") -> np.ndarray:
    """Martian: one colossal Valles-Marineris-style rift with terraced walls,
    sparse craters and directional dune ripples."""
    s = recipe.seed
    rng = recipe.rng(17)
    theta = float(rng.random()) * np.pi
    x, y = _centered(res)
    u = np.cos(theta) * x + np.sin(theta) * y
    v = -np.sin(theta) * x + np.cos(theta) * y
    v_w = v + 0.12 * noise.fbm(res, s + 61, octaves=4, scale=1.9) \
        + 0.10 * (float(rng.random()) - 0.5)

    ms = recipe.mountain_scale
    rift = noise.smoothstep(0.16, 0.045, np.abs(v_w))
    rift = np.maximum(rift, noise.smoothstep(0.075, 0.025, np.abs(v_w - 0.26)) * 0.65)
    rift = noise.terrace(rift, 0.34, 5.0)              # stepped canyon walls
    chaos = noise.fbm(res, s + 62, octaves=5, scale=6.0) * rift * 0.10

    plains = noise.warped_fbm(res, s, octaves=5, scale=3.6, warp=0.5) * 0.28
    craters = _crater_field(res, recipe, count=16, r_min=0.013, r_max=0.055,
                            salt=11, peak_r=0.04)
    dunefield = noise.smoothstep(0.15, 0.55, noise.fbm(res, s + 64, octaves=3, scale=2.2))
    ripple = np.sin(u * 150.0 + noise.fbm(res, s + 63, octaves=3, scale=5.0) * 7.0)
    ripple = ripple.astype(np.float32) * 0.0045 * dunefield * (1.0 - rift)

    island = noise.radial_falloff(res, power=2.3, radius=1.1)
    island = np.clip(island + 0.10 * noise.fbm(res, s + 2, octaves=4, scale=3.2), 0.0, 1.0)
    relief = plains + craters + ripple + chaos - rift * (0.62 + 0.25 * ms)
    h = SEA_LEVEL - 0.02 + island * 0.044 + relief * _amp(recipe) * island
    return np.clip(_dry_floor(h, island), 0.0, 1.0)


def naval(res: int, recipe: "Recipe") -> np.ndarray:
    """Open ocean scattered with small round islets of varied size; some
    cells stay submerged as shoals."""
    s = recipe.seed
    f1, _f2, cv, _cv2 = noise.worley(res, s + 7, cells=6, jitter=0.95)
    f1 = f1 + 0.12 * noise.fbm(res, s + 8, octaves=4, scale=6.0)
    size_boost = 0.55 + recipe.land_ratio          # land slider scales islets
    radius = (0.14 + cv * 0.22) * size_boost
    islet = noise.smoothstep(1.0, 0.30, np.clip(f1 / radius, 0.0, 2.0))
    detail = noise.fbm(res, s, octaves=4, scale=7.0) * 0.006
    border = noise.square_falloff(res, margin=0.07)
    seabed = SEA_LEVEL - 0.05 + noise.fbm(res, s + 1, octaves=3, scale=3.0) * 0.006
    h = seabed + (islet * (0.052 + cv * 0.036) + islet * detail) * border
    return np.clip(h, 0.0, 1.0)


def flatlands(res: int, recipe: "Recipe") -> np.ndarray:
    """Prairie: long rolling swells 10-30m high, no cliffs."""
    base = noise.fbm(res, recipe.seed, octaves=5, scale=2.8)
    island = noise.radial_falloff(res, power=3.0, radius=1.05)
    island = np.clip(island + 0.08 * noise.fbm(res, recipe.seed + 2, octaves=3, scale=3.0), 0.0, 1.0)
    h = SEA_LEVEL - 0.02 + (base * 0.5 + 0.3) * 0.075 * island * max(recipe.mountain_scale, 0.2)
    return np.clip(h, 0.0, 1.0)


def floating(res: int, recipe: "Recipe") -> np.ndarray:
    """'Floating islands': sheer-walled pillar islands with flat green tops
    40–140m up, rising from deep water; sandbar spawn islets scattered
    between them (heightfield translation of the fantasy reference)."""
    s = recipe.seed
    ms = recipe.mountain_scale
    f1r, _f2, cv, _cv2 = noise.worley(res, s + 3, cells=5, jitter=0.85)
    f1 = f1r + 0.10 * noise.fbm(res, s + 5, octaves=4, scale=5.0)

    seabed = SEA_LEVEL - 0.062 + noise.fbm(res, s, octaves=4, scale=4.0) * 0.004
    top = SEA_LEVEL + 0.040 + cv * 0.095 * ms
    radius = 0.26 + cv * 0.12
    wall = noise.smoothstep(1.0, 0.52, np.clip(f1 / radius, 0.0, 2.0)) ** 0.8
    h = seabed + wall * (top - seabed)
    # flat-top relief
    h = h + wall**3 * noise.fbm(res, s + 8, octaves=4, scale=6.5) * 0.007

    # sea-level sandbar islets between the pillars (spawnable beaches)
    fb, _fb2, cvb, _cvb2 = noise.worley(res, s + 9, cells=10, jitter=0.9)
    bar = noise.smoothstep(1.0, 0.25, np.clip(fb / 0.26, 0.0, 2.0))
    bar = bar * (cvb > 0.5)
    h = np.maximum(h, SEA_LEVEL - 0.004 + bar * 0.0075)

    border = noise.square_falloff(res, margin=0.07)
    h = h * border + (1.0 - border) * (SEA_LEVEL - 0.06)
    return np.clip(h, 0.0, 1.0)


THEMES: dict[str, ThemeSpec] = {
    t.key: t
    for t in [
        ThemeSpec(
            key="classic", label="Classic Procedural",
            description="Vanilla-style landmass filling the map: lobed coastlines, lowlands with hill clusters, diagonal latitude biomes, rivers and forests.",
            build_height=classic, land_ratio_scale=1.45, beach_scale=0.75,
            biome_rotation=0.9,
        ),
        ThemeSpec(
            key="circular_isle", label="Circular Isle",
            description="An atoll: round island with a highland core, ringed by a bright shallow reef shelf dotted with sandbars.",
            build_height=circular_isle, forest_scale=3.4, land_ratio_scale=0.68,
            beach_scale=1.2, biome_rotation=0.6,
        ),
        ThemeSpec(
            key="volcano", label="Volcano",
            description="A steep central cone with a sunken caldera and radial gullies, secondary vents, and a broad forested lava apron.",
            build_height=volcano, rock_slope=24.0, snow_height=2.0,
            biome_edges=(0.5, 0.78, 0.92), forest_threshold=0.3,
            biome_rotation=0.5, rivers=False, beach_scale=0.7, shelf=0.5,
        ),
        ThemeSpec(
            key="archipelago", label="Archipelago",
            description="Chains of elongated islands aligned like drowned ridgelines, split by narrow straits — boat-heavy gameplay.",
            build_height=archipelago, rivers=False, land_ratio_scale=0.8,
            beach_scale=0.9, biome_rotation=0.9,
        ),
        ThemeSpec(
            key="naval", label="Naval",
            description="Mostly ocean scattered with small round islets and submerged shoals; maximum water combat.",
            build_height=naval, rivers=False, swamps=False, dry=True,
            biome_rotation=0.6,
        ),
        ThemeSpec(
            key="canyonlands", label="Canyonlands",
            description="A high desert plateau incised by branching gorges with terraced vertical walls.",
            build_height=canyonlands, biome_edges=(0.72, 0.9, 0.97),
            rock_slope=30.0, forest_threshold=0.3, erosion=False,
            land_ratio_scale=1.35, biome_rotation=0.5,
        ),
        ThemeSpec(
            key="moon", label="Moon",
            description="Grey cratered regolith: power-law craters with central peaks, smooth maria plains. No vegetation, no open water.",
            build_height=moon, fixed_biome=int(Biome.TUNDRA), jungle=False, swamps=False,
            rivers=False, barren=True, dry=True, palette="grey", erosion=False,
            beach_scale=0.3, shelf=0.0, land_ratio_scale=1.4,
        ),
        ThemeSpec(
            key="mars", label="Mars",
            description="Rust-red plains split by a colossal terraced rift canyon, with dune ripples and impact craters.",
            build_height=mars, fixed_biome=int(Biome.ARID), jungle=False, swamps=False,
            rivers=False, barren=True, dry=True, palette="red", erosion=True,
            beach_scale=0.3, shelf=0.0, land_ratio_scale=1.35,
        ),
        ThemeSpec(
            key="flatlands", label="Flatlands",
            description="Gentle buildable plains with guaranteed spawn beaches — creative/build servers.",
            build_height=flatlands, rivers=False, swamps=False, erosion=False,
            biome_rotation=0.6,
        ),
        ThemeSpec(
            key="floating", label="Floating Islands",
            description="Sheer-walled pillar islands with lush flat tops high above deep water, with sandbar spawn islets scattered between them.",
            build_height=floating, rivers=False, swamps=False, erosion=False,
            dry=True, shelf=0.0, beach_scale=0.6,
            biome_edges=(0.45, 0.85, 0.97), biome_rotation=0.6,
        ),
    ]
}
