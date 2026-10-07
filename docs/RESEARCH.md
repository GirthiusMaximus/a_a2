# Rust World Generator — Research Report & Build Plan

**Date:** 2026-10-07
**Status:** Research complete — awaiting stakeholder sign-off before implementation.

This document covers the research for a Docker-hosted, web-based procedural map generator for the game **Rust** (Facepunch), producing `.map` files that drop directly into a Rust dedicated server or open in **RustEdit**, with 2D/3D previews, themed generation, spawn overlays, blacklisting options, and a job queue.

---

## 1. The Rust `.map` file format (fully reverse-engineered)

Sources: Facepunch Rust Wiki (Map Data / Terrain / Topology pages), the Rust.World SDK as shipped inside the open-source editors **RustMapEditor** (Adsito) and **RustMapper** (kilgoar), and the K4os.Compression.LZ4 library source. All verified against actual SDK code during research.

### 1.1 Container layout

```
[uint32  world serialization version]   // currently 10 (little-endian)
[uint64  timestamp]                     // .NET ticks-style timestamp; readers skip it
[LZ4 "legacy" (lz4net) stream]          // compressed protobuf payload: WorldData
```

- Compression is **NOT** the standard LZ4 Frame format. It is the lz4net `LZ4Stream` chunked format (what `K4os.Compression.LZ4.Legacy` reads/writes). Verified from K4os source — each chunk is:
  ```
  varint(chunkFlags)        // 7-bit little-endian varint; bit0 = compressed, bit1 = high-compression
  varint(originalLength)    // uncompressed byte count (default block size = 1 MiB)
  varint(compressedLength)  // ONLY present when the compressed flag is set
  <raw LZ4 block bytes>     // standard LZ4 *block* format (no header)
  ```
  This is straightforward to implement in any language on top of a standard LZ4 *block* codec (e.g. Python `lz4.block` with `store_size=False`).

### 1.2 Protobuf payload (`WorldData`, protobuf-net field numbers)

```protobuf
message WorldData {               // field numbers from the SDK
  uint32 size      = 1;           // world edge length in meters (1000–6000, vanilla default 4500)
  repeated MapData maps    = 2;
  repeated PrefabData prefabs = 3;
  repeated PathData paths  = 4;
}
message MapData   { string name = 1; bytes data = 2; }   // named terrain layer blobs
message PrefabData{
  string category = 1;            // e.g. "Decor", or RustEdit category string
  uint32 id       = 2;            // prefab ID (game-manifest hash of the asset path)
  VectorData position = 3; VectorData rotation = 4; VectorData scale = 5;
}
message PathData  {               // roads / rivers / rails / powerlines
  string name = 1;                // "Road", "River", "Rail", "Powerline…"
  bool  spline = 2; bool start = 3; bool end = 4;
  float width = 5; float innerPadding = 6; float outerPadding = 7;
  float innerFade = 8; float outerFade = 9; float randomScale = 10;
  float meshOffset = 11; float terrainOffset = 12;
  int32 splat = 13; int32 topology = 14;
  repeated VectorData nodes = 15; // world-space node positions
}
message VectorData { float x = 1; float y = 2; float z = 3; }
```

### 1.3 Terrain layer blobs (`MapData.name` → encoding)

All multi-channel maps are **channel-major**: index = `(c * res + z) * res + x`. Resolution is implied by blob length (`res = sqrt(len / bytesPerElement / channels)`).

| name       | element | channels | content |
|------------|---------|----------|---------|
| `terrain`  | int16   | 1 | land heightmap, normalized height `h ∈ [0,1]` stored as `short = h * 32766 + 0.5` |
| `height`   | int16   | 1 | duplicate of `terrain` (both are written; game reads `terrain`, some tools read `height`) |
| `water`    | int16   | 1 | water heightmap, same encoding (flat 0.5 = sea level on normal maps) |
| `splat`    | uint8   | 8 | ground texture weights 0–255: Dirt, Snow, Sand, Rock, Grass, Forest, Stones, Gravel (idx 0–7); weights should sum to ~255 per texel |
| `biome`    | uint8   | 4 or 5 | Arid, Temperate, Tundra, Arctic (+ **Jungle** as 5th channel since the 2025 Jungle update; 4-channel maps still load) |
| `alpha`    | uint8   | 1 | terrain visibility/holes: 255 = visible, 0 = hole (caves/monument basements) |
| `topology` | int32   | 1 | **bitmask** per texel, 31 defined flags (see §3) |

