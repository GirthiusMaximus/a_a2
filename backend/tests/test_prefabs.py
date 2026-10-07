"""Prefab id derivation + monument catalogue sanity."""
from __future__ import annotations

import pytest

from rustworld.monuments import MONUMENTS, selectable_monuments
from rustworld.prefabs import normalise_path, prefab_id

# (path, id) pairs taken from the Carbon prefab dump
# (https://api.carbonmod.gg/meta/rust/prefabs.json) plus the long-documented
# player.prefab id.  These pin the hash: id = uint32_le(md5(path)[:4]).
KNOWN = [
    ("assets/prefabs/player/player.prefab", 4108440852),
    ("assets/bundled/prefabs/system/performance.prefab", 321173649),
    ("assets/bundled/prefabs/system/server.prefab", 4183588704),
    ("assets/bundled/prefabs/system/server_console.prefab", 2717563973),
    ("assets/bundled/prefabs/system/steam.prefab", 3293128464),
    ("assets/bundled/prefabs/system/steam_client.prefab", 1088702304),
    ("assets/prefabs/building/door.hinged/effects/door-wood-open-start.prefab", 714438472),
    ("assets/prefabs/building/door.hinged/effects/door-wood-open-end.prefab", 1450485940),
    ("assets/prefabs/building/door.hinged/effects/door-wood-knock.prefab", 361333517),
    ("assets/prefabs/deployable/barricades/effects/damage.prefab", 3240254756),
    ("assets/bundled/prefabs/fx/build/repair_full_metal.prefab", 2350903527),
    ("assets/bundled/prefabs/fx/build/repair_metal.prefab", 2187858850),
    ("assets/prefabs/npc/scientist/sound/chatter.prefab", 856067623),
    ("assets/prefabs/npc/autoturret/effects/offline.prefab", 3111275805),
    ("assets/content/sound/templates/small-spread-sound.prefab", 846573508),
    ("assets/content/sound/templates/medium-large-sound.prefab", 2898489146),
    ("assets/content/sound/templates/bullet-flyby.prefab", 3197869613),
    ("assets/prefabs/missions/effects/mission_failed.prefab", 2649100417),
    ("assets/prefabs/deployable/research table/effects/research-start.prefab", 3218551988),
    ("assets/prefabs/locks/keypad/effects/lock.code.shock.prefab", 821899790),
    ("assets/prefabs/plants/hemp/hemp.skin.4.fruiting.prefab", 3557507480),
    ("assets/prefabs/plants/pumpkin/pumpkin.skin.5.dying.prefab", 1268716940),
    ("assets/content/nature/treessource/palm_trees/palm_tree_tropical_short_d.prefab", 2976243279),
    ("assets/content/nature/treessource/palm_trees/palm_tree_tropical_tall_a.prefab", 2933783591),
    ("assets/content/nature/treessource/palm_trees/palm_tree_tropical_med_a.prefab", 4083329169),
    ("assets/content/nature/treessource/palm_trees/palm_tree_tropical_short_a.prefab", 689883357),
    ("assets/content/nature/treessource/palm_trees/palm_tree_tropical_short_c.prefab", 3671678118),
    ("assets/content/vehicles/boats/effects/small-boat-push-water.prefab", 3880717310),
    ("assets/prefabs/deployable/boat building platform/boatbuildingstation.guide.prefab", 3322324641),
    ("assets/prefabs/deployable/boatbuilding/cannon/effects/cannonball_explosion.prefab", 2284784967),
    ("assets/prefabs/building/wall.frame.fence/effects/door-fence-metal-open-end.prefab", 1513384943),
    ("assets/prefabs/building/wall.frame.fence/effects/door-fence-metal-close-end.prefab", 1854170922),
    ("assets/prefabs/deployable/elevator/effects/door-elevator-cage-close-start.prefab", 2813735644),
    ("assets/prefabs/deployable/wooden loot crates/sound/wooden-crate-2-gib.prefab", 1937001925),
    ("assets/prefabs/weapons/f1 grenade/effects/bounce.prefab", 977761430),
    ("assets/prefabs/tools/smoke grenade/effects/ignite.prefab", 1277383634),
    ("assets/bundled/prefabs/fx/entities/pumpkin/gib.prefab", 2619374519),
    (
        "assets/content/sound/monuments/nuclearmissilesilo/effects/"
        "nuclear-missile-silo-elevator-door-close-start.prefab",
        3468265436,
    ),
]


@pytest.mark.parametrize("path,expected", KNOWN)
def test_prefab_id_matches_game(path: str, expected: int) -> None:
    assert prefab_id(path) == expected


def test_prefab_id_is_case_and_separator_insensitive() -> None:
    a = prefab_id("assets/prefabs/player/player.prefab")
    assert prefab_id("Assets/Prefabs/Player/Player.prefab") == a
    assert prefab_id("assets\\prefabs\\player\\player.prefab") == a


def test_prefab_id_fits_uint32() -> None:
    for spec in MONUMENTS.values():
        assert 0 <= spec.id <= 0xFFFFFFFF


def test_monument_paths_are_wellformed() -> None:
    for spec in MONUMENTS.values():
        assert spec.path == normalise_path(spec.path)
        assert spec.path.startswith("assets/bundled/prefabs/autospawn/monument/")
        assert spec.path.endswith(".prefab")


def test_monument_ids_are_unique() -> None:
    ids = [m.id for m in MONUMENTS.values()]
    assert len(set(ids)) == len(ids)


def test_catalogue_is_ordered_biggest_first() -> None:
    radii = [m.radius for m in selectable_monuments()]
    assert radii == sorted(radii, reverse=True)
