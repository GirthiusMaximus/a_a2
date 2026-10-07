"""Rust .map (WorldSerialization) file reader/writer.

File layout:
    uint32  version   (little-endian; current = 10)
    uint64  timestamp (writers may emit 0; readers skip)
    bytes   lz4net-legacy-compressed protobuf WorldData

WorldData protobuf schema (protobuf-net field numbers):
    WorldData  { 1: uint32 size, 2: repeated MapData maps,
                 3: repeated PrefabData prefabs, 4: repeated PathData paths }
    MapData    { 1: string name, 2: bytes data }
    PrefabData { 1: string category, 2: uint32 id,
                 3: VectorData position, 4: VectorData rotation, 5: VectorData scale }
    PathData   { 1: string name, 2: bool spline, 3: bool start, 4: bool end,
                 5: float width, 6: float innerPadding, 7: float outerPadding,
                 8: float innerFade, 9: float outerFade, 10: float randomScale,
                 11: float meshOffset, 12: float terrainOffset,
                 13: int32 splat, 14: int32 topology, 15: repeated VectorData nodes }
    VectorData { 1: float x, 2: float y, 3: float z }
"""
from __future__ import annotations

import struct
import time
from dataclasses import dataclass, field

from . import lz4legacy
from .proto import ProtoReader, ProtoWriter, WIRE_LEN

CURRENT_VERSION = 10


@dataclass
class VectorData:
    x: float = 0.0
    y: float = 0.0
    z: float = 0.0


@dataclass
class MapData:
    name: str
    data: bytes


@dataclass
class PrefabData:
    category: str = ":\\test\\0"
    id: int = 0
    position: VectorData = field(default_factory=VectorData)
    rotation: VectorData = field(default_factory=VectorData)
    scale: VectorData = field(default_factory=lambda: VectorData(1.0, 1.0, 1.0))


@dataclass
class PathData:
    name: str = "Road"
    spline: bool = False
    start: bool = False
    end: bool = False
    width: float = 10.0
    inner_padding: float = 1.0
    outer_padding: float = 1.0
    inner_fade: float = 8.0
    outer_fade: float = 8.0
    random_scale: float = 1.0
    mesh_offset: float = 0.0
    terrain_offset: float = 0.0
    splat: int = 128      # TerrainSplat.GRAVEL
    topology: int = 2048  # TerrainTopology.ROAD
    nodes: list[VectorData] = field(default_factory=list)


@dataclass
class WorldData:
    size: int = 4000
    maps: list[MapData] = field(default_factory=list)
    prefabs: list[PrefabData] = field(default_factory=list)
    paths: list[PathData] = field(default_factory=list)

    # -- layer helpers ---------------------------------------------
    def get_map(self, name: str) -> MapData | None:
        for m in self.maps:
            if m.name == name:
                return m
        return None

    def set_map(self, name: str, data: bytes) -> None:
        existing = self.get_map(name)
        if existing is not None:
            existing.data = data
        else:
            self.maps.append(MapData(name, data))


# ---------------------------------------------------------------------------
# protobuf encode
# ---------------------------------------------------------------------------

def _write_vector(v: VectorData) -> ProtoWriter:
    w = ProtoWriter()
    w.float_(1, v.x)
    w.float_(2, v.y)
    w.float_(3, v.z)
    return w


def encode_world(world: WorldData) -> bytes:
    w = ProtoWriter()
    w.uint32(1, world.size)
    for m in world.maps:
        mw = ProtoWriter()
        mw.string(1, m.name)
        mw.bytes_(2, m.data)
        w.message(2, mw)
    for p in world.prefabs:
        pw = ProtoWriter()
        pw.string(1, p.category)
        pw.uint32(2, p.id)
        pw.message(3, _write_vector(p.position))
        pw.message(4, _write_vector(p.rotation))
        pw.message(5, _write_vector(p.scale))
        w.message(3, pw)
    for p in world.paths:
        pw = ProtoWriter()
        pw.string(1, p.name)
        pw.bool_(2, p.spline)
        pw.bool_(3, p.start)
        pw.bool_(4, p.end)
        pw.float_(5, p.width)
        pw.float_(6, p.inner_padding)
        pw.float_(7, p.outer_padding)
        pw.float_(8, p.inner_fade)
        pw.float_(9, p.outer_fade)
        pw.float_(10, p.random_scale)
        pw.float_(11, p.mesh_offset)
        pw.float_(12, p.terrain_offset)
        pw.int32(13, p.splat)
        pw.int32(14, p.topology)
        for n in p.nodes:
            pw.message(15, _write_vector(n))
        w.message(4, pw)
    return w.getvalue()