**Resolutions** (from the SDK editors; matches the game's "1 vertex per meter" target):
- heightmap res = `NextPowerOfTwo(size / 2) + 1` → size 1000→513, 2000→1025, 3000–4000→2049, 4500–6000→4097 *(RustEdit accepts 513/1025/2049/4097 heightmaps)*
- splat/biome/alpha/topology res = `NextPowerOfTwo(size / 2)` clamped to [16, 2048]

**Coordinate system / vertical scale:**
- Terrain vertical size is **1000 m**; terrain is positioned so world Y = `(h × 1000) − 500`, i.e. normalized 0.5 ≈ **sea level (Y = 0)**; new flat maps default to land height 503 m (just above the sea).
- X/Z world origin is the **map center**; terrain spans `[-size/2, +size/2]`. Prefab/path positions are in these world coordinates.

### 1.4 Prefab IDs

`PrefabData.id` is the uint hash assigned in the game's `GameManifest` (the StringPool), mapping asset paths like `assets/bundled/prefabs/autospawn/monument/harbor/harbor_1.prefab` → uint. These IDs are **not** computable from the path with a public algorithm — they come from the game manifest. Community-maintained path→ID tables exist (Rust Map Making community; the open-source editors extract them from installed game content). **Plan:** embed a curated JSON table of needed prefab IDs (monuments, utility prefabs, spawn points, resource/decor prefabs), refreshable from a game install or a community dump.

**Utility prefabs relevant to us** (from the wiki/RustEdit): spawn point prefabs, "modifier" volume prefabs (prevent-building, radiation), and monument marker prefabs. Note: trees/ores/animals are **not** usually baked as prefabs — the server spawns them dynamically (see §3).

### 1.5 RustEdit compatibility

- RustEdit opens any valid `.map` (v8/v9/v10). It also *appends its own extra `MapData` entries* for custom IO circuits, NPC spawners, building blocks, etc. — these are optional; a map without them is perfectly valid.
- RustEdit also imports raw **16-bit grayscale heightmaps** (RAW/PNG) at 513/1025/2049/4097 — so we will offer both `.map` and 16-bit heightmap (RAW + PNG) exports, and accept 16-bit (or 8-bit, upscaled) heightmap **uploads**.
- A server loads the map by placing the file and setting the `levelurl` convar (or dropping into the `maps` folder for procedural naming `Procedural Map.<size>.<seed>.map`).

---

## 2. Map validity requirements (what makes a generated map *playable*)

From the Facepunch wiki Topology/Terrain pages:

- **Player spawns:** a valid spawn area requires overlapping topologies **Tier0 + Oceanside + Beach + Mainland** (typically painted on beaches). Without one, players spawn at (0,0,0) and get kicked for InsideTerrain violations. → our generator always paints valid spawn beaches.
- **Biomes drive gameplay**: ore spawning, collectible/food spawning, tree models, temperature. An all-Arctic map has no food/hemp spawns and no valid spawn area. Biomes are Arid / Temperate / Tundra / Arctic / Jungle.
- **Forest topology** requires Forest splat (Temperate/Arid/Tundra) or Snow splat (Arctic) for trees to spawn.
- **Alpha holes** need accompanying prefabs/terrain-trigger volumes or players fall through / die to anticheat — v1 will only use alpha for intentional cave themes paired with the right volumes, or not at all.
- Ocean must be marked with **Ocean/Offshore** topology; rivers with **River/Riverside** (freshwater), lakes with **Lake/Lakeside**; roadside junkpiles need sufficiently wide **Roadside** topology.

### Topology flag list (bit positions 0–30)

`Field, Cliff, Summit, Beachside, Beach, Forest, Forestside, Ocean, Oceanside, Decor, Monument, Road, Roadside, Swamp, River, Riverside, Lake, Lakeside, Offshore, Rail, Railside, Building, Cliffside, Mountain, Clutter, Alt, Tier0, Tier1, Tier2, Mainland, Hilltop`

Key gameplay effects (wiki-verified):

| Topology | Effect |
|---|---|
| Field | resource pickups, bushes, scrap-heli spawns |
| Beach / Oceanside / Tier0 / Mainland | **player spawn areas**, driftwood, boats |
| Forest / Forestside | trees, mushrooms, berries |
| Cliffside / Decor / Clutter | **ore node spawns**, decorative rocks |
| Mainland | **where animals roam** + airdrop landings |
| Monument | barrels & food crates |
| Road / Rail / Building / Cliff | block spawns & building |
| Swamp | swamp trees + sulfur pickups |
| River / Lake | drinkable water |
| Tier0/1/2 | map progression zones (crate quality) |

---

## 3. Spawn overlays (ore / animal / player views)

Rust servers spawn resources **dynamically** via *spawn populations* that filter on splat + biome + topology. So a `.map` does not contain ore/animal positions — but the **spawnable regions are fully determined by our generated layers**, which means we can render accurate overlays:

- **Ore nodes:** areas with Cliffside/Decor/Clutter topology, Rock/Gravel-adjacent splats, excluding Road/Building/Monument/Cliff; biome tints the ore mix (sulfur bias in Arid, metal/stone everywhere, more nodes in Arctic/Tundra).
- **Animals:** Mainland topology minus blocked topologies; species weighting by biome (bears in forests, wolves in tundra/arctic, boars/deer temperate, scientists near roads).
- **Player spawns:** the computed Tier0∩Beach∩Oceanside∩Mainland mask — we both *render* it and *validate* it (fail generation if the mask is too small).
- Optionally scatter deterministic "preview spawn points" within those masks (seeded) to visualize expected density.

---

## 4. Preview rendering (2D + 3D), and "how RustEdit does it"

- **RustEdit is closed-source.** Its viewport is a live Unity render — not reproducible 1:1 outside Unity. However, the **de-facto standard map preview** (used by the game itself for the in-game map, by RustMaps.com, and replicated by the open-source `Rust Map API` plugin) is Facepunch's `MapImageRenderer` algorithm, which draws the map **purely from the heightmap + splat + water data** — exactly what we generate. This is the correct "1:1" target and is what server owners expect a preview to look like.
- Algorithm (replicated from the game / Rust Map API, constants public):
  1. For each pixel sample height, water level and the 8 splat weights.
  2. Start from base green `StartColor (0.3243, 0.3971, 0.1956)`, blend per-splat colors (sand, rock, gravel, dirt, forest, snow…).
  3. Apply sun shading: normal from heightmap gradient, `SunDirection = normalize(0.95, 2.87, 2.37)`, `SunPower 0.5`, `Brightness 1.0`, `Contrast 0.87`.
  4. Water: blend `WaterColor (0.2697, 0.4205, 0.6275)` by depth, `OffShoreColor (0.1663, 0.2593, 0.3491)` for deep ocean.
- **2D view:** the renderer above produces a PNG server-side (also used as the job thumbnail); the web UI overlays grid (A0…Z26-style), monuments, roads/rivers, and the §3 spawn masks as toggleable layers.
- **3D view:** Three.js in the browser — displace a plane mesh with the real 16-bit heightmap texture, drape the rendered 2D image (or per-layer textures) over it, water plane at sea level, orbit/fly camera. This mirrors what RustEdit/Rust 3D Maps show for terrain (minus game prefab meshes, which require game assets we cannot ship).

---

## 5. Procedural generation design

### 5.1 Pipeline (all seeded → fully deterministic per seed+size+options)

1. **Base heightfield** — layered simplex/Perlin fBm + ridged multifractal + domain warping (theme-dependent), normalized to Rust's 0–1000 m scale with sea at 500.
2. **Island/landmass mask** — radial or shaped falloff (theme-dependent: single isle, archipelago, ring, crater…), guaranteeing ocean at map edges (required for Cargo Ship / Oil Rig style play and spawn beaches).
3. **Geomorphology pass** — optional fast thermal + hydraulic erosion (grid-based, a few dozen iterations) for natural valleys; beach flattening band around sea level (gentle 500–505 m slope for spawnability).
4. **Hydrology** — rivers traced downhill from highland sources with carving; lakes from depression filling; swamps on low flat wet areas.
5. **Biome map** — latitude gradient (arctic north → arid south, like vanilla) warped by noise + altitude (mountain → tundra/arctic), theme overrides (moon/mars = single biome).
6. **Splat map** — rules on slope/height/biome/moisture: beaches→Sand, steep→Rock, mid-slope→Dirt/Gravel, flats→Grass, forest patches→Forest splat, Arctic→Snow; roads→Gravel.
7. **Topology map** — computed from all of the above per §2/§3 rules (Beach/Oceanside bands, Forest patches, Cliff from slope, Ocean/Offshore from depth, Mainland on the main landmass, Tier0/1/2 zoning, Lake/River/Swamp, Field, Decor/Clutter/Cliffside scatter masks).
8. **Roads & rails** *(phase 2+)* — cost-field pathfinding (slope-penalized A*) between POIs, written as `PathData` splines + splat/topology stamping.
9. **Prefab placement** *(phase 2+)* — monuments from the curated prefab table with spacing/terrain-flatness constraints + terrain stamping; decor prefab scatter.
10. **Validation** — spawn-mask area check, biome coverage check, min land %, connectivity check; auto-retry with jittered sub-seed on failure.

### 5.2 Themes (each = parameter preset + optional custom passes)

| Theme | Approach |
|---|---|
| Classic procedural | vanilla-like: fBm island, latitude biomes, rivers, forests |
| Circular isle | radial falloff disc, ring beach, central highland |
| Volcano | central cone (ridged noise), caldera crater, lava-like rock/gravel splat, ash (Arid/rock) ring |
| Archipelago / Naval | many small islands, large ocean %, heavy Oceanside/Offshore |
| Canyonlands | ridged noise + plateau terracing, carved river canyons |
| Moon | craters (stamped bowl + rim), gray rock/gravel splat, single biome, no water (water level dropped), no forests |
| Mars | red-ish via Arid biome + dirt/rock splat, craters + dune noise |
| Underground | flat surface + alpha-hole cave network (phase 3 — needs terrain-trigger volumes to be anticheat-safe) |
| Flatlands / Builder | near-flat grass map with spawn beaches |
| Custom upload | user heightmap (16/8-bit PNG/RAW) → steps 4–10 applied on top |

### 5.3 Options & blacklists

- Core: size (1000–6000), seed (0–2147483647 or "random"), theme, land %, mountain scale, river/lake density, beach width.
- Biome blacklist/weights (e.g. "no Arctic"), with validity guard (§2).
- Prefab/monument blacklist + per-category toggles (phase 2).
- Topology toggles (e.g. disable swamps), water level override, erosion on/off.
- Everything captured in a JSON "recipe" stored with the job → reproducible & shareable; example maps are just bundled recipes.

---

## 6. Application architecture

```
┌────────────────────────── Docker (compose) ──────────────────────────┐
│  web (frontend)      React + TypeScript + Three.js + deck-style 2D   │
│                      canvas overlays; talks REST/WS to API           │
│  api (FastAPI)       /jobs CRUD, /maps download, /presets, /upload,  │
│                      WS progress channel                             │
│  worker (Python)     generation pipeline (NumPy, vectorized),        │
│                      .map codec, preview renderer (Pillow/NumPy)     │
│  queue/store         job queue + artifact store (see open question)  │
└──────────────────────────────────────────────────────────────────────┘
```

- **`rustmap` codec module** (pure Python): LZ4-legacy stream codec (on `lz4.block`) + protobuf (WorldData) + layer pack/unpack. **Golden tests:** round-trip real `.map` files byte-identically (decode→encode) and open outputs in RustEdit/a test server.
- **Job queue (req. #9):** jobs = recipe JSON; states queued→running→done/failed with progress %, concurrency-limited workers (generation for size 6000 ≈ 4097² heightmap ≈ 33 MB int16 + 2048² × 8 splat ≈ 33 MB — comfortably in-RAM with NumPy, est. 10–60 s/job).
- **Artifacts per job:** `.map`, 16-bit RAW + PNG heightmap, preview PNG, layer PNGs (biome/splat/topology/spawn masks), recipe JSON.
- **Performance target:** size-4000 classic map in < 30 s on 2 vCPU; previews < 3 s.

### Phased delivery

| Phase | Deliverable |
|---|---|
| **P0** | Repo scaffold, Docker, `.map` codec w/ golden round-trip tests, flat-map smoke test loads in RustEdit |
| **P1** | Classic-procedural pipeline (height/biome/splat/topology/water, spawn-valid beaches), 2D preview (Facepunch-style render + overlays), heightmap upload/export, example map gallery, job queue UI |
| **P2** | 3D Three.js viewer; themes (isle, volcano, moon, mars, naval, canyon, flat); spawn overlay views (ore/animal/player); biome/topology blacklist options |
| **P3** | Roads/rivers as PathData; monument/prefab placement + prefab blacklist; underground theme; RustEdit extra-data niceties |

### Risks & mitigations

1. **Game format drift** (e.g. new biome channel, version bump) → version-aware codec, golden tests against fresh maps, emit both 4- and 5-channel biome as configured.
2. **Prefab IDs unobtainable programmatically** → curated embedded table; monuments phased to P3; terrain-only maps are fully RustEdit-loadable regardless.
3. **"1:1 RustEdit preview" ambiguity** → we target the official in-game/RustMaps `MapImageRenderer` algorithm (see open question).
4. **Anticheat/terrain violations on exotic themes** (underground) → gated to P3 with required volume prefabs.
5. **LZ4-legacy incompatibility** → format implemented from K4os source + byte-level golden tests; fallback option: a tiny .NET sidecar using the real libraries.

---

## 7. Open questions (need your input)

1. **Stack:** Python/FastAPI + NumPy backend with React/Three.js frontend (recommended: best procedural-gen ergonomics) — or a C#/.NET backend to reuse Facepunch's own SDK libraries verbatim?
2. **Monuments in v1?** Terrain-complete maps (finished in RustEdit) first, with monuments in a later phase — or are auto-placed monuments a launch requirement?
3. **Preview:** is the official in-game `MapImageRenderer` look (what RustMaps and the game use) acceptable as the "1:1" 2D target, given RustEdit is closed-source Unity?
4. **Queue infra:** single-container simplicity (SQLite + in-process worker pool) vs. Redis-backed multi-container compose (scales to multiple workers/machines)?
