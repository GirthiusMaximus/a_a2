# Facepunch Procedural Generation — Source Research (Phase 4)

Research conducted 2026-10-07 to answer: *can "Classic Procedural" be a 1:1 recreation of
Facepunch's actual procedural generation?*

**Short answer: partially — and the boundary is sharp and knowable.** Four functions are
compiled into a native library and cannot be recovered. Everything else is readable C# and
*can* be matched exactly. Details below.

---

## 1. Source provenance and recency vetting

The user's requirement was explicit: sources must be *verified recent*, because Facepunch
changes procgen often. Every candidate was date-checked before use.

| Source | Last push | Verdict |
|---|---|---|
| **`publicrust/rust-template`** | **2025-10-13** | ✅ **PRIMARY.** Post-Jungle decompile |
| `kilgoar/kilgoar2024` (RustWorldSDK) | 2025-08-27 | ✅ Secondary cross-check |
| `kilgoar/RustMapperBeta` | 2026-03-14 | ✅ Secondary |
| `CarbonCommunity/Carbon.Documentation` | 2026-09-15 | ✅ Prefab IDs (already used) |
| `Klobiroff/Rust-217Devblog-Source` | 2026-04-12 | ❌ **REJECTED** |
| `Ailtop/RustDocuments` | 2023-11-25 | ⚠️ Stable files only |
| `unet-dev/Decompiled-Assemblies` | 2019 | ❌ Rejected |
| `mlgodzilla/Decompiled-Rust` | 2019 | ❌ Rejected |
| `CodeWithBryan/rust-research` | 2023-02 | ❌ Rejected |
| `MillionthOdin16/RustChangelog` | 2024-08 | ❌ Rejected |

### The recency test that matters

A repo's *GitHub push date is not its content date*. `Klobiroff/Rust-217Devblog-Source` was
pushed 2026-04 and contains the complete `Generate*`/`Place*` component set — it looks ideal.
It is actually a pre-2025 dump. The tell:

```csharp
// Klobiroff — Rust.World/TerrainBiome.cs
public const int COUNT = 4;     // no Jungle  →  predates the Jungle Update
```

```csharp
// publicrust/rust-template — Rust.World_chunk1.cstxt   ✅ current
public enum Enum { Arid = 1, Temperate = 2, Tundra = 4, Arctic = 8, Jungle = 0x10 }
public const int COUNT = 5;
public const int JUNGLE = 16;
```

**Rule adopted:** any Rust decompile is only trusted for procgen if `TerrainBiome.COUNT == 5`
and `Jungle` is present. This check should be repeated on any future source.

---

## 2. Headline finding: the native boundary

`GenerateHeight` is not an algorithm. It is a P/Invoke stub:

```csharp
public class GenerateHeight : ProceduralComponent
{
    [DllImport("RustNative", EntryPoint = "generate_height")]
    public unsafe static extern void Native_GenerateHeight(
        short* map, int res, Vector3 pos, Vector3 size, uint seed,
        float lootAngle,  float lootTier0, float lootTier1, float lootTier2,
        float biomeAngle, float biomeArid, float biomeTemperate,
                          float biomeTundra, float biomeArctic);

    public unsafe override void Process(uint seed)
    {
        Native_GenerateHeight(
            (short*)NativeArrayUnsafeUtility.GetUnsafePtr<short>(TerrainMeta.HeightMap.dst),
            TerrainMeta.HeightMap.res, TerrainMeta.Position, TerrainMeta.Size, seed,
            TerrainMeta.LootAxisAngle,
            World.Config.PercentageTier0, World.Config.PercentageTier1, World.Config.PercentageTier2,
            TerrainMeta.BiomeAxisAngle,
            World.Config.PercentageBiomeArid, World.Config.PercentageBiomeTemperate,
            World.Config.PercentageBiomeTundra, World.Config.PercentageBiomeArctic);
    }
}
```

Exhaustive scan of every `EntryPoint` in the assembly — **exactly four** native functions:

```
generate_height    generate_biome    generate_splat    generate_topology
```

### What this means

