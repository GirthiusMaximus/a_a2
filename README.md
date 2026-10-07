# Rust World Generator

A web-based procedural map generator for the game **Rust** (Facepunch). Generates
complete, playable `.map` files — heightmap, water, ground splats, biomes,
topology and valid player-spawn beaches — that drop straight into a Rust
dedicated server or open directly in **RustEdit**.

![status](https://img.shields.io/badge/status-alpha-orange)

## Features

- **Themed procedural generation** — classic procedural, circular isle, volcano,
  archipelago, naval, canyonlands, moon, mars, flatlands.
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
- **Blacklists** — exclude biomes (e.g. no Arctic) or features (swamps, rivers,
  forests…) per generation.
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
  heightmap (PNG/RAW) at the shown resolution. Monument/road placement is
  RustEdit's job for now (see roadmap).

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
    generation/         # noise, themes, pipeline
  app/                  # FastAPI + queue + worker tasks
  tests/
frontend/               # React + TypeScript + Three.js UI
docs/RESEARCH.md        # format research & build plan
docker-compose.yml
```

## Roadmap

- **P3:** roads/rivers as `PathData` splines, monument prefab placement with
  curated prefab-ID tables + prefab blacklist, underground/cave theme with
  terrain-trigger volumes, RustEdit extra-data chunks.

## Format notes

See [docs/RESEARCH.md](docs/RESEARCH.md) for the full reverse-engineered `.map`
specification (container header, LZ4-legacy chunking, protobuf schema, layer
encodings, resolutions, coordinate system) and research sources.
