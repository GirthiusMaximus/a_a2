"""Catalogue of vanilla Rust monuments that can be stamped into a map.

Paths come from the game's pooled-string table (the ``autospawn/monument``
block), so they are exactly what the server resolves at spawn time.  Ids are
computed from the path via :func:`rustworld.prefabs.prefab_id`.

Footprint radii are *approximate* — Facepunch does not publish monument
bounds, and the real bounds are baked into each prefab's ``TerrainPlacement``
component inside the asset bundles.  The values here were sized from in-game
map renders and are used for three things: terrain flattening, monument
spacing, and where roads attach.  They are deliberately a little generous so
monuments do not collide or hang off cliffs.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .prefabs import prefab_id

__all__ = ["MonumentSpec", "MONUMENTS", "monument_keys", "selectable_monuments"]


@dataclass(frozen=True)
class MonumentSpec:
    key: str
    path: str
    name: str
    category: str              # large | medium | small | tiny | water | special
    radius: float              # footprint radius in metres (terrain stamp)
    placement: str = "land"    # land | coast | offshore | lake
    max_slope: float = 14.0    # mean slope (deg) tolerated across the footprint
    flatten: float = 1.0       # 0..1 how hard the terrain is levelled
    biomes: tuple[str, ...] = ()        # allowed biomes ( empty = any )
    min_map_size: int = 1000   # skip on maps smaller than this
    max_count: int = 1         # hard cap per map
    vanilla_count: int = 1     # instances on a real procedural map (vanilla mode)
    per_km2: float = 0.0       # extra instances per km^2 of land (0 = unique)
    road_hub: bool = True      # roads route to this monument
    priority: int = 0          # higher = placed first (defaults to radius)
    default_on: bool = True    # part of the default monument set
    tags: tuple[str, ...] = field(default_factory=tuple)

    @property
    def tiers(self) -> tuple[int, ...]:
        """Loot tiers this monument may spawn in.

        Facepunch gates every monument with ``MonumentInfo.Tier`` (a
        Tier0/Tier1/Tier2 flag set); that is what keeps Launch Site out of
        the starter end of the map.  Derived here from the catalogue tags.
        """
        if "tier2" in self.tags:
            return (2,)
        if "tier1" in self.tags:
            return (1, 2)
        if "safezone" in self.tags:
            return (0, 1)
        return (0, 1, 2)

    @property
    def id(self) -> int:
        return prefab_id(self.path)

    @property
    def place_priority(self) -> float:
        return self.priority * 1000.0 + self.radius


_M = MonumentSpec

# ---------------------------------------------------------------------------
# The catalogue.  Order here is cosmetic; placement is driven by radius.
# ---------------------------------------------------------------------------
_CATALOGUE: list[MonumentSpec] = [
    # ---- xlarge / large ---------------------------------------------------
    _M("launch_site", "assets/bundled/prefabs/autospawn/monument/xlarge/launch_site_1.prefab",
       "Launch Site", "large", 200.0, max_slope=7.0, min_map_size=3500, tags=("tier2",)),
    _M("airfield", "assets/bundled/prefabs/autospawn/monument/large/airfield_1.prefab",
       "Airfield", "large", 150.0, max_slope=7.0, min_map_size=3000, tags=("tier2",)),
    _M("powerplant", "assets/bundled/prefabs/autospawn/monument/large/powerplant_1.prefab",
       "Power Plant", "large", 125.0, max_slope=9.0, min_map_size=2500, tags=("tier2",)),
    _M("water_treatment", "assets/bundled/prefabs/autospawn/monument/large/water_treatment_plant_1.prefab",
       "Water Treatment Plant", "large", 125.0, max_slope=9.0, min_map_size=2500, tags=("tier2",)),
    _M("trainyard", "assets/bundled/prefabs/autospawn/monument/large/trainyard_1.prefab",
       "Train Yard", "large", 115.0, max_slope=9.0, min_map_size=2500, tags=("tier2",)),
    _M("excavator", "assets/bundled/prefabs/autospawn/monument/large/excavator_1.prefab",
       "Giant Excavator Pit", "large", 125.0, max_slope=8.0, min_map_size=3500, tags=("tier2",)),
    _M("military_tunnel", "assets/bundled/prefabs/autospawn/monument/large/military_tunnel_1.prefab",
       "Military Tunnel", "large", 100.0, max_slope=12.0, min_map_size=2500, tags=("tier2",)),

    # ---- medium -----------------------------------------------------------
    _M("outpost", "assets/bundled/prefabs/autospawn/monument/medium/compound.prefab",
       "Outpost", "medium", 100.0, max_slope=7.0, min_map_size=2000, tags=("safezone",)),
    _M("bandit_town", "assets/bundled/prefabs/autospawn/monument/medium/bandit_town.prefab",
       "Bandit Camp", "medium", 95.0, max_slope=7.0, min_map_size=2000, tags=("safezone",)),
    _M("junkyard", "assets/bundled/prefabs/autospawn/monument/medium/junkyard_1.prefab",
       "Junkyard", "medium", 90.0, max_slope=9.0, min_map_size=2500, tags=("tier1",)),
    _M("missile_silo", "assets/bundled/prefabs/autospawn/monument/medium/nuclear_missile_silo.prefab",
       "Missile Silo", "medium", 80.0, max_slope=8.0, min_map_size=3000, tags=("tier2",)),
    _M("radtown", "assets/bundled/prefabs/autospawn/monument/medium/radtown_small_3.prefab",
       "Sewer Branch", "medium", 60.0, max_slope=11.0, min_map_size=2000, tags=("tier1",)),

    # ---- small ------------------------------------------------------------
    _M("satellite_dish", "assets/bundled/prefabs/autospawn/monument/small/satellite_dish.prefab",
       "Satellite Dish Array", "small", 80.0, max_slope=9.0, min_map_size=2000, tags=("tier1",)),
    _M("sphere_tank", "assets/bundled/prefabs/autospawn/monument/small/sphere_tank.prefab",
       "The Dome", "small", 55.0, max_slope=10.0, min_map_size=2000, tags=("tier1",)),
    _M("mining_quarry_a", "assets/bundled/prefabs/autospawn/monument/small/mining_quarry_a.prefab",
       "Sulfur Quarry", "small", 38.0, max_slope=14.0, max_count=2, per_km2=0.10),
    _M("mining_quarry_b", "assets/bundled/prefabs/autospawn/monument/small/mining_quarry_b.prefab",
       "Stone Quarry", "small", 38.0, max_slope=14.0, max_count=2, per_km2=0.10),
    _M("mining_quarry_c", "assets/bundled/prefabs/autospawn/monument/small/mining_quarry_c.prefab",
       "HQM Quarry", "small", 38.0, max_slope=14.0, max_count=2, per_km2=0.10),
    _M("stables_a", "assets/bundled/prefabs/autospawn/monument/small/stables_a.prefab",
       "Ranch", "small", 35.0, max_slope=10.0, max_count=2, per_km2=0.10),
    _M("stables_b", "assets/bundled/prefabs/autospawn/monument/small/stables_b.prefab",
       "Large Barn", "small", 35.0, max_slope=10.0, max_count=2, per_km2=0.10),

    # ---- roadside ---------------------------------------------------------
    _M("gas_station", "assets/bundled/prefabs/autospawn/monument/roadside/gas_station_1.prefab",
       "Oxum's Gas Station", "small", 32.0, max_slope=10.0, max_count=4, per_km2=0.30, vanilla_count=3),
    _M("supermarket", "assets/bundled/prefabs/autospawn/monument/roadside/supermarket_1.prefab",
       "Abandoned Supermarket", "small", 30.0, max_slope=10.0, max_count=4, per_km2=0.30, vanilla_count=3),
    _M("warehouse", "assets/bundled/prefabs/autospawn/monument/roadside/warehouse.prefab",
       "Mining Outpost", "small", 30.0, max_slope=10.0, max_count=4, per_km2=0.30, vanilla_count=3),

    # ---- tiny -------------------------------------------------------------
    _M("water_well_a", "assets/bundled/prefabs/autospawn/monument/tiny/water_well_a.prefab",
       "Water Well A", "tiny", 18.0, max_slope=12.0, max_count=3, per_km2=0.25, road_hub=False),
    _M("water_well_b", "assets/bundled/prefabs/autospawn/monument/tiny/water_well_b.prefab",
       "Water Well B", "tiny", 18.0, max_slope=12.0, max_count=3, per_km2=0.25, road_hub=False),
    _M("water_well_c", "assets/bundled/prefabs/autospawn/monument/tiny/water_well_c.prefab",
       "Water Well C", "tiny", 18.0, max_slope=12.0, max_count=3, per_km2=0.25, road_hub=False),
    _M("water_well_d", "assets/bundled/prefabs/autospawn/monument/tiny/water_well_d.prefab",
       "Water Well D", "tiny", 18.0, max_slope=12.0, max_count=3, per_km2=0.25, road_hub=False),
    _M("water_well_e", "assets/bundled/prefabs/autospawn/monument/tiny/water_well_e.prefab",
       "Water Well E", "tiny", 18.0, max_slope=12.0, max_count=3, per_km2=0.25, road_hub=False),

    # ---- coastal ----------------------------------------------------------
    _M("harbor_1", "assets/bundled/prefabs/autospawn/monument/harbor/harbor_1.prefab",
       "Large Harbor", "medium", 110.0, placement="coast", max_slope=7.0,
       min_map_size=2500, tags=("tier1",)),
    _M("harbor_2", "assets/bundled/prefabs/autospawn/monument/harbor/harbor_2.prefab",
       "Small Harbor", "medium", 95.0, placement="coast", max_slope=7.0,
       min_map_size=2000, tags=("tier1",)),
    _M("ferry_terminal", "assets/bundled/prefabs/autospawn/monument/harbor/ferry_terminal_1.prefab",
       "Ferry Terminal", "medium", 95.0, placement="coast", max_slope=7.0, min_map_size=3000),
    _M("fishing_village_a", "assets/bundled/prefabs/autospawn/monument/fishing_village/fishing_village_a.prefab",
       "Fishing Village A", "small", 35.0, placement="coast", max_slope=9.0,
       max_count=2, per_km2=0.10, road_hub=False, tags=("safezone",)),
    _M("fishing_village_b", "assets/bundled/prefabs/autospawn/monument/fishing_village/fishing_village_b.prefab",
       "Fishing Village B", "small", 35.0, placement="coast", max_slope=9.0,
       max_count=2, per_km2=0.10, road_hub=False, tags=("safezone",)),
    _M("fishing_village_c", "assets/bundled/prefabs/autospawn/monument/fishing_village/fishing_village_c.prefab",
       "Fishing Village C", "small", 35.0, placement="coast", max_slope=9.0,
       max_count=2, per_km2=0.10, road_hub=False, tags=("safezone",)),
    _M("lighthouse", "assets/bundled/prefabs/autospawn/monument/lighthouse/lighthouse.prefab",
       "Lighthouse", "small", 25.0, placement="coast", max_slope=12.0,
       max_count=3, per_km2=0.20, road_hub=False, vanilla_count=2),

    # ---- offshore ---------------------------------------------------------
    _M("oilrig_small", "assets/bundled/prefabs/autospawn/monument/offshore/oilrig_1.prefab",
       "Small Oil Rig", "water", 55.0, placement="offshore", flatten=0.0,
       min_map_size=2500, road_hub=False, tags=("tier2",)),
    _M("oilrig_large", "assets/bundled/prefabs/autospawn/monument/offshore/oilrig_2.prefab",
       "Large Oil Rig", "water", 65.0, placement="offshore", flatten=0.0,
       min_map_size=3000, road_hub=False, tags=("tier2",)),

    # ---- biome specific ---------------------------------------------------
    _M("arctic_base", "assets/bundled/prefabs/autospawn/monument/arctic_bases/arctic_research_base_a.prefab",
       "Arctic Research Base", "medium", 65.0, max_slope=9.0, biomes=("arctic",),
       min_map_size=3000, tags=("tier2",)),
    _M("desert_base_a", "assets/bundled/prefabs/autospawn/monument/military_bases/desert_military_base_a.prefab",
       "Abandoned Military Base A", "medium", 60.0, max_slope=9.0, biomes=("arid",),
       min_map_size=2500, tags=("tier2",)),
    _M("desert_base_b", "assets/bundled/prefabs/autospawn/monument/military_bases/desert_military_base_b.prefab",
       "Abandoned Military Base B", "medium", 60.0, max_slope=9.0, biomes=("arid",),
       min_map_size=2500, default_on=False, tags=("tier2",)),
    _M("desert_base_c", "assets/bundled/prefabs/autospawn/monument/military_bases/desert_military_base_c.prefab",
       "Abandoned Military Base C", "medium", 60.0, max_slope=9.0, biomes=("arid",),
       min_map_size=2500, default_on=False, tags=("tier2",)),
    _M("desert_base_d", "assets/bundled/prefabs/autospawn/monument/military_bases/desert_military_base_d.prefab",
       "Abandoned Military Base D", "medium", 60.0, max_slope=9.0, biomes=("arid",),
       min_map_size=2500, default_on=False, tags=("tier2",)),
    _M("swamp_a", "assets/bundled/prefabs/autospawn/monument/swamp/swamp_a.prefab",
       "Swamp A", "small", 45.0, max_slope=7.0, biomes=("temperate", "jungle"),
       max_count=2, per_km2=0.08, road_hub=False, default_on=False),
    _M("swamp_b", "assets/bundled/prefabs/autospawn/monument/swamp/swamp_b.prefab",
       "Swamp B", "small", 45.0, max_slope=7.0, biomes=("temperate", "jungle"),
       max_count=2, per_km2=0.08, road_hub=False, default_on=False),
    _M("swamp_c", "assets/bundled/prefabs/autospawn/monument/swamp/swamp_c.prefab",
       "Swamp C", "small", 45.0, max_slope=7.0, biomes=("temperate", "jungle"),
       max_count=2, per_km2=0.08, road_hub=False, default_on=False),
    _M("ice_lake_1", "assets/bundled/prefabs/autospawn/monument/ice_lakes/ice_lake_1.prefab",
       "Ice Lake 1", "small", 50.0, max_slope=6.0, biomes=("arctic",),
       max_count=2, per_km2=0.10, road_hub=False, default_on=False),
    _M("ice_lake_2", "assets/bundled/prefabs/autospawn/monument/ice_lakes/ice_lake_2.prefab",
       "Ice Lake 2", "small", 45.0, max_slope=6.0, biomes=("arctic",),
       max_count=2, per_km2=0.10, road_hub=False, default_on=False),
    _M("ice_lake_3", "assets/bundled/prefabs/autospawn/monument/ice_lakes/ice_lake_3.prefab",
       "Ice Lake 3", "small", 45.0, max_slope=6.0, biomes=("arctic",),
       max_count=2, per_km2=0.10, road_hub=False, default_on=False),
    _M("ice_lake_4", "assets/bundled/prefabs/autospawn/monument/ice_lakes/ice_lake_4.prefab",
       "Ice Lake 4", "small", 40.0, max_slope=6.0, biomes=("arctic",),
       max_count=2, per_km2=0.10, road_hub=False, default_on=False),

    # ---- caves (off by default: they need matching cliff geometry) --------
    _M("cave_small_easy", "assets/bundled/prefabs/autospawn/monument/cave/cave_small_easy.prefab",
       "Small Cave (easy)", "tiny", 22.0, max_slope=30.0, flatten=0.0,
       max_count=3, per_km2=0.25, road_hub=False, default_on=False),
    _M("cave_small_medium", "assets/bundled/prefabs/autospawn/monument/cave/cave_small_medium.prefab",
       "Small Cave (medium)", "tiny", 22.0, max_slope=30.0, flatten=0.0,
       max_count=3, per_km2=0.25, road_hub=False, default_on=False),
    _M("cave_small_hard", "assets/bundled/prefabs/autospawn/monument/cave/cave_small_hard.prefab",
       "Small Cave (hard)", "tiny", 22.0, max_slope=30.0, flatten=0.0,
       max_count=2, per_km2=0.15, road_hub=False, default_on=False),
    _M("cave_medium_easy", "assets/bundled/prefabs/autospawn/monument/cave/cave_medium_easy.prefab",
       "Medium Cave (easy)", "small", 30.0, max_slope=30.0, flatten=0.0,
       max_count=2, per_km2=0.15, road_hub=False, default_on=False),
    _M("cave_medium_hard", "assets/bundled/prefabs/autospawn/monument/cave/cave_medium_hard.prefab",
       "Medium Cave (hard)", "small", 30.0, max_slope=30.0, flatten=0.0,
       max_count=2, per_km2=0.15, road_hub=False, default_on=False),
    _M("cave_large_medium", "assets/bundled/prefabs/autospawn/monument/cave/cave_large_medium.prefab",
       "Large Cave", "small", 38.0, max_slope=30.0, flatten=0.0,
       max_count=1, road_hub=False, default_on=False),
    _M("cave_large_hard", "assets/bundled/prefabs/autospawn/monument/cave/cave_large_hard.prefab",
       "Large Cave (hard)", "small", 38.0, max_slope=30.0, flatten=0.0,
       max_count=1, road_hub=False, default_on=False),
    _M("cave_large_sewers_hard", "assets/bundled/prefabs/autospawn/monument/cave/cave_large_sewers_hard.prefab",
       "Sewer Cave", "small", 38.0, max_slope=30.0, flatten=0.0,
       max_count=1, road_hub=False, default_on=False),

    # ---- underwater labs (server places its own; off by default) ----------
    _M("underwater_lab_a", "assets/bundled/prefabs/autospawn/monument/underwater_lab/underwater_lab_a.prefab",
       "Underwater Lab A", "water", 60.0, placement="offshore", flatten=0.0,
       min_map_size=3000, road_hub=False, default_on=False, tags=("tier2",)),
    _M("underwater_lab_b", "assets/bundled/prefabs/autospawn/monument/underwater_lab/underwater_lab_b.prefab",
       "Underwater Lab B", "water", 60.0, placement="offshore", flatten=0.0,
       min_map_size=3000, road_hub=False, default_on=False, tags=("tier2",)),
    _M("underwater_lab_c", "assets/bundled/prefabs/autospawn/monument/underwater_lab/underwater_lab_c.prefab",
       "Underwater Lab C", "water", 60.0, placement="offshore", flatten=0.0,
       min_map_size=3000, road_hub=False, default_on=False, tags=("tier2",)),
    _M("underwater_lab_d", "assets/bundled/prefabs/autospawn/monument/underwater_lab/underwater_lab_d.prefab",
       "Underwater Lab D", "water", 60.0, placement="offshore", flatten=0.0,
       min_map_size=3000, road_hub=False, default_on=False, tags=("tier2",)),
]

MONUMENTS: dict[str, MonumentSpec] = {m.key: m for m in _CATALOGUE}


def monument_keys() -> list[str]:
    return list(MONUMENTS)


def selectable_monuments() -> list[MonumentSpec]:
    """Catalogue in placement order (biggest first)."""
    return sorted(MONUMENTS.values(), key=lambda m: -m.place_priority)
