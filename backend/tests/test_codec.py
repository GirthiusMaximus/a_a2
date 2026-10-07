"""Codec tests: LZ4-legacy stream, protobuf, and full .map round-trips."""
import numpy as np
import pytest

from rustworld import lz4legacy
from rustworld.layers import (
    build_world,
    heightmap_resolution,
    pack_heights,
    splatmap_resolution,
    unpack_channels,
    unpack_heights,
    unpack_topology,
    Topology,
)
from rustworld.worldfile import (
    PathData,
    PrefabData,
    VectorData,
    WorldData,
    decode_world,
    encode_world,
    load_map_bytes,
    save_map_bytes,
)


def test_lz4_roundtrip_small():
    data = b"hello rust world" * 100
    assert lz4legacy.decompress(lz4legacy.compress(data)) == data


def test_lz4_roundtrip_multi_chunk():
    rng = np.random.default_rng(42)
    # > 1 MiB and compressible mix, forcing multiple chunks + both chunk kinds
    data = rng.integers(0, 255, 3 * 1024 * 1024, dtype=np.uint8).tobytes() + b"\x00" * 500_000
    assert lz4legacy.decompress(lz4legacy.compress(data)) == data


def test_lz4_incompressible_chunk():
    rng = np.random.default_rng(1)
    data = rng.bytes(4096)  # random -> stored uncompressed
    assert lz4legacy.decompress(lz4legacy.compress(data)) == data


def test_varint_boundaries():
    for n in (0, 1, 127, 128, 300, 1 << 20, (1 << 32) - 1):
        out = bytearray()
        lz4legacy._write_varint(out, n)
        assert lz4legacy._Reader(bytes(out)).read_varint() == n


def test_world_proto_roundtrip():
    world = WorldData(size=3500)
    world.set_map("terrain", b"\x01\x02\x03")
    world.prefabs.append(
        PrefabData(category="Decor", id=123456789,
                   position=VectorData(1.5, -2.25, 3.75),
                   rotation=VectorData(0, 90, 0),
                   scale=VectorData(1, 1, 1))
    )
    world.paths.append(
        PathData(name="River", spline=True, width=42.0,
                 nodes=[VectorData(0, 0, 0), VectorData(10, 1, -5)])
    )
    decoded = decode_world(encode_world(world))
    assert decoded.size == 3500
    assert decoded.get_map("terrain").data == b"\x01\x02\x03"
    p = decoded.prefabs[0]
    assert p.id == 123456789 and p.category == "Decor"
    assert p.position.x == pytest.approx(1.5) and p.position.y == pytest.approx(-2.25)
    path = decoded.paths[0]
    assert path.name == "River" and path.spline and len(path.nodes) == 2
    assert path.nodes[1].z == pytest.approx(-5.0)


def test_map_container_roundtrip():
    world = WorldData(size=2000)
    world.set_map("terrain", pack_heights(np.full((65, 65), 0.503, dtype=np.float32)))
    raw = save_map_bytes(world)
    loaded, version = load_map_bytes(raw)
    assert version == 10
    assert loaded.size == 2000
    heights = unpack_heights(loaded.get_map("terrain").data)
    assert heights.shape == (65, 65)
    assert np.allclose(heights, 0.503, atol=1e-4)


def test_resolutions_match_rustedit_expectations():
    assert heightmap_resolution(1000) == 513
    assert heightmap_resolution(2000) == 1025
    assert heightmap_resolution(4000) == 2049
    assert heightmap_resolution(4500) == 4097
    assert splatmap_resolution(1000) == 512
    assert splatmap_resolution(4500) == 2048  # clamped


def test_build_world_layer_shapes_and_values():
    size = 1000
    h_res, s_res = heightmap_resolution(size), splatmap_resolution(size)
    height = np.full((h_res, h_res), 0.52, dtype=np.float32)
    water = np.full((h_res, h_res), 0.5, dtype=np.float32)
    splat = np.zeros((8, s_res, s_res), dtype=np.float32)
    splat[4] = 1.0  # grass
    biome = np.zeros((5, s_res, s_res), dtype=np.float32)
    biome[1] = 1.0  # temperate
    topo = np.full((s_res, s_res), int(Topology.FIELD | Topology.MAINLAND), dtype=np.int32)

    world = build_world(size, height, water, splat, biome, topo)
    raw = save_map_bytes(world)
    loaded, _ = load_map_bytes(raw)

    assert unpack_heights(loaded.get_map("terrain").data).shape == (h_res, h_res)
    assert loaded.get_map("height").data == loaded.get_map("terrain").data
    sp = unpack_channels(loaded.get_map("splat").data, 8)
    assert sp.shape == (8, s_res, s_res)
    assert np.allclose(sp[4], 1.0, atol=0.01)
    bi = unpack_channels(loaded.get_map("biome").data, 5)
    assert np.allclose(bi[1], 1.0, atol=0.01)
    tp = unpack_topology(loaded.get_map("topology").data)
    assert int(tp[0, 0]) == int(Topology.FIELD | Topology.MAINLAND)
    assert len(loaded.get_map("alpha").data) == s_res * s_res
