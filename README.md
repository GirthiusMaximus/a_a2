# Rust World Generator

A web-based procedural map generator for the game **Rust** (Facepunch). Generates
complete, playable `.map` files — heightmap, water, ground splats, biomes,
topology and valid player-spawn beaches — that drop straight into a Rust
dedicated server or open directly in **RustEdit**.

![status](https://img.shields.io/badge/status-alpha-orange)

## Features

- **Themed procedural generation** — classic procedural, circular isle, volcano,
  archipelago, naval, canyonlands, moon, mars, flatlands, floating islands.
- **Monuments & roads** — the vanilla monument set placed on suitable ground
  and linked by a ring road with spurs, written as real `PrefabData` /
  `PathData`. Prefab ids are computed from the asset path, so no lookup
  table is needed.
- **True `.map` export** (WorldSerialization v10, LZ4-legacy + protobuf) +
  16-bit heightmap PNG/RAW export, RustEdit-compatible resolutions
  (513/1025/2049/4097).
- **Heightmap upload** — bring your own 16-bit PNG/RAW terrain; the generator
  paints biomes/splats/topology on top.
- **1:1 official 2D preview** — a NumPy port of the game's own
  `MapImageRenderer` (same algorithm RustMaps uses), plus a **3D viewer**
  (Three.js) displaced by the real heightmap.
- **Spawn overlays** — player spawn areas, ore node regions and animal roam
  regions derived from the generated topology/biome/splat layers.
- **Blacklists** — exclude biomes (e.g. no Arctic), features (swamps, rivers,
  forests…) or individual monuments per generation.
- **Job queue** — Redis/RQ-backed queue with progress reporting; scale workers
  horizontally with Compose replicas.
- **Example map gallery** — one-click curated recipes.

## Run it

```bash
docker compose up --build
# open http://localhost:8080
```

Services: `web` (nginx + React UI) → `api` (FastAPI) → `redis` queue →
`worker` ×2 (generation). Artifacts persist in the `mapdata` volume.

### Dev mode (no Docker)

```bash
# backend (inline worker pool, no Redis needed)
cd backend && pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000

# frontend
cd frontend && npm install && npm run dev   # http://localhost:5173
```

### Tests

```bash
cd backend && python -m pytest tests/ -v
```

Covers: LZ4-legacy stream round-trips, protobuf round-trips, `.map` container
round-trips, RustEdit resolution conventions, per-theme generation validity
(spawn areas, splat/biome normalization, ocean borders), determinism, the
renderer, heightmap IO and the full API job flow.

## Using the output

- **Server:** place the `.map` on any HTTP host and set
  `server.levelurl "https://…/yourmap.map"`, or drop it in the server's `maps/`
  folder. Keep `server.seed`/`server.worldsize` consistent with the file name.
- **RustEdit:** `File → Open` the `.map` directly, or import the 16-bit
  heightmap (PNG/RAW) at the shown resolution. Monuments and roads are
  written into the file as `PrefabData` / `PathData`, so they show up in
  the editor and spawn on a server.

## Repository layout

```
backend/
  rustworld/            # engine: .map codec, layers, noise, generation, render
    lz4legacy.py        # lz4net "legacy" stream codec (K4os-compatible)
    proto.py            # minimal protobuf wire codec
    worldfile.py        # WorldData/.map container
    layers.py           # splat/biome/topology enums + packing
    render.py           # MapImageRenderer port + overlays + spawn masks
    heightmap_io.py     # 16-bit PNG/RAW import/export
    prefabs.py          # prefab id = uint32_le(md5(path)[:4])
    monuments.py        # monument catalogue + placement rules
    generation/         # noise, themes, pipeline, placement, roads
  app/                  # FastAPI + queue + worker tasks
  tests/
frontend/               # React + TypeScript + Three.js UI
docs/RESEARCH.md        # format research & build plan
docs/THEMES.md          # per-theme landform research & shaping rules
docs/MONUMENTS.md       # prefab ids, monument catalogue, placement & roads
docker-compose.yml
```

## Monuments & roads

Maps ship with the vanilla monument set and a ring-road network by default.
Prefab ids are **computed** from the asset path — `uint32_le(md5(path)[:4])`,
the same hash `StringPool.Add` uses — so no lookup table is needed and
nothing has to be re-synced when Rust updates. Monuments are sited on flat,
suitably-elevated ground largest-first, the terrain is levelled under each
pad, and roads are routed with a terrain-cost search (A* for the ring, one
multi-source Dijkstra for every monument spur).

Controls: `monuments`, `monument_density`, `monument_whitelist`,
`monument_blacklist`, `roads`, `ring_road`. `GET /api/monuments` lists the
catalogue; each finished job also produces `overlay_monuments.png` and
`monuments.json`.

Details and limitations: [docs/MONUMENTS.md](docs/MONUMENTS.md).

## Roadmap

- **P4:** rivers as `PathData` splines, rail network and power lines,
  monument yaw aligned to its spur road, real `TerrainPlacement` footprint
  bounds, underground/cave theme with terrain-trigger volumes, RustEdit
  extra-data chunks.

## Format notes

See [docs/RESEARCH.md](docs/RESEARCH.md) for the full reverse-engineered `.map`
specification (container header, LZ4-legacy chunking, protobuf schema, layer
encodings, resolutions, coordinate system) and research sources.