| Stage | Where it lives | 1:1 recoverable? |
|---|---|---|
| Height field | `RustNative` (compiled) | ❌ **No** — binary only |
| Biome field | `RustNative` | ❌ No (but *inputs* known) |
| Splat field | `RustNative` | ❌ No (but *inputs* known) |
| Topology field | `RustNative` | ❌ No (but *inputs* known) |
| Seed PRNG | C# | ✅ **Yes — exact** |
| Loot / biome axis | C# | ✅ **Yes — exact** |
| Tier percentages | C# | ✅ **Yes — exact** |
| Monument placement | C# | ✅ **Yes — algorithm exact** |
| Road layout + constants | C# | ✅ **Yes — exact** |
| River layout + constants | C# | ✅ **Yes — exact** |
| Prefab black/whitelist | C# | ✅ **Yes — exact** |

A literal pixel-identical heightmap would require reverse-engineering `RustNative.dll` — a
stripped, optimised native binary that is not in any public repo and would be a
disproportionate effort with no guarantee of success. **Everything structural around it is
exactly recoverable**, and that is a great deal more than we currently implement.

---

## 3. Exactly recoverable mechanics

### 3.1 The PRNG — `SeedRandom` (verified bit-exact in Python)

```csharp
public static uint Xorshift(ref uint x) { x ^= x << 13; x ^= x >> 17; x ^= x << 5; return x; }
public static float Xorshift01(ref uint x) => (float)Xorshift(ref x) * 2.3283064E-10f;

public static int   Range(ref uint s, int min, int max)     => min + (int)(Xorshift(ref s) % (uint)(max - min));
public static float Range(ref uint s, float min, float max) => min + Xorshift01(ref s) * (max - min);
public static int   Sign (ref uint s) => (Xorshift(ref s) % 2 != 0) ? -1 : 1;
public static float Value(ref uint s) => Xorshift01(ref s);
public static Vector2 Value2D(ref uint s) { float a = Value(ref s) * PI * 2f; return new(cos a, sin a); }

public static uint Wanghash(ref uint x)
{ x = x ^ 0x3D ^ (x >> 16); x *= 9u; x ^= x >> 4; x *= 668265261u; x ^= x >> 15; return x; }
```

Reimplemented and validated: loot-axis distribution over 200 000 seeds came out
`{0: 49999, 90: 50001, 180: 50000, 270: 50000}` — uniform, as expected. `Value()` stays in
`[0,1)` across 100 000 seeds. **This gives us seed-identical derived structure.**

### 3.2 Loot axis and biome axis — derived from the seed

```csharp
uint seed = World.Seed;
int num  = SeedRandom.Range(ref seed, 0, 4) * 90;   // 0 | 90 | 180 | 270
int num2 = SeedRandom.Range(ref seed, -45, 46);     // jitter -45..+45
int num3 = SeedRandom.Sign(ref seed);               // -1 | +1
LootAxisAngle  = num;
BiomeAxisAngle = num + num2 + num3 * 90;            // ≈ perpendicular to loot axis
```

So a Rust map is organised along **two near-perpendicular axes**: loot tiers band along one,
biomes band along the other. Reproduced locally:

| seed | loot axis | biome axis |
|---|---|---|
| 1337 | 180° | 51° |
| 912156065 | 0° | 77° |
| 1234567 | 180° | 312° |
| 42 | 0° | −63° |
| 2025 | 270° | 153° |

### 3.3 `WorldConfig` — the real defaults

```csharp
public float PercentageTier0 = 0.3f;    // ← the Tier 1 / 2 / 3 areas the user asked about
public float PercentageTier1 = 0.3f;
public float PercentageTier2 = 0.4f;

public float PercentageBiomeArid      = 0.4f;
public float PercentageBiomeTemperate = 0.15f;
public float PercentageBiomeTundra    = 0.15f;
public float PercentageBiomeArctic    = 0.3f;
public float PercentageBiomeJungle    = 0.5f;

public bool MainRoads = true, SideRoads = true, Trails = true, Rivers = true;
public bool Powerlines = true, AboveGroundRails = true, BelowGroundRails = true;
public bool UnderwaterLabs = true;

public List<string> PrefabBlacklist, PrefabWhitelist;   // substring match via name.Contains()
```

Both tier and biome percentage sets are **normalised to sum to 1** on load; if the tier sum is
0 the fallback is `Tier1 = 100%`. Note `PercentageBiomeJungle` is *excluded* from the
normalisation group — Jungle is layered differently from the original four.

