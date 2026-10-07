# Theme design research & shaping rules

Visual research notes driving each theme's height-builder. Reference imagery
was collected into `image-search/` during development (vanilla Rust map renders
from just-wiped.net, NPS cinder-cone aerials, Maldives atoll aerials, Kornati
archipelago aerials, Canyonlands NP aerials, NASA lunar orbital photography,
NASA Valles Marineris mosaics, prairie aerials, fantasy floating-island art).

## Observations → rules

### Classic procedural (reference: vanilla Rust 4500 map renders)
- The landmass **fills the square** (~75–80%), it is *not* a round island —
  ocean is a border moat with small offshore islets.
- Coastline is heavily **lobed**: peninsulas, coves, fjord-like notches.
- Interior is mostly **lowland** with scattered hill clusters; no giant peak.
- Biome gradient runs **diagonally** (seed-dependent tilt), arid → temperate →
  arctic; thin sand edge, narrow shallow shelf.
- Rules: warped square falloff + lobed coast warp, low base relief, patchy
  ridged hill masks, rotated biome latitude, narrow beaches (`beach_scale 0.7`).

### Circular isle (reference: Maldives atolls)
- Atolls have a bright **shallow reef shelf ring** around the island before a
  sharp drop to deep blue; sandbars dot the shelf.
- Rules: compact round island (radius ~0.6), surrounding shallow shelf
  (~3–4 m deep) out to ~0.95 radius with noise sandbars, then deep ocean.
  Wide beaches, central highland.

### Volcano (reference: NPS cinder cones, Canary Islands)
- The cone is **smaller than the island**: a steep central edifice with a
  crisp crater bowl, surrounded by a broad, gently-sloped forested **lava
  apron**; often 1–3 **secondary cinder cones** on the flanks.
- Slopes carry faint **radial gullies**.
- Rules: main cone radius ~0.4 with flat-floored caldera, azimuthal gully
  modulation, low shield apron to the coast, 2 secondary cones, rocky summit.

### Archipelago (reference: Kornati, Japanese archipelago)
- Islands are **elongated and aligned** — drowned parallel ridgelines with
  narrow straits between them.
- Rules: anisotropic (stretched ~1:2.8) domain-warped fBm rotated by a
  seed-random axis, square border falloff.

### Naval (reference: tropical islet/reef fields)
- Scattered **small round islets** of varied size with shallow aprons and
  shoals that never break the surface; vast open water.
- Rules: Worley-cell islets (per-cell random size, some submerged as shoals),
  deep ocean elsewhere.

### Canyonlands (reference: Canyonlands NP aerials)
- A **flat high plateau** incised by branching canyons with **vertical,
  terraced walls**; isolated buttes/mesas stand in the lowlands.
- Rules: raised plateau base, canyon network carved along inverted-ridge noise
  (two scales: main gorges + tributaries), strong terracing of everything
  above sea level, arid-leaning biomes.

### Moon (reference: NASA lunar orbital photos)
- Crater sizes follow a **power law** (many small, few large); big craters
  have **flat floors, raised rims and central peaks**; craters overlap;
  smooth dark **maria** plains contrast with rough highlands.
- Rules: ~90 power-law craters with flat floors + rims, central peaks above a
  size threshold, 1–2 broad shallow maria basins, grey rock/gravel palette,
  no water (dry floors).

### Mars (reference: NASA Valles Marineris mosaics)
- One colossal **linear rift canyon** dominates, with stepped walls and
  chaotic floor; plains carry sparse craters and **dune ripples**.
- Rules: seed-rotated rift line (warped), terraced rift walls, sparse craters,
  directional ripple micro-noise, red dirt/rock palette, dry floors.

### Flatlands (reference: prairie aerials)
- Long-wavelength **rolling swells**, no cliffs; ideal build terrain.
- Rules: 2-octave low-amp noise, generous spawn beaches (unchanged).

### Floating islands (reference: fantasy pillar-island art)
- Steep-walled **rock pillars with lush flat tops** rising out of water/mist;
  varied heights; small low islets between them.
- Rust terrain is a heightfield (no true overhangs), so the faithful playable
  translation is **sheer-sided pillar islands (~45–60° walls) with green
  tops 40–140 m up, rising from deep water**, plus sea-level sandbar islets so
  players have valid spawn beaches.
- Rules: Worley-cell pillar masks with narrow wall transition, per-cell random
  top height, fBm top relief, deep (~70 m) seabed, secondary Worley sandbars;
  erosion & shore flattening disabled to keep walls crisp.
