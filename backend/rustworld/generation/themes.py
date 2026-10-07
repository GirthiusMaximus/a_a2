"""Theme definitions: parameter presets + height-field builders."""
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
    snow: bool = False            # allow snow even when barren
    rock_slope: float = 38.0      # degrees where rock splat takes over
    snow_height: float = 0.82     # normalized height snowline
    forest_scale: float = 4.0
    forest_threshold: float = 0.22
    beach_scale: float = 1.0
    shelf: float = 0.85           # strength of shoreline flattening
    land_ratio_scale: float = 1.0


def _amp(recipe: "Recipe") -> float:
    return 0.11 * recipe.mountain_scale


# --- height builders -------------------------------------------------------

def classic(res: int, recipe: "Recipe") -> np.ndarray:
    base = noise.warped_fbm(res, recipe.seed, octaves=6, scale=3.2, warp=0.4)
    ridges = noise.ridged(res, recipe.seed + 1, octaves=5, scale=2.6)
    island = noise.radial_falloff(res, power=2.6, radius=1.05)
    island = np.clip(island + 0.22 * noise.fbm(res, recipe.seed + 2, octaves=4, scale=3.0), 0, 1)
    h = SEA_LEVEL - 0.028 + (base * 0.55 + ridges * 0.6 - 0.18) * _amp(recipe) * island * 2.1
    h = h * island + (1 - island) * (SEA_LEVEL - 0.03)
    return np.clip(h, 0.0, 1.0)


def circular_isle(res: int, recipe: "Recipe") -> np.ndarray:
    base = noise.fbm(res, recipe.seed, octaves=5, scale=3.0)
    island = noise.radial_falloff(res, power=1.9, radius=0.86)
    h = SEA_LEVEL - 0.03 + island * _amp(recipe) * 1.7 + base * _amp(recipe) * 0.5 * island
    return np.clip(h, 0.0, 1.0)


def volcano(res: int, recipe: "Recipe") -> np.ndarray:
    c = np.linspace(-1.0, 1.0, res, dtype=np.float32)
    x, y = np.meshgrid(c, c)
    d = np.sqrt(x * x + y * y)
    cone = np.clip(1.0 - d * 1.45, 0.0, 1.0) ** 1.6
    crater = noise.smoothstep(0.1, 0.028, d) * 0.5      # caldera depression
    rough = noise.ridged(res, recipe.seed, octaves=6, scale=4.0) * 0.25
    island = noise.radial_falloff(res, power=2.4, radius=1.0)
    island = np.clip(island + 0.15 * noise.fbm(res, recipe.seed + 2, octaves=4, scale=3.5), 0, 1)
    h = SEA_LEVEL - 0.03 + (cone * 2.6 - crater * 2.0 + rough) * _amp(recipe) * island * 1.6
    return np.clip(h, 0.0, 1.0)


def archipelago(res: int, recipe: "Recipe") -> np.ndarray:
    base = noise.warped_fbm(res, recipe.seed, octaves=6, scale=5.2, warp=0.5)
    border = noise.square_falloff(res, margin=0.08)
    h = SEA_LEVEL - 0.045 + (base + 0.12) * _amp(recipe) * 1.25 * border
    return np.clip(h, 0.0, 1.0)


def canyonlands(res: int, recipe: "Recipe") -> np.ndarray:
    base = noise.warped_fbm(res, recipe.seed, octaves=6, scale=3.4, warp=0.55)
    terraced = np.round(base * 5.0) / 5.0 * 0.65 + base * 0.35   # mesa steps
    island = noise.radial_falloff(res, power=2.8, radius=1.08)
    h = SEA_LEVEL - 0.025 + (terraced + 0.25) * _amp(recipe) * 1.9 * island
    return np.clip(h, 0.0, 1.0)


def _craters(res: int, recipe: "Recipe", count: int, max_r: float) -> np.ndarray:
    rng = recipe.rng(11)
    c = np.linspace(0.0, 1.0, res, dtype=np.float32)
    x, y = np.meshgrid(c, c)
    out = np.zeros((res, res), dtype=np.float32)
    for _ in range(count):
        cx, cy = rng.random(), rng.random()
        r = 0.015 + rng.random() ** 2 * max_r
        d = np.sqrt((x - cx) ** 2 + (y - cy) ** 2) / r
        bowl = -np.clip(1.0 - d * d, 0.0, 1.0) * 0.9
        rim = np.exp(-((d - 1.0) ** 2) * 14.0) * 0.45
        out += (bowl + rim) * r * 9.0
    return out


