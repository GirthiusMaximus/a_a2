"""Bit-exact reimplementations of Facepunch's own world-generation primitives.

Everything in this module is a direct port of readable C# from the game
assembly (see ``docs/PROCGEN_RESEARCH.md`` for provenance and the recency
vetting that selected the source).  Where a value is quoted from the game it
is reproduced verbatim in the docstring so it can be re-verified later.

The one thing that is *not* portable is the height field itself:
``GenerateHeight`` is a ``[DllImport("RustNative")]`` stub, so the raw terrain
algorithm only exists as compiled native code.  Everything that surrounds it
-- the PRNG, the seed-derived axes, the loot tiers, the world config -- is
plain C# and is matched exactly here.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

__all__ = [
    "SeedRandom",
    "WorldConfig",
    "loot_axis_angle",
    "biome_axis_angle",
    "axis_projection",
    "tier_index",
    "CLIFF_SLOPE",
    "ROCK_SLOPE_MIN",
    "ROCK_SLOPE_MAX",
    "ROAD_WIDTH",
    "TRAIL_WIDTH",
    "ROAD_INNER_PADDING",
    "ROAD_OUTER_PADDING",
    "ROAD_INNER_FADE",
    "ROAD_OUTER_FADE",
    "ROAD_RANDOM_SCALE",
    "ROAD_TERRAIN_OFFSET",
    "RIVER_WIDTH",
    "RIVER_INNER_FADE",
    "RIVER_OUTER_FADE",
    "RIVER_TERRAIN_OFFSET",
    "RIVER_MIN_SOURCE_HEIGHT",
    "RIVER_MIN_SEPARATION",
    "river_count",
    "MIN_DISTANCE_SAME_TYPE",
    "GROUP_CANDIDATES",
    "INDIVIDUAL_CANDIDATES",
]

_U32 = 0xFFFFFFFF

# ``2.3283064E-10f`` exactly as the game spells it -- a float32 literal, not 1/2**32.
_XORSHIFT_SCALE = np.float32(2.3283064e-10)


class SeedRandom:
    """Port of ``Rust.Global :: SeedRandom``.

    .. code-block:: csharp

        public static uint Xorshift(ref uint x)
        { x ^= x << 13; x ^= x >> 17; x ^= x << 5; return x; }

        public static float Xorshift01(ref uint x)
            => (float)Xorshift(ref x) * 2.3283064E-10f;

        public static int   Range(ref uint s, int min, int max)
            => min + (int)(Xorshift(ref s) % (uint)(max - min));
        public static float Range(ref uint s, float min, float max)
            => min + Xorshift01(ref s) * (max - min);
        public static int   Sign (ref uint s) => (Xorshift(ref s) % 2 != 0) ? -1 : 1;
        public static float Value(ref uint s) => Xorshift01(ref s);

    The state is advanced in place, exactly like the C# ``ref uint seed``
    parameter, so a sequence of calls reproduces the game's sequence.
    """

    __slots__ = ("seed",)

    def __init__(self, seed: int = 0) -> None:
        self.seed = int(seed) & _U32

    # -- core ---------------------------------------------------------------
    def xorshift(self) -> int:
        x = self.seed
        x ^= (x << 13) & _U32
        x ^= x >> 17
        x ^= (x << 5) & _U32
        self.seed = x & _U32
        return self.seed

    def value(self) -> float:
        """``Xorshift01`` -- float32 multiply, matching the game's precision."""
        return float(np.float32(self.xorshift()) * _XORSHIFT_SCALE)

    def range_int(self, lo: int, hi: int) -> int:
        """``Range(ref, int, int)`` -- ``hi`` exclusive."""
        span = (hi - lo) & _U32
        if span == 0:
            return lo
        return lo + int(self.xorshift() % span)

    def range_float(self, lo: float, hi: float) -> float:
        return lo + self.value() * (hi - lo)

    def sign(self) -> int:
        return -1 if (self.xorshift() % 2) else 1

    def value2d(self) -> tuple[float, float]:
        a = self.value() * math.pi * 2.0
        return (math.cos(a), math.sin(a))

    # -- hashing ------------------------------------------------------------
    def wanghash(self) -> int:
        x = self.seed
        x = (x ^ 0x3D ^ (x >> 16)) & _U32
        x = (x * 9) & _U32
        x ^= x >> 4
        x = (x * 668265261) & _U32
        x ^= x >> 15
        self.seed = x & _U32
        return self.seed

    def wanghash01(self) -> float:
        return float(np.float32(self.wanghash()) * _XORSHIFT_SCALE)

    def shuffle(self, items: list) -> list:
        """``Array.Shuffle(ref seed)`` -- Fisher-Yates driven by this stream."""
        out = list(items)
        for i in range(len(out) - 1, 0, -1):
            j = self.range_int(0, i + 1)
            out[i], out[j] = out[j], out[i]
        return out


