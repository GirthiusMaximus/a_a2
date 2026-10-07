# Phase 3 — Monuments & Roads

This phase adds the two things a terrain-only map is missing: the vanilla
monument set, and a road network tying it together.

---

## 1. Prefab ids are computable (the thing that unblocked this)

Every object in a Rust map file is referenced by a `uint32` prefab id, not by
its asset path:

```
PrefabData { string category; uint32 id; Vector3 position, rotation, scale; }
```

The ids come from `StringPool`, which the game builds from
`GameManifest.pooledStrings`. Unknown strings are registered through
`StringPool.Add`, which calls `str.ManifestHash()`. That hash is:

```
id = uint32_le( md5(lowercase_asset_path)[0:4] )
```

```python
>>> from rustworld.prefabs import prefab_id
>>> prefab_id("assets/prefabs/player/player.prefab")
4108440852
```

This was recovered by brute-forcing candidate hash functions (CRC32, Adler,
FNV-1/1a, MurmurHash2/3 at several seeds, MD5/SHA1 truncations in both byte
orders) against known `(path, id)` pairs, then confirmed against **38** pairs
from the Carbon prefab dump (`api.carbonmod.gg/meta/rust/prefabs.json`).
`tests/test_prefabs.py` keeps all 38 as regression vectors.

**Why it matters:** earlier research concluded a path → id table was not
derivable and monuments were therefore deferred. Because the id is a pure
function of the path, we need no lookup table, no asset bundles, and nothing
to re-sync on each Rust update — any prefab can be emitted from its path
alone. `StringPool.Get` is `OrdinalIgnoreCase`, so we normalise to lowercase
and `/` separators before hashing.

---

## 2. Monument catalogue

`rustworld/monuments.py` holds ~60 monuments taken from the pooled-string
`autospawn/monument` block, so the paths are exactly what the server
resolves. Note several paths that are easy to guess wrong:

| Monument | Actual path segment |
| --- | --- |
| Launch Site | `xlarge/launch_site_1` (not `large/`) |
| Satellite Dish, The Dome | `small/` (not `medium/`) |
| Gas Station, Supermarket, Mining Outpost | `roadside/` |
| Outpost | `medium/compound` |
| Sewer Branch | `medium/radtown_small_3` |
| Lighthouse | `lighthouse/lighthouse` |
| Ferry Terminal | `harbor/ferry_terminal_1` |

Each entry carries placement metadata:

- `radius` — footprint in metres. **Approximate**: Facepunch does not publish
  monument bounds (the real ones live in each prefab's `TerrainPlacement`
  component inside the asset bundles), so these were sized from in-game map
  renders and are deliberately a touch generous.
- `placement` — `land` | `coast` | `offshore`.
- `max_slope`, `flatten`, `biomes`, `min_map_size`, `max_count`, `per_km2`,
  `road_hub`, `default_on`.

Caves, underwater labs, swamps, ice lakes and the extra desert-base variants
ship `default_on=False`: they need terrain features we do not guarantee, or
the server spawns its own.

---

## 3. Placement algorithm

Monuments are sited on a coarse grid (~8–16 m/cell) and stamped back onto the
full-resolution heightmap.

1. **Per-cell terrain stats** — land fraction, mean slope and height relief
   over the monument footprint, all from summed-area tables so each candidate
   test is O(1) regardless of radius.
2. **Feasibility** — map-edge margin, slope and relief limits, plus
   placement-specific rules:
   - `land`: ≥98.5 % land in the footprint, clear of the shoreline,
   - `coast`: ≥55 % land with the waterline inside `0.35–1.5 × radius`,
   - `offshore`: >12 m of water, well clear of land, held back from the border.
   Biome-locked monuments additionally test the dominant biome.
3. **Score** — flat and low-relief ground wins, with an *elevation bonus*.
   That bonus matters: the shoreline shelf is the flattest ground on most
   themes, so a pure flatness score parks every monument on the beach. The
   bonus rewards genuine inland elevation and tapers off in the peaks.
   A seeded random term keeps layouts varied between seeds.
4. **Greedy, biggest-first** — the catalogue is walked in descending radius so
   large monuments claim the good ground; each placement claims a
   `1.5 × radius + 45 m` exclusion disc.
5. **Stamp** — terrain is levelled to the pad height with a smooth apron
   (`0.78 × r` flat, feathered to `1.18 × r`); the footprint is painted with
   `MONUMENT` + `BUILDING` topology, a crisp gravel/dirt pad, and has
   `FOREST`/`FIELD`/`DECOR`/`CLUTTER` cleared.

Monument prefabs re-apply their own `TerrainPlacement` stamp when the server
spawns them; we still flatten in the saved heightmap so the monument does not
sit in a crater in RustEdit or in the preview.

---

## 4. Road network

Vanilla maps are organised around a ring road with spurs to each monument, so
that is what we build (`rustworld/generation/roads.py`):

1. **Cost grid** — `1 + (slope/6)²`, a steep-ground cliff penalty, and a
   water cost of `25 + 4 × depth` so crossings become deliberate bridges and
   roads route around bays rather than through them. Climb between cells adds
   a further grade penalty.
2. **Ring** — 11 jittered waypoints on a circle at `0.30 × size`, each snapped
   to usable land, linked with A* (weighted heuristic) and closed into a loop.
3. **Spurs** — one **multi-source Dijkstra** seeded from every ring cell gives
   the least-cost route from *any* cell back to the ring; each monument then
   just walks the predecessor chain. This replaced a per-monument A* and is
   the reason road building costs ~0.3 s instead of ~5 s.
4. **Shaping** — Chaikin smoothing, resampling to 12 m nodes, and trimming of
   nodes that fall inside a monument footprint.
5. **Terrain** — the height profile along each road is smoothed so the grade
   stays gentle, then a corridor is graded into the heightmap and painted with
   gravel splat plus `ROAD` / `ROADSIDE` topology. Stamping is densified to
   half the road half-width, otherwise the discs leave a beaded dotted line.
6. **Output** — `PathData(name="Road", spline=true, width=12 ring / 9 spur,
   splat=1<<GRAVEL, topology=ROAD)` with world-space nodes.

If the terrain cannot support a ring (tiny islands, naval maps) the ring is
skipped and monuments are linked with a minimum spanning tree instead.
Themes opt out entirely via `ThemeSpec.monuments` / `.roads` — moon and mars
have neither, naval and floating have monuments but no roads.

---

## 5. Options

Recipe fields: `monuments`, `monument_density`, `monument_whitelist`,
`monument_blacklist`, `roads`, `ring_road`.

API: `GET /api/monuments` returns the catalogue (key, name, radius,
placement, biome locks, min map size, prefab path and computed id).

Artifacts: `overlay_monuments.png` (footprints + road network overlay) and
`monuments.json` (machine-readable placements and road polylines).

---

## 6. Known limitations

- Footprint radii are estimates, not the prefab's real `TerrainPlacement`
  bounds. A monument with an unusually long approach ramp may clip terrain.
- Monument yaw is seeded-random on land and faces the water on the coast; it
  is not aligned to the spur road that reaches it.
- Rivers are carved into the heightmap but are not emitted as `PathData`,
  so RustEdit shows no river splines.
- No rail network, power lines, or `monument_marker` prefabs yet.
- Still unverified against a live RustEdit / dedicated server load.