This also validates the v1 "blacklist prefabs" feature: Facepunch's own semantics are
`name.Contains(item)` substring matching, whitelist overriding when non-empty.

### 3.4 Tiers are real topology bits, and monuments are tier-gated

```csharp
// TerrainTopology.Enum
Tier0 = 0x4000000,   // 1 << 26   = 67108864
Tier1 = 0x8000000,   // 1 << 27   = 134217728
Tier2 = 0x10000000,  // 1 << 28   = 268435456

public enum MonumentTier { Tier0 = 1, Tier1 = 2, Tier2 = 4 }

public class MonumentInfo : LandmarkInfo
{
    public MonumentType Type = MonumentType.Building;
    [InspectorFlags] public MonumentTier Tier = (MonumentTier)(-1);  // -1 = any tier
    public int MinWorldSize;
    public Bounds Bounds;
    public bool IsSafeZone;
    public bool CheckPlacement(...);   // samples topology at the 4 OBB corners
}

public enum MonumentType
{ Cave, Airport, Building, Town, Radtown, Lighthouse, WaterWell, Roadside, Mountain, Lake, Oasis, Canyon }
```

**This is the complete tier story**, and it closes the user's request:

1. Loot axis picked from seed (one of four cardinals).
2. Map divided perpendicular to it into bands of **30 % / 30 % / 40 %** → Tier0 / Tier1 / Tier2.
3. Those bands are written into the topology mask as bits 26/27/28.
4. Each monument declares which tiers it may occupy — this is what keeps Launch Site out of
   the starter region and Outpost out of the deep end.
5. **Player spawns are Tier0** (∩ Beach ∩ Oceanside ∩ Mainland) — consistent with the
   wiki-derived rule already implemented, now with the correct *source* of Tier0.

### 3.5 Monument placement — `PlaceMonuments`

```csharp
public int TargetCount;
public AnimationCurve TargetCountWorldSizeMultiplier = AnimationCurve.Constant(1000f, 6000f, 1f);
public int MinDistanceSameType = 500;      // metres — default
public int MinDistanceDifferentType = 0;
public int MinWorldSize;
public DistanceMode DistanceSameType = DistanceMode.Max;   // push same-type apart
public DistanceMode DistanceDifferentType = Any;
public const int GroupCandidates = 8, IndividualCandidates = 8, Attempts = 10000;

int num5 = Mathf.RoundToInt(TargetCount * TargetCountWorldSizeMultiplier.Evaluate(World.Size));

if (World.Size < MinWorldSize) return;                     // whole group skipped
foreach (prefab in folderPrefabs)                          // ← each prefab tried ONCE per pass
{
    if (World.Size < prefab.Component.MinWorldSize) continue;
    ...
    if (num5 > 0 && list2.Count >= num5) break;            // folder target reached
}
```

Five rules that our current implementation gets wrong:

1. **Each distinct prefab is placed at most once per pass.** The loop iterates over *prefabs*,
   not over slots. This is why a real map has exactly one Launch Site, one Airfield, one
   Powerplant — and why "2 Harbors" means `harbor_1` + `harbor_2`, two different prefabs, not
   one prefab twice.
2. **`MinDistanceSameType = 500 m`** between monuments from the same folder.
3. **Per-folder `TargetCount`**, scaled by an `AnimationCurve` over world size 1000→6000.
4. **Per-prefab `MinWorldSize`** gating, *plus* per-group `MinWorldSize`.
5. **8 whole-layout candidates × 8 per-monument candidates**, scoring by
   `±distance² ` depending on `DistanceMode`, keeping the highest-scoring complete layout.
   We currently do a single greedy pass.

Roadside monuments are a **separate component**, `PlaceMonumentsRoadside`, with
`RoadMode { SideRoadOrRingRoad, SideRoad, RingRoad, SideRoadOrDesireTrail, DesireTrail }`.
That is why warehouses / gas stations / supermarkets reliably appear in threes *along roads* —
they are not scattered by the generic placer at all.

Full component pipeline (50 `ProceduralComponent` subclasses, in dependency order):

