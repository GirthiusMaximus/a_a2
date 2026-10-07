"""Terrain layer packing/unpacking and enums for Rust worlds.

All multi-channel maps are channel-major: index = (c * res + z) * res + x.
"""
from __future__ import annotations

from enum import IntEnum

import numpy as np

from .worldfile import WorldData

TERRAIN_HEIGHT = 1000.0  # vertical terrain span in meters
SEA_LEVEL = 0.5          # normalized height of sea level (world Y = 0)
SHORT_SCALE = 32766.0    # Float2Short scale used by the Rust SDK


class Splat(IntEnum):
    DIRT = 0
    SNOW = 1
    SAND = 2
    ROCK = 3
    GRASS = 4
    FOREST = 5
    STONES = 6
    GRAVEL = 7


SPLAT_COUNT = 8


class Biome(IntEnum):
    ARID = 0
    TEMPERATE = 1
    TUNDRA = 2
    ARCTIC = 3
    JUNGLE = 4


BIOME_COUNT = 5


class Topology(IntEnum):
    FIELD = 1 << 0
    CLIFF = 1 << 1
    SUMMIT = 1 << 2
    BEACHSIDE = 1 << 3
    BEACH = 1 << 4
    FOREST = 1 << 5
    FORESTSIDE = 1 << 6
    OCEAN = 1 << 7
    OCEANSIDE = 1 << 8
    DECOR = 1 << 9
    MONUMENT = 1 << 10
    ROAD = 1 << 11
    ROADSIDE = 1 << 12
    SWAMP = 1 << 13
    RIVER = 1 << 14
    RIVERSIDE = 1 << 15
    LAKE = 1 << 16
    LAKESIDE = 1 << 17
    OFFSHORE = 1 << 18
    RAIL = 1 << 19
    RAILSIDE = 1 << 20
    BUILDING = 1 << 21
    CLIFFSIDE = 1 << 22
    MOUNTAIN = 1 << 23
    CLUTTER = 1 << 24
    ALT = 1 << 25
    TIER0 = 1 << 26
    TIER1 = 1 << 27
    TIER2 = 1 << 28
    MAINLAND = 1 << 29
    HILLTOP = 1 << 30


def next_power_of_two(v: int) -> int:
    p = 1
    while p < v:
        p <<= 1
    return p


def heightmap_resolution(size: int) -> int:
    return next_power_of_two(max(1, size // 2)) + 1


def splatmap_resolution(size: int) -> int:
    return int(np.clip(next_power_of_two(max(1, size // 2)), 16, 2048))


# ---------------------------------------------------------------------------
# packing  (numpy <-> MapData blobs)
# ---------------------------------------------------------------------------

def pack_heights(height01: np.ndarray) -> bytes:
    """Pack a normalized [0,1] float heightmap (res x res) into int16 bytes."""
    h = np.clip(height01, 0.0, 1.0)
    shorts = (h * SHORT_SCALE + 0.5).astype(np.int16)
    return shorts.tobytes()


def unpack_heights(blob: bytes) -> np.ndarray:
    arr = np.frombuffer(blob, dtype="<i2").astype(np.float32) / SHORT_SCALE
    res = int(round(len(arr) ** 0.5))
    return arr.reshape(res, res)


def pack_channels(weights: np.ndarray) -> bytes:
    """Pack float weights [0,1] of shape (channels, res, res) into bytes."""
    w = np.clip(weights, 0.0, 1.0)
    return (w * 255.0 + 0.5).astype(np.uint8).tobytes()


def unpack_channels(blob: bytes, channels: int) -> np.ndarray:
    arr = np.frombuffer(blob, dtype=np.uint8)
    res = int(round((len(arr) / channels) ** 0.5))
    return arr.reshape(channels, res, res).astype(np.float32) / 255.0


def pack_topology(mask: np.ndarray) -> bytes:
    """Pack an int32 bitmask array (res x res) into bytes."""
    return mask.astype("<i4").tobytes()


def unpack_topology(blob: bytes) -> np.ndarray:
    arr = np.frombuffer(blob, dtype="<i4")
    res = int(round(len(arr) ** 0.5))
    return arr.reshape(res, res).copy()


def pack_alpha(visible: np.ndarray) -> bytes:
    """Pack a boolean visibility array (res x res); True = terrain visible."""
    return np.where(visible, 255, 0).astype(np.uint8).tobytes()


# ---------------------------------------------------------------------------
# world assembly
# ---------------------------------------------------------------------------

def build_world(
    size: int,
    height01: np.ndarray,
    water01: np.ndarray,
    splat: np.ndarray,      # (8, res, res) float weights
    biome: np.ndarray,      # (4 or 5, res, res) float weights
    topology: np.ndarray,   # (res, res) int32 bitmask
    alpha: np.ndarray | None = None,  # (res, res) bool, default all visible
    prefabs: list | None = None,      # worldfile.PrefabData (monuments)
    paths: list | None = None,        # worldfile.PathData (roads/rivers)
) -> WorldData:
    world = WorldData(
        size=int(size),
        maps=[],
        prefabs=list(prefabs or []),
        paths=list(paths or []),
    )
    height_blob = pack_heights(height01)
    world.set_map("terrain", height_blob)
    world.set_map("height", height_blob)
    world.set_map("water", pack_heights(water01))
    world.set_map("splat", pack_channels(splat))
    world.set_map("biome", pack_channels(biome))
    if alpha is None:
        alpha = np.ones(topology.shape, dtype=bool)
    world.set_map("alpha", pack_alpha(alpha))
    world.set_map("topology", pack_topology(topology))
    return world
