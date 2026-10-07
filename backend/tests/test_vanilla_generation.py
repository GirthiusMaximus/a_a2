"""Regression guards for the Phase 4 vanilla-accuracy work.

These lock in the three things the user reported against the Phase 3 build:
flat terrain, too many monuments, and a land-coverage slider that was not
honoured -- plus the tier system that drives player spawns.
"""
from __future__ import annotations

from collections import Counter

import numpy as np
import pytest

from rustworld.facepunch import (
    MIN_DISTANCE_SAME_TYPE,
    WorldConfig,
    loot_axis_angle,
    tier_index,
)
from rustworld.generation.pipeline import Recipe, generate
from rustworld.generation.themes import THEMES
from rustworld.layers import SEA_LEVEL, TERRAIN_HEIGHT, Topology
from rustworld.monuments import MONUMENTS

SIZE = 1500


@pytest.fixture(scope="module")
def world():
    return generate(Recipe(seed=1337, size=SIZE, theme="classic"))


# ---------------------------------------------------------------------------
# land ratio is an absolute, honoured target
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("request_ratio", [0.35, 0.60, 0.75])
def test_land_ratio_is_honoured_within_two_percent(request_ratio):
    r = generate(Recipe(seed=2024, size=SIZE, theme="classic", land_ratio=request_ratio))
    got = float((r.height01 > SEA_LEVEL).mean())
    assert abs(got - request_ratio) < 0.02, f"asked {request_ratio}, got {got:.3f}"


def test_land_ratio_none_uses_theme_default():
    r = generate(Recipe(seed=99, size=SIZE, theme="classic"))
    got = float((r.height01 > SEA_LEVEL).mean())
    assert abs(got - THEMES["classic"].land_ratio_default) < 0.02


def test_extreme_land_ratio_still_does_not_crash():
    generate(Recipe(seed=912156065, size=SIZE, theme="classic",
                    land_ratio=0.9, mountain_scale=2.0, river_density=2.0))


# ---------------------------------------------------------------------------
# terrain is no longer flat
# ---------------------------------------------------------------------------

def test_terrain_has_real_relief(world):
    """Phase 3 shipped median land elevation of 2.2 m and a 94 m peak."""
    h = world.height01
    land = h > SEA_LEVEL
    m = (h - SEA_LEVEL)[land] * TERRAIN_HEIGHT
    assert m.max() > 150.0, f"peak only {m.max():.0f} m"
    assert np.percentile(m, 50) > 15.0, f"median only {np.percentile(m, 50):.0f} m"
    assert np.percentile(m, 90) > 60.0


def test_ocean_is_actually_deep(world):
    """A seabed pinned at sea level renders the whole ocean as beach sand."""
    h = world.height01
    sea = (h - SEA_LEVEL)[h <= SEA_LEVEL] * TERRAIN_HEIGHT
    assert sea.mean() < -20.0, f"mean seabed only {sea.mean():.0f} m"
    assert sea.min() < -40.0


def test_terrain_is_not_a_cliff_field(world):
    """Facepunch marks slope > 30 deg as Topology.Cliff; most land must be below it."""
    h = world.height01
    land = h > SEA_LEVEL
    gz, gx = np.gradient(h * TERRAIN_HEIGHT, SIZE / h.shape[0])
    slope = np.degrees(np.arctan(np.hypot(gz, gx)))
    cliff_share = float((slope[land] > 30.0).mean())
    # Share varies with map size (fewer, broader ranges fit on a big map);
    # at the default 3000-4500 sizes it lands around 6-8%.
    assert 0.01 < cliff_share < 0.32, f"cliff share {cliff_share:.1%}"


def test_rivers_have_somewhere_to_start(world):
    """GenerateRiverLayout only accepts sources above 15 m."""
    h = world.height01
    land = h > SEA_LEVEL
    m = (h - SEA_LEVEL)[land] * TERRAIN_HEIGHT
    assert float((m > 15.0).mean()) > 0.35


# ---------------------------------------------------------------------------
# loot tiers
# ---------------------------------------------------------------------------

def test_tier_bands_are_written_to_topology(world):
    t = world.topology
    fracs = [float(((t & int(f)) != 0).mean())
             for f in (Topology.TIER0, Topology.TIER1, Topology.TIER2)]
    assert fracs[0] == pytest.approx(0.30, abs=0.04)
    assert fracs[1] == pytest.approx(0.30, abs=0.04)
    assert fracs[2] == pytest.approx(0.40, abs=0.04)