# ---------------------------------------------------------------------------
# Seed-derived map axes
# ---------------------------------------------------------------------------
#
#   TerrainMeta.Init:
#       uint seed = World.Seed;
#       int num  = SeedRandom.Range(ref seed, 0, 4) * 90;
#       int num2 = SeedRandom.Range(ref seed, -45, 46);
#       int num3 = SeedRandom.Sign(ref seed);
#       LootAxisAngle  = num;
#       BiomeAxisAngle = num + num2 + num3 * 90;


def _axes(seed: int) -> tuple[float, float]:
    r = SeedRandom(seed)
    loot = r.range_int(0, 4) * 90
    jitter = r.range_int(-45, 46)
    sign = r.sign()
    return float(loot), float(loot + jitter + sign * 90)


def loot_axis_angle(seed: int) -> float:
    """Degrees.  Always one of 0 / 90 / 180 / 270."""
    return _axes(seed)[0]


def biome_axis_angle(seed: int) -> float:
    """Degrees.  Roughly perpendicular to the loot axis (+-45 degrees)."""
    return _axes(seed)[1]


def axis_projection(res: int, angle_deg: float) -> np.ndarray:
    """Normalised 0..1 projection of every cell onto ``angle_deg``.

    Unity convention: 0 degrees points along +Z, 90 degrees along +X.  Arrays are
    ``[z, x]`` with row 0 = south, matching the rest of the codebase.
    """
    t = math.radians(angle_deg)
    dx, dz = math.sin(t), math.cos(t)
    c = np.linspace(-0.5, 0.5, res, dtype=np.float32)
    zz, xx = np.meshgrid(c, c, indexing="ij")
    proj = xx * np.float32(dx) + zz * np.float32(dz)
    # extent of the projection over a unit square for this direction
    half = (abs(dx) + abs(dz)) * 0.5
    return ((proj + half) / (2.0 * half)).astype(np.float32)


def tier_index(res: int, seed: int, pct: tuple[float, float, float]) -> np.ndarray:
    """Per-cell loot tier (0, 1 or 2) as bands across the loot axis.

    ``pct`` are the normalised Tier0/Tier1/Tier2 fractions from
    :class:`WorldConfig` (vanilla default 0.30 / 0.30 / 0.40).
    """
    proj = axis_projection(res, loot_axis_angle(seed))
    t0, t1, _ = pct
    out = np.full((res, res), 2, dtype=np.uint8)
    out[proj < (t0 + t1)] = 1
    out[proj < t0] = 0
    return out


# ---------------------------------------------------------------------------
# WorldConfig
# ---------------------------------------------------------------------------


