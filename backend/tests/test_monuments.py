"""Monument placement + road network behaviour."""
from __future__ import annotations

import numpy as np
import pytest

from rustworld import build_world, save_map_bytes
from rustworld.generation import Recipe, generate
from rustworld.layers import SEA_LEVEL, TERRAIN_HEIGHT, Topology
from rustworld.monuments import MONUMENTS
from rustworld.worldfile import load_map_bytes


@pytest.fixture(scope="module")
def world():
    return generate(Recipe(seed=4242, size=3000, theme="classic"))


def test_monuments_are_placed(world) -> None:
    assert world.stats["monument_count"] >= 8
    assert len(world.prefabs) == world.stats["monument_count"]


def test_monuments_stay_inside_the_map(world) -> None:
    half = world.size / 2.0
    for m in world.monuments:
        assert -half < m["x"] < half
        assert -half < m["z"] < half
        # footprint must not hang off the edge either
        assert abs(m["x"]) + m["radius"] < half
        assert abs(m["z"]) + m["radius"] < half


def test_monuments_do_not_overlap(world) -> None:
    ms = world.monuments
    for i, a in enumerate(ms):
        for b in ms[i + 1:]:
            d = float(np.hypot(a["x"] - b["x"], a["z"] - b["z"]))
            assert d > (a["radius"] + b["radius"]) * 0.5, f"{a['name']} overlaps {b['name']}"


def test_land_monuments_are_above_water(world) -> None:
    for m in world.monuments:
        spec = MONUMENTS[m["key"]]
        if spec.placement == "offshore":
            continue
        assert m["y"] >= -1.0, f"{m['name']} is underwater at {m['y']}m"


def test_monument_footprints_are_flat(world) -> None:
    """The stamped pad should be level enough to actually build on."""
    res = world.height01.shape[0]
    size = world.size
    for m in world.monuments:
        spec = MONUMENTS[m["key"]]
        if spec.flatten <= 0.0:
            continue
        cx = (m["x"] + size / 2.0) / size * res
        cz = (m["z"] + size / 2.0) / size * res
        r = m["radius"] * 0.6 / size * res
        x0, x1 = int(max(cx - r, 0)), int(min(cx + r + 1, res))
        z0, z1 = int(max(cz - r, 0)), int(min(cz + r + 1, res))
        patch = world.height01[z0:z1, x0:x1]
        spread_m = float(patch.max() - patch.min()) * TERRAIN_HEIGHT
        assert spread_m < 12.0, f"{m['name']} pad varies by {spread_m:.1f}m"


def test_monument_topology_is_marked(world) -> None:
    assert ((world.topology & int(Topology.MONUMENT)) != 0).any()
    assert ((world.topology & int(Topology.BUILDING)) != 0).any()


def test_roads_exist_and_are_marked(world) -> None:
    assert world.stats["road_count"] >= 1
    assert world.stats["road_length_km"] > 1.0
    assert ((world.topology & int(Topology.ROAD)) != 0).any()
    assert ((world.topology & int(Topology.ROADSIDE)) != 0).any()


def test_road_nodes_are_sane(world) -> None:
    half = world.size / 2.0
    for path in world.paths:
        assert path.name == "Road"
        assert len(path.nodes) >= 2
        assert path.width > 0
        for n in path.nodes:
            assert -half <= n.x <= half
            assert -half <= n.z <= half
            assert -500.0 < n.y < 500.0


def test_roads_follow_the_ground(world) -> None:
    """Road nodes should sit on the carved corridor, not float or sink."""
    res = world.height01.shape[0]
    size = world.size
    worst = 0.0
    for path in world.paths:
        for n in path.nodes:
            xi = int(np.clip((n.x + size / 2) / size * res, 0, res - 1))
            zi = int(np.clip((n.z + size / 2) / size * res, 0, res - 1))
            ground = (float(world.height01[zi, xi]) - SEA_LEVEL) * TERRAIN_HEIGHT
            worst = max(worst, abs(ground - n.y))
    assert worst < 6.0, f"road deviates from terrain by {worst:.1f}m"


def test_disabling_monuments_and_roads(world) -> None:
    bare = generate(Recipe(seed=4242, size=3000, theme="classic",
                           monuments=False, roads=False))
    assert bare.stats["monument_count"] == 0
    assert bare.stats["road_count"] == 0
    assert not bare.prefabs and not bare.paths
    assert ((bare.topology & int(Topology.ROAD)) != 0).sum() == 0


def test_blacklist_removes_a_monument() -> None:
    res = generate(Recipe(seed=4242, size=3000, theme="classic",
                          monument_blacklist=["airfield", "launch_site"],
                          roads=False))
    keys = {m["key"] for m in res.monuments}
    assert "airfield" not in keys and "launch_site" not in keys


def test_whitelist_limits_the_set() -> None:
    res = generate(Recipe(seed=7, size=3000, theme="classic",
                          monument_whitelist=["sphere_tank", "lighthouse"],
                          roads=False))
    assert {m["key"] for m in res.monuments} <= {"sphere_tank", "lighthouse"}
    assert res.stats["monument_count"] >= 1


def test_barren_themes_have_no_monuments() -> None:
    res = generate(Recipe(seed=11, size=2000, theme="moon"))
    assert res.stats["monument_count"] == 0
    assert res.stats["road_count"] == 0


def test_prefabs_and_paths_round_trip_through_the_map_file(world) -> None:
    w = build_world(
        world.size, world.height01, world.water01,
        world.splat, world.biome, world.topology,
        prefabs=world.prefabs, paths=world.paths,
    )
    blob = save_map_bytes(w)
    back, _version = load_map_bytes(blob)

    assert len(back.prefabs) == len(world.prefabs)
    for a, b in zip(world.prefabs, back.prefabs):
        assert a.id == b.id
        assert a.position.x == pytest.approx(b.position.x, abs=1e-3)
        assert a.position.y == pytest.approx(b.position.y, abs=1e-3)
        assert a.position.z == pytest.approx(b.position.z, abs=1e-3)
        assert a.rotation.y == pytest.approx(b.rotation.y, abs=1e-3)

    assert len(back.paths) == len(world.paths)
    for a, b in zip(world.paths, back.paths):
        assert a.name == b.name
        assert len(a.nodes) == len(b.nodes)
        assert a.width == pytest.approx(b.width, abs=1e-3)
        assert a.splat == b.splat and a.topology == b.topology


def test_monument_density_scales_counts() -> None:
    few = generate(Recipe(seed=99, size=3000, theme="classic",
                          monument_density=0.0, roads=False))
    many = generate(Recipe(seed=99, size=3000, theme="classic",
                           monument_density=2.0, roads=False))
    assert many.stats["monument_count"] > few.stats["monument_count"]


def test_generation_is_deterministic() -> None:
    a = generate(Recipe(seed=555, size=2000, theme="classic"))
    b = generate(Recipe(seed=555, size=2000, theme="classic"))
    assert a.monuments == b.monuments
    assert a.roads == b.roads