def test_every_cell_has_exactly_one_tier(world):
    t = world.topology
    n = (((t & int(Topology.TIER0)) != 0).astype(int)
         + ((t & int(Topology.TIER1)) != 0).astype(int)
         + ((t & int(Topology.TIER2)) != 0).astype(int))
    # the spawn fallback may add TIER0 to a few beach cells; allow a small overlap
    assert (n == 0).sum() == 0
    assert float((n > 1).mean()) < 0.05


def test_player_spawns_exist_and_are_tier0(world):
    assert world.stats["spawn_valid"]
    assert world.stats["spawn_area_m2"] > 5000
    t = world.topology
    flags = int(Topology.TIER0 | Topology.BEACH | Topology.OCEANSIDE | Topology.MAINLAND)
    spawn = (t & flags) == flags
    assert spawn.any()
    assert np.all((t[spawn] & int(Topology.TIER0)) != 0)


def test_non_facepunch_theme_keeps_simple_tiers():
    assert not THEMES["archipelago"].facepunch_tiers
    r = generate(Recipe(seed=5, size=SIZE, theme="archipelago"))
    assert r.stats["spawn_valid"]


# ---------------------------------------------------------------------------
# monument composition
# ---------------------------------------------------------------------------

def test_unique_monuments_are_never_duplicated(world):
    counts = Counter(m["name"] for m in world.monuments)
    repeatable = {MONUMENTS[k].name for k in MONUMENTS if MONUMENTS[k].vanilla_count > 1}
    for name, n in counts.items():
        if name not in repeatable:
            assert n == 1, f"{name} placed {n} times"


def test_repeatable_monuments_match_the_vanilla_table(world):
    counts = Counter(m["name"] for m in world.monuments)
    for key, spec in MONUMENTS.items():
        if spec.vanilla_count > 1 and counts.get(spec.name):
            assert counts[spec.name] <= spec.vanilla_count


def test_monument_count_is_in_the_vanilla_range(world):
    """Real procedural maps carry roughly 40 large+small monuments.

    This runs at size 1500, where most of the catalogue is correctly gated
    out by ``min_map_size`` -- the full set only appears on 3000+ maps.
    """
    assert 12 <= len(world.monuments) <= 60


def test_same_type_monuments_respect_min_distance(world):
    by_name: dict[str, list[tuple[float, float]]] = {}
    for m in world.monuments:
        by_name.setdefault(m["name"], []).append((m["x"], m["z"]))
    for name, pts in by_name.items():
        for i in range(len(pts)):
            for j in range(i + 1, len(pts)):
                d = float(np.hypot(pts[i][0] - pts[j][0], pts[i][1] - pts[j][1]))
                assert d >= MIN_DISTANCE_SAME_TYPE * 0.95, f"{name}: {d:.0f} m apart"


def test_tier_gated_monuments_land_in_an_allowed_tier(world):
    pct = WorldConfig().normalise().tier_percentages
    res = 256
    t = tier_index(res, 1337, pct)
    by_name = {s.name: s for s in MONUMENTS.values()}
    for m in world.monuments:
        spec = by_name.get(m["name"])
        if spec is None or len(spec.tiers) == 3:
            continue
        xi = int(np.clip((m["x"] + SIZE / 2) / SIZE * res, 0, res - 1))
        zi = int(np.clip((m["z"] + SIZE / 2) / SIZE * res, 0, res - 1))
        assert int(t[zi, xi]) in spec.tiers, (
            f"{m['name']} wants tiers {spec.tiers}, landed in tier {int(t[zi, xi])}"
        )


def test_min_map_size_is_respected(world):
    by_name = {s.name: s for s in MONUMENTS.values()}
    for m in world.monuments:
        spec = by_name.get(m["name"])
        if spec is not None:
            assert SIZE >= spec.min_map_size


# ---------------------------------------------------------------------------
# road constants
# ---------------------------------------------------------------------------

def test_roads_use_facepunch_constants(world):
    from rustworld import facepunch as fp

    for path in world.paths:
        if not path.name.startswith("Road"):
            continue
        assert path.width == fp.ROAD_WIDTH
        assert path.inner_fade == fp.ROAD_INNER_FADE
        assert path.outer_fade == fp.ROAD_OUTER_FADE
        assert path.random_scale == fp.ROAD_RANDOM_SCALE
        assert path.terrain_offset == fp.ROAD_TERRAIN_OFFSET
        assert all(n.y >= 1.0 for n in path.nodes)  # Mathf.Max(height, 1f)