```
GenerateHeight → GenerateBiome → GenerateSplat → GenerateTopology
→ PlaceMonuments / PlaceMonument / PlaceMonumentsOffshore
→ GenerateRoadLayout / GenerateRailLayout / GenerateRiverLayout / GeneratePowerlineLayout
→ GenerateRoadRing / GenerateRailRing / GenerateRailBranching / GenerateRailSiding
→ PlaceMonumentsRoadside / PlaceMonumentsRailside
→ Generate{Road,Rail,River}{Terrain,Meshes,Texture,Topology}
→ GenerateErosion / GenerateErosionSplat / GenerateCliffSplat / GenerateCliffTopology
→ GenerateOceanTopology / GenerateClutterTopology / GenerateDecorTopology
→ PlaceCliffs / PlaceCliffsUniform / PlaceDecor{Uniform,ValueNoise,WhiteNoise}
→ GenerateDungeonGrid / GenerateDungeonBase / ProcessMonumentNodes / ProcessProceduralObjects
```

### 3.6 Road and river constants — exact, and several of ours are wrong

```csharp
public class GenerateRoadLayout : ProceduralComponent
{
    public const float RoadWidth = 10f;      public const float TrailWidth = 4f;
    public const float InnerPadding = 1f;    public const float OuterPadding = 1f;
    public const float InnerFade = 1f;       public const float OuterFade = 8f;
    public const float RandomScale = 0.75f;  public const float TerrainOffset = -0.125f;
    // road:  Topology = 2048, Splat = 128 (gravel), Hierarchy = 1, Spline = true
    // trail: Topology = 2048, Splat = 1   (dirt),   Hierarchy = 2, InnerPadding = 1f * 0.4f
    // name = "Road " + number;  y = Mathf.Max(height, 1f);  Path.Smoothen(16, ...)
}

public class GenerateRiverLayout : ProceduralComponent
{
    public const float Width = 8f;
    public const float InnerPadding = 1f;    public const float OuterPadding = 1f;
    public const float InnerFade = 16f;      public const float OuterFade = 64f;
    public const float RandomScale = 0.75f;
    public const float MeshOffset = -0.5f;   public const float TerrainOffset = -1.5f;

    int num = 3; if (World.Size <= 4000) num = 2;        // river count
    // sources scanned outward from centre in 4 mirrored quadrants, 5 m steps,
    // from centre+250 m to max−750 m; require height > 15 m and normal.y ∈ (0.01, 0.99);
    // reject if within 260 m (sqrt 67600) of an existing river
}
```

| Parameter | Facepunch | Ours today | Action |
|---|---|---|---|
| Road width | **10** | 12 ring / 9 spur | fix |
| Inner fade | **1** | 8 | fix |
| Outer fade | 8 | 8 | ok |
| Random scale | **0.75** | 1 | fix |
| Terrain offset | **−0.125** | — | add |
| Path name | **`"Road N"`** | `"Road"` | fix |
| Trails | **width 4, splat dirt, hierarchy 2** | absent | add |
| River count | **2 (≤4000) / 3** | density-driven | fix |
| River width / fades | **8 / 16 / 64** | ad-hoc | fix |

---

## 4. Real monument counts (empirical — code can't tell us)

`TargetCount` values live in Unity **scene assets**, not in the assembly, so they were
sourced empirically from map databases.

RustMaps.com, procedural 4500:

| Class | Count |
|---|---|
| Large monuments | **22** |
| Small monuments | **18** |
| Tiny monuments | **110** |
| Caves | 8 |
| Safezones | 6 |

Just-Wiped "main monument" counts: **14–15 @ 3500**, **15 @ 4000**, **16–19 @ 4500**,
**17 @ 5000**. Typical 4500 composition is one each of Airfield, Arctic Research Base, Bandit
Town, Compound, Excavator, Junkyard, Launch Site, Military Tunnel, Nuclear Missile Silo,
Powerplant, Satellite Dish, Sphere Tank, Trainyard, Underwater Lab, Water Treatment Plant —
**plus** Harbor ×2, Oil Rig ×2, Fishing Village ×3, Warehouse ×3, Gas Station ×3,
Supermarket ×3, Quarry ×3, Swamp ×3, Lighthouse ×2, Water Well 3–7, caves 7–10.

Counts famously plateau above 4000 — an 8000 map carries roughly the same monument set as a
4000 one, just spread further apart.

### Gap vs. our generator

| Size | Ours now | Real (large + small) |
|---|---|---|
| 3000 | 39 | ~25 |
| 3500 | 46 | ~30 |
| 4000 | 55 | ~38 |
| 4500 (density 2) | 67 | ~40 |

