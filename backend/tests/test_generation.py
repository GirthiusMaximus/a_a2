"""Generation pipeline + renderer tests."""
import numpy as np
import pytest

from rustworld.generation import Recipe, generate, THEMES
from rustworld.layers import SEA_LEVEL, Topology
from rustworld.render import (
    animal_spawn_mask,
    ore_spawn_mask,
    player_spawn_mask,
    render_biome_image,
    render_map_image,
)
from rustworld.heightmap_io import export_png16, export_raw16, import_heightmap


SMALL = dict(size=1000)  # 513/512 res — fast tests


def test_generate_classic_deterministic():
    r1 = generate(Recipe(seed=1234, **SMALL))
    r2 = generate(Recipe(seed=1234, **SMALL))
    assert np.array_equal(r1.height01, r2.height01)
    assert np.array_equal(r1.topology, r2.topology)
    r3 = generate(Recipe(seed=9999, **SMALL))
    assert not np.array_equal(r1.height01, r3.height01)


def test_generate_produces_valid_spawn_area():
    res = generate(Recipe(seed=42, **SMALL))
    assert res.stats["spawn_valid"], res.stats
    mask = player_spawn_mask(res.topology)
    assert mask.sum() > 50


def test_land_has_ocean_border():
    res = generate(Recipe(seed=7, **SMALL))
    edge = np.concatenate([
        res.height01[0], res.height01[-1], res.height01[:, 0], res.height01[:, -1]
    ])
    assert (edge < SEA_LEVEL).mean() > 0.95  # borders are ocean


@pytest.mark.parametrize("theme", sorted(THEMES))
def test_all_themes_generate(theme):
    res = generate(Recipe(seed=5, theme=theme, **SMALL))
    assert res.splat.shape[0] == 8
    assert res.biome.shape[0] == 5
    totals = res.splat.sum(axis=0)
    assert np.allclose(totals, 1.0, atol=0.02)
    btot = res.biome.sum(axis=0)
    assert np.allclose(btot, 1.0, atol=0.02)
    assert res.stats["spawn_valid"], f"{theme}: {res.stats}"


def test_biome_blacklist():
    res = generate(Recipe(seed=11, biome_blacklist=["arctic", "tundra"], **SMALL))
    assert res.biome[3].max() == 0.0  # arctic
    assert res.biome[2].max() == 0.0  # tundra


def test_topology_blacklist():
    res = generate(Recipe(seed=11, topology_blacklist=["swamp"], **SMALL))
    assert (res.topology & Topology.SWAMP).max() == 0


def test_spawn_masks_disjoint_from_blockers():
    res = generate(Recipe(seed=21, **SMALL))
    ore = ore_spawn_mask(res.topology)
    animal = animal_spawn_mask(res.topology)
    ocean = (res.topology & Topology.OCEAN) != 0
    assert not (ore & ocean).any()
    assert not (animal & ocean).any()


def test_render_map_image():
    res = generate(Recipe(seed=3, **SMALL))
    img = render_map_image(res.size, res.height01, res.splat, res.water01, image_res=256)
    assert img.size[0] == img.size[1]
    arr = np.asarray(img)
    assert arr.std() > 10  # not a flat image
    bimg = render_biome_image(res.biome)
    assert bimg.size == (res.biome.shape[1], res.biome.shape[2])


def test_heightmap_io_roundtrip():
    res = generate(Recipe(seed=13, **SMALL))
    png = export_png16(res.height01)
    back = import_heightmap(png, "test.png")
    assert back.shape == res.height01.shape
    assert np.allclose(back, res.height01, atol=1e-3)
    raw = export_raw16(res.height01)
    back_raw = import_heightmap(raw, "test.raw")
    assert np.allclose(back_raw, res.height01, atol=1e-3)


def test_custom_heightmap_input():
    hm = np.linspace(0.4, 0.6, 257 * 257, dtype=np.float32).reshape(257, 257)
    res = generate(Recipe(seed=1, size=1000, heightmap=hm))
    assert res.height01.shape == (513, 513)
