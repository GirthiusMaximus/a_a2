"""Verify the Facepunch primitives behave exactly like the C# originals."""
from __future__ import annotations

import math
from collections import Counter

import numpy as np
import pytest

from rustworld.facepunch import (
    CLIFF_SLOPE,
    MIN_DISTANCE_SAME_TYPE,
    RIVER_MIN_SEPARATION,
    ROAD_WIDTH,
    ROCK_SLOPE_MAX,
    ROCK_SLOPE_MIN,
    SeedRandom,
    WorldConfig,
    axis_projection,
    biome_axis_angle,
    loot_axis_angle,
    river_count,
    tier_index,
)


# ---------------------------------------------------------------------------
# PRNG
# ---------------------------------------------------------------------------

def _ref_xorshift(x: int) -> int:
    """Independent restatement of the C# body, to catch a typo in the port."""
    m = 0xFFFFFFFF
    x = (x ^ (x << 13)) & m
    x = x ^ (x >> 17)
    x = (x ^ (x << 5)) & m
    return x


def test_xorshift_matches_reference():
    state = 1
    r = SeedRandom(1)
    for _ in range(1000):
        state = _ref_xorshift(state)
        assert r.xorshift() == state


def test_xorshift_is_32_bit_and_never_zero_from_nonzero_seed():
    r = SeedRandom(0x12345678)
    for _ in range(10000):
        v = r.xorshift()
        assert 0 <= v <= 0xFFFFFFFF
        assert v != 0


def test_value_in_unit_interval():
    for seed in range(1, 5000):
        v = SeedRandom(seed).value()
        assert 0.0 <= v < 1.0


def test_range_int_respects_bounds():
    r = SeedRandom(99)
    for _ in range(5000):
        v = r.range_int(-45, 46)
        assert -45 <= v <= 45


def test_sign_is_plus_or_minus_one():
    r = SeedRandom(7)
    seen = {r.sign() for _ in range(200)}
    assert seen == {-1, 1}


def test_value2d_is_unit_length():
    r = SeedRandom(31337)
    for _ in range(500):
        x, y = r.value2d()
        assert math.isclose(math.hypot(x, y), 1.0, rel_tol=1e-6)


def test_streams_are_deterministic_and_seed_dependent():
    a = [SeedRandom(4242).value() for _ in range(10)]
    b = [SeedRandom(4242).value() for _ in range(10)]
    c = [SeedRandom(4243).value() for _ in range(10)]
    assert a == b
    assert a != c


def test_wanghash_matches_reference():
    m = 0xFFFFFFFF
    x = 0xABCDEF
    r = SeedRandom(x)
    for _ in range(200):
        x = (x ^ 0x3D ^ (x >> 16)) & m
        x = (x * 9) & m
        x ^= x >> 4
        x = (x * 668265261) & m
        x ^= x >> 15
        assert r.wanghash() == x


# ---------------------------------------------------------------------------
# Seed-derived axes
# ---------------------------------------------------------------------------

def test_loot_axis_is_always_cardinal():
    for seed in range(1, 3000):
        assert loot_axis_angle(seed) in (0.0, 90.0, 180.0, 270.0)


def test_loot_axis_is_uniform_over_the_four_quadrants():
    counts = Counter(loot_axis_angle(s) for s in range(1, 40001))
    assert set(counts) == {0.0, 90.0, 180.0, 270.0}
    for v in counts.values():
        assert abs(v - 10000) < 500, counts


def test_biome_axis_is_roughly_perpendicular_to_loot_axis():
    """BiomeAxisAngle = loot + jitter(-45..45) + sign*90."""
    for seed in range(1, 2000):
        loot = loot_axis_angle(seed)
        biome = biome_axis_angle(seed)
        offset = (biome - loot) % 360.0
        # +-90 plus up to 45 degrees of jitter
        delta = min(abs(offset - 90.0), abs(offset - 270.0))
        assert delta <= 45.0, (seed, loot, biome, offset)


def test_known_seed_axis_values_are_stable():
    # Regression lock: these come from the ported derivation and must not drift.
    assert (loot_axis_angle(1337), biome_axis_angle(1337)) == (180.0, 51.0)
    assert (loot_axis_angle(42), biome_axis_angle(42)) == (0.0, -63.0)
    assert (loot_axis_angle(2025), biome_axis_angle(2025)) == (270.0, 153.0)
    assert loot_axis_angle(912156065) == 0.0


# ---------------------------------------------------------------------------
# Tier bands
# ---------------------------------------------------------------------------