@dataclass
class WorldConfig:
    """Port of ``WorldConfig`` with the game's real defaults.

    Tier and biome percentages are normalised on load exactly as
    ``LoadFromWorldConfig`` does, including its zero-sum fallbacks.
    """

    percentage_tier0: float = 0.3
    percentage_tier1: float = 0.3
    percentage_tier2: float = 0.4

    percentage_biome_arid: float = 0.4
    percentage_biome_temperate: float = 0.15
    percentage_biome_tundra: float = 0.15
    percentage_biome_arctic: float = 0.3
    percentage_biome_jungle: float = 0.5  # deliberately outside the normalised group

    main_roads: bool = True
    side_roads: bool = True
    trails: bool = True
    rivers: bool = True
    powerlines: bool = True
    above_ground_rails: bool = True
    below_ground_rails: bool = True
    underwater_labs: bool = True

    prefab_blacklist: list[str] = field(default_factory=list)
    prefab_whitelist: list[str] = field(default_factory=list)

    def normalise(self) -> "WorldConfig":
        total = self.percentage_tier0 + self.percentage_tier1 + self.percentage_tier2
        if total > 0:
            self.percentage_tier0 /= total
            self.percentage_tier1 /= total
            self.percentage_tier2 /= total
        else:
            self.percentage_tier0, self.percentage_tier1, self.percentage_tier2 = 0.0, 1.0, 0.0

        total2 = (
            self.percentage_biome_arid
            + self.percentage_biome_temperate
            + self.percentage_biome_tundra
            + self.percentage_biome_arctic
        )
        if total2 > 0:
            self.percentage_biome_arid /= total2
            self.percentage_biome_temperate /= total2
            self.percentage_biome_tundra /= total2
            self.percentage_biome_arctic /= total2
        else:
            self.percentage_biome_arid = 0.0
            self.percentage_biome_temperate = 1.0
            self.percentage_biome_tundra = 0.0
            self.percentage_biome_arctic = 0.0
        return self

    @property
    def tier_percentages(self) -> tuple[float, float, float]:
        return (self.percentage_tier0, self.percentage_tier1, self.percentage_tier2)

    @property
    def biome_percentages(self) -> tuple[float, float, float, float]:
        return (
            self.percentage_biome_arid,
            self.percentage_biome_temperate,
            self.percentage_biome_tundra,
            self.percentage_biome_arctic,
        )

    def is_prefab_allowed(self, name: str) -> bool:
        """``WorldConfig.IsPrefabAllowed`` -- substring matching, whitelist wins."""
        for item in self.prefab_blacklist:
            if item in name:
                return False
        if self.prefab_whitelist:
            for item in self.prefab_whitelist:
                if item in name:
                    return True
            return False
        return True


# ---------------------------------------------------------------------------
# Terrain / path constants lifted verbatim from the generation components
# ---------------------------------------------------------------------------

# GenerateCliffTopology: `if (slope > 30f || splat > 0.4f)` -> Topology.Cliff
CLIFF_SLOPE = 30.0
CLIFF_SPLAT = 0.4

# GenerateCliffSplat: `SetSplat(x, z, 8, Mathf.InverseLerp(30f, 50f, slope))`
# (splat index 8 is the ROCK bit, 1 << 3)
ROCK_SLOPE_MIN = 30.0
ROCK_SLOPE_MAX = 50.0

# GenerateRoadLayout
ROAD_WIDTH = 10.0
TRAIL_WIDTH = 4.0
ROAD_INNER_PADDING = 1.0
ROAD_OUTER_PADDING = 1.0
ROAD_INNER_FADE = 1.0
ROAD_OUTER_FADE = 8.0
ROAD_RANDOM_SCALE = 0.75
ROAD_TERRAIN_OFFSET = -0.125
TRAIL_INNER_PADDING = 1.0 * 0.4

# GenerateRiverLayout
RIVER_WIDTH = 8.0
RIVER_INNER_PADDING = 1.0
RIVER_OUTER_PADDING = 1.0
RIVER_INNER_FADE = 16.0
RIVER_OUTER_FADE = 64.0
RIVER_RANDOM_SCALE = 0.75
RIVER_MESH_OFFSET = -0.5
RIVER_TERRAIN_OFFSET = -1.5
RIVER_MIN_SOURCE_HEIGHT = 15.0          # `if (val2.y <= 15f) continue;`
RIVER_MIN_SEPARATION = math.sqrt(67600.0)  # 260 m -- `SqrMagnitude2D < 67600f`


def river_count(world_size: int) -> int:
    """``int num = 3; if (World.Size <= 4000) num = 2;``"""
    return 2 if world_size <= 4000 else 3


# PlaceMonuments / PlaceMonumentsRoadside
MIN_DISTANCE_SAME_TYPE = 500.0   # metres, the serialized default
GROUP_CANDIDATES = 8
INDIVIDUAL_CANDIDATES = 8
PLACEMENT_ATTEMPTS = 10000