# ---------------------------------------------------------------------------
# protobuf decode
# ---------------------------------------------------------------------------

def _read_vector(data: bytes) -> VectorData:
    r = ProtoReader(data)
    v = VectorData()
    while not r.eof():
        f, wire = r.tag()
        if f == 1:
            v.x = r.float_()
        elif f == 2:
            v.y = r.float_()
        elif f == 3:
            v.z = r.float_()
        else:
            r.skip(wire)
    return v


def decode_world(data: bytes) -> WorldData:
    r = ProtoReader(data)
    world = WorldData(size=0, maps=[], prefabs=[], paths=[])
    while not r.eof():
        f, wire = r.tag()
        if f == 1:
            world.size = r.varint()
        elif f == 2 and wire == WIRE_LEN:
            mr = ProtoReader(r.bytes_())
            name, blob = "", b""
            while not mr.eof():
                mf, mw = mr.tag()
                if mf == 1:
                    name = mr.string()
                elif mf == 2:
                    blob = mr.bytes_()
                else:
                    mr.skip(mw)
            world.maps.append(MapData(name, blob))
        elif f == 3 and wire == WIRE_LEN:
            pr = ProtoReader(r.bytes_())
            p = PrefabData()
            while not pr.eof():
                pf, pw = pr.tag()
                if pf == 1:
                    p.category = pr.string()
                elif pf == 2:
                    p.id = pr.varint()
                elif pf == 3:
                    p.position = _read_vector(pr.bytes_())
                elif pf == 4:
                    p.rotation = _read_vector(pr.bytes_())
                elif pf == 5:
                    p.scale = _read_vector(pr.bytes_())
                else:
                    pr.skip(pw)
            world.prefabs.append(p)
        elif f == 4 and wire == WIRE_LEN:
            pr = ProtoReader(r.bytes_())
            p = PathData(nodes=[])
            while not pr.eof():
                pf, pw = pr.tag()
                if pf == 1:
                    p.name = pr.string()
                elif pf == 2:
                    p.spline = bool(pr.varint())
                elif pf == 3:
                    p.start = bool(pr.varint())
                elif pf == 4:
                    p.end = bool(pr.varint())
                elif pf == 5:
                    p.width = pr.float_()
                elif pf == 6:
                    p.inner_padding = pr.float_()
                elif pf == 7:
                    p.outer_padding = pr.float_()
                elif pf == 8:
                    p.inner_fade = pr.float_()
                elif pf == 9:
                    p.outer_fade = pr.float_()
                elif pf == 10:
                    p.random_scale = pr.float_()
                elif pf == 11:
                    p.mesh_offset = pr.float_()
                elif pf == 12:
                    p.terrain_offset = pr.float_()
                elif pf == 13:
                    p.splat = pr.varint()
                elif pf == 14:
                    p.topology = pr.varint()
                elif pf == 15:
                    p.nodes.append(_read_vector(pr.bytes_()))
                else:
                    pr.skip(pw)
            world.paths.append(p)
        else:
            r.skip(wire)
    return world


# ---------------------------------------------------------------------------
# .map container
# ---------------------------------------------------------------------------

def load_map_bytes(raw: bytes) -> tuple[WorldData, int]:
    """Parse a .map file. Returns (world, version)."""
    if len(raw) < 12:
        raise ValueError("file too small to be a .map")
    version = struct.unpack_from("<I", raw, 0)[0]
    if not (7 <= version <= 50):
        raise ValueError(f"unexpected world serialization version {version}")
    payload = lz4legacy.decompress(raw[12:])
    return decode_world(payload), version


def load_map(path: str) -> tuple[WorldData, int]:
    with open(path, "rb") as fh:
        return load_map_bytes(fh.read())


def save_map_bytes(world: WorldData, version: int = CURRENT_VERSION, timestamp: int | None = None) -> bytes:
    payload = encode_world(world)
    compressed = lz4legacy.compress(payload)
    if timestamp is None:
        # .NET DateTime.UtcNow.ToBinary()-style value is not required;
        # readers skip these 8 bytes. Use unix epoch ticks for traceability.
        timestamp = int(time.time())
    return struct.pack("<IQ", version, timestamp) + compressed


def save_map(world: WorldData, path: str, version: int = CURRENT_VERSION) -> None:
    with open(path, "wb") as fh:
        fh.write(save_map_bytes(world, version))