def test_axis_projection_spans_unit_range():
    for angle in (0.0, 90.0, 180.0, 270.0):
        p = axis_projection(64, angle)
        assert p.min() == pytest.approx(0.0, abs=1e-5)
        assert p.max() == pytest.approx(1.0, abs=1e-5)


def test_cardinal_projection_is_axis_aligned():
    # 90 degrees -> +X, so every row is identical and columns increase.
    p = axis_projection(32, 90.0)
    assert np.allclose(p, p[0][None, :])
    assert np.all(np.diff(p[0]) > 0)
    # 0 degrees -> +Z, so every column is identical and rows increase.
    q = axis_projection(32, 0.0)
    assert np.allclose(q, q[:, 0][:, None])
    assert np.all(np.diff(q[:, 0]) > 0)


def test_tier_bands_hit_the_vanilla_30_30_40_split():
    pct = WorldConfig().normalise().tier_percentages
    t = tier_index(512, seed=1337, pct=pct)
    frac = [float((t == i).mean()) for i in range(3)]
    assert frac[0] == pytest.approx(0.30, abs=0.01)
    assert frac[1] == pytest.approx(0.30, abs=0.01)
    assert frac[2] == pytest.approx(0.40, abs=0.01)


def test_tier_bands_are_contiguous_stripes():
    t = tier_index(128, seed=2025, pct=(0.3, 0.3, 0.4))
    # along the loot axis the tier index must be non-decreasing
    assert loot_axis_angle(2025) == 270.0  # -X, so tiers increase right-to-left
    row = t[t.shape[0] // 2]
    assert np.all(np.diff(row.astype(int)) <= 0)


def test_all_three_tiers_present_for_every_cardinal_axis():
    for seed in (1337, 42, 2025, 1234567):
        t = tier_index(96, seed, (0.3, 0.3, 0.4))
        assert set(np.unique(t)) == {0, 1, 2}


# ---------------------------------------------------------------------------
# WorldConfig
# ---------------------------------------------------------------------------

def test_vanilla_defaults():
    c = WorldConfig()
    assert (c.percentage_tier0, c.percentage_tier1, c.percentage_tier2) == (0.3, 0.3, 0.4)
    assert c.biome_percentages == (0.4, 0.15, 0.15, 0.3)
    assert c.underwater_labs and c.rivers and c.main_roads


def test_normalise_scales_to_one():
    c = WorldConfig(percentage_tier0=3, percentage_tier1=3, percentage_tier2=4).normalise()
    assert sum(c.tier_percentages) == pytest.approx(1.0)
    assert c.percentage_tier2 == pytest.approx(0.4)
    assert sum(c.biome_percentages) == pytest.approx(1.0)


def test_normalise_zero_sum_fallbacks():
    c = WorldConfig(percentage_tier0=0, percentage_tier1=0, percentage_tier2=0).normalise()
    assert c.tier_percentages == (0.0, 1.0, 0.0)
    d = WorldConfig(
        percentage_biome_arid=0,
        percentage_biome_temperate=0,
        percentage_biome_tundra=0,
        percentage_biome_arctic=0,
    ).normalise()
    assert d.biome_percentages == (0.0, 1.0, 0.0, 0.0)


def test_jungle_is_excluded_from_biome_normalisation():
    c = WorldConfig().normalise()
    assert c.percentage_biome_jungle == 0.5


def test_is_prefab_allowed_substring_semantics():
    c = WorldConfig(prefab_blacklist=["oilrig"])
    assert not c.is_prefab_allowed("assets/.../offshore/oilrig_1.prefab")
    assert c.is_prefab_allowed("assets/.../large/airfield_1.prefab")

    w = WorldConfig(prefab_whitelist=["harbor"])
    assert w.is_prefab_allowed("assets/.../harbor/harbor_1.prefab")
    assert not w.is_prefab_allowed("assets/.../large/airfield_1.prefab")

    # blacklist is evaluated first and wins
    b = WorldConfig(prefab_blacklist=["harbor"], prefab_whitelist=["harbor"])
    assert not b.is_prefab_allowed("assets/.../harbor/harbor_1.prefab")


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_terrain_and_path_constants_match_the_game():
    assert CLIFF_SLOPE == 30.0
    assert (ROCK_SLOPE_MIN, ROCK_SLOPE_MAX) == (30.0, 50.0)
    assert ROAD_WIDTH == 10.0
    assert MIN_DISTANCE_SAME_TYPE == 500.0
    assert RIVER_MIN_SEPARATION == pytest.approx(260.0)


def test_river_count_threshold():
    assert river_count(3000) == 2
    assert river_count(4000) == 2
    assert river_count(4001) == 3
    assert river_count(6000) == 3