We are **1.5–2× over** on the monument classes RustEdit displays as markers, and the
composition is wrong (duplicates of things that should be unique, no roadside placement, no
tier gating).

---

## 5. Why our terrain is too flat

The user is right, and the cause is now identifiable. `Native_GenerateHeight` receives the
tier and biome parameters, meaning **Facepunch's height field is tier- and biome-aware**: the
terrain character changes across the map (arid flats vs. arctic mountains), and relief is
allocated per region rather than globally. Our generator applies one global noise stack and
then normalises, which flattens everything toward the mean and wastes most of the 16-bit range.

Our observed output at size 3000 classic peaks at ~198 m of a 1000 m Y span — under 20 % of
range used, and only ~70 m above sea level after the 0.5 sea offset. Rust terrain routinely
reaches 200 m+ above water with sharp cliff relief.

Fix direction (not a 1:1 port, since the generator is native): region-aware amplitude driven
by the real tier/biome axes, ridged multifractal for mountain cores, restored high-frequency
detail octaves that the current erosion pass is smoothing away, and a height budget that
targets realistic above-sea relief instead of normalising to a fixed quantile.

---

## 6. The `land_ratio` defect (separate, confirmed)

The reported crash — `ValueError: Quantiles must be in the range [0, 1]` at size 6000 /
75 % land — **was fixed at `b7e005a`** and re-verified this session:
`Recipe(seed=912156065, size=6000, theme="classic", land_ratio=0.75, …)` completes, land
80.33 %, max height 197.7 m. The traceback the user pasted is a **stale job record**: it
quotes the post-fix docstring as a source line, so it was recorded against pre-fix code.
*Their Docker image needs rebuilding to clear it.*

But it exposed a genuine bug. The clamp added at `b7e005a` is a band-aid: requesting 75 %
still yields **80.33 %**, because `land_ratio * theme.land_ratio_scale` (1.45 for classic)
overshoots and is then clamped. The requested land ratio should be honoured as an *absolute
target*, with theme scaling applied to terrain character, not to the quantile target.

---

## 7. Proposed Phase 4 plan

**A. Facepunch-exact core** (new `backend/rustworld/facepunch.py`)
- `SeedRandom` — xorshift32, `Range`, `Sign`, `Value`, `Value2D`, `Wanghash`. Bit-exact.
- `loot_axis_angle(seed)`, `biome_axis_angle(seed)` — exact derivation.
- `WorldConfig` — real defaults, real normalisation, `IsPrefabAllowed` substring semantics.

**B. Tier system**
- Tier0/1/2 bands perpendicular to the loot axis at 30/30/40 %.
- Emit topology bits 26/27/28.
- Tier-gate monuments via a new `tier` field on `MonumentSpec`.
- Player spawns from real Tier0 ∩ Beach ∩ Oceanside ∩ Mainland.
- New overlay showing the three tier regions.

**C. Monument realism**
- One placement per prefab per pass (kills duplicates).
- `MinDistanceSameType = 500 m`.
- Per-folder target counts calibrated to the empirical table in §4.
- 8 group candidates × 8 individual candidates with Facepunch's scoring.
- Roadside class placed *along roads* (warehouse / gas station / supermarket ×3).
- Recalibrate `monument_density` so 1.0 = vanilla, not 1.5–2× vanilla.

**D. Terrain relief**
- Region-aware amplitude keyed to the real biome/tier axes.
- Ridged multifractal mountain cores; restore detail octaves post-erosion.
- Target realistic above-sea relief; stop wasting the 16-bit range.

**E. Corrections**
- Road/river constants per §3.6; add trails.
- Fix `land_ratio` to be an absolute target.
- Biome fractions default to the real 40/15/15/30.

---

## 8. Honest statement of the limit

"Classic Procedural = 1:1 with Facepunch" is **achievable for the structure** — same PRNG,
same seed→axis derivation, same tier bands and percentages, same monument placement rules and
distances, same road/river constants, same prefab filtering semantics, same topology/biome/
splat encodings.

It is **not achievable for the raw height field**, because that is compiled native code. Our
heightmap will be Rust-*like* and Rust-*plausible* — correct relief, correct structure,
correct everything around it — but it will not be byte-identical to what the game's
`RustNative` emits for the same seed. No public source makes that possible.