def moon(res: int, recipe: "Recipe") -> np.ndarray:
    rolling = noise.fbm(res, recipe.seed, octaves=5, scale=3.2) * 0.5
    craters = _craters(res, recipe, count=46, max_r=0.075)
    island = noise.radial_falloff(res, power=2.2, radius=1.12)
    h = SEA_LEVEL + 0.012 + (rolling * 0.6 + craters) * _amp(recipe) * island + island * 0.02
    return np.clip(h, 0.0, 1.0)


def mars(res: int, recipe: "Recipe") -> np.ndarray:
    dunes = noise.warped_fbm(res, recipe.seed, octaves=6, scale=4.2, warp=0.6) * 0.6
    craters = _craters(res, recipe, count=22, max_r=0.06)
    ridges = noise.ridged(res, recipe.seed + 3, octaves=5, scale=2.4) * 0.5
    island = noise.radial_falloff(res, power=2.3, radius=1.1)
    h = SEA_LEVEL + 0.01 + (dunes + craters + ridges - 0.2) * _amp(recipe) * island + island * 0.018
    return np.clip(h, 0.0, 1.0)


def naval(res: int, recipe: "Recipe") -> np.ndarray:
    base = noise.warped_fbm(res, recipe.seed, octaves=6, scale=6.0, warp=0.45)
    border = noise.square_falloff(res, margin=0.07)
    h = SEA_LEVEL - 0.055 + (base + 0.05) * _amp(recipe) * border
    return np.clip(h, 0.0, 1.0)


def flatlands(res: int, recipe: "Recipe") -> np.ndarray:
    base = noise.fbm(res, recipe.seed, octaves=4, scale=2.4) * 0.25
    island = noise.radial_falloff(res, power=3.0, radius=1.05)
    h = SEA_LEVEL - 0.02 + (base + 0.3) * 0.028 * island * max(recipe.mountain_scale, 0.2)
    return np.clip(h, 0.0, 1.0)


THEMES: dict[str, ThemeSpec] = {
    t.key: t
    for t in [
        ThemeSpec(
            key="classic", label="Classic Procedural",
            description="Vanilla-style island: warped coastlines, ridged highlands, latitude biomes, rivers and forests.",
            build_height=classic,
        ),
        ThemeSpec(
            key="circular_isle", label="Circular Isle",
            description="A clean round island with a ring beach and a highland core.",
            build_height=circular_isle, forest_scale=3.4,
        ),
        ThemeSpec(
            key="volcano", label="Volcano",
            description="A towering central volcano with a sunken caldera, rocky ash slopes and black-sand feel.",
            build_height=volcano, rock_slope=30.0, snow_height=2.0,
            biome_edges=(0.5, 0.78, 0.92), forest_threshold=0.3,
        ),
        ThemeSpec(
            key="archipelago", label="Archipelago",
            description="A scattering of islands separated by shallow seas — boat-heavy gameplay.",
            build_height=archipelago, rivers=False, land_ratio_scale=0.8,
        ),
        ThemeSpec(
            key="naval", label="Naval",
            description="Mostly ocean with small island chains; maximum water combat.",
            build_height=naval, rivers=False, swamps=False, land_ratio_scale=0.5,
        ),
        ThemeSpec(
            key="canyonlands", label="Canyonlands",
            description="Terraced mesas and deep carved canyons, arid-leaning.",
            build_height=canyonlands, biome_edges=(0.55, 0.8, 0.93),
            rock_slope=30.0, forest_threshold=0.3,
        ),
        ThemeSpec(
            key="moon", label="Moon",
            description="Grey cratered regolith. No vegetation, no open water — airlock optional.",
            build_height=moon, fixed_biome=int(Biome.TUNDRA), jungle=False, swamps=False,
            rivers=False, barren=True, erosion=False, beach_scale=0.3, shelf=0.0,
            land_ratio_scale=1.4,
        ),
        ThemeSpec(
            key="mars", label="Mars",
            description="Rust-red dunes, impact craters and dry ridgelines.",
            build_height=mars, fixed_biome=int(Biome.ARID), jungle=False, swamps=False,
            rivers=False, barren=True, erosion=True, beach_scale=0.3, shelf=0.0,
            land_ratio_scale=1.35,
        ),
        ThemeSpec(
            key="flatlands", label="Flatlands",
            description="Gentle buildable plains with guaranteed spawn beaches — creative/build servers.",
            build_height=flatlands, rivers=False, swamps=False, erosion=False,
        ),
    ]
}
