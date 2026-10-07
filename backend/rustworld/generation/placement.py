"""Monument placement.

Monuments are chosen and positioned on a coarse working grid (one cell is
roughly 8-16 m) so the search stays cheap, then stamped back onto the full
resolution height map.

The approach mirrors what Facepunch's procedural generator does in spirit:
walk the catalogue from the largest monument down, score every candidate
cell for "can a monument of radius r sit here", and greedily take the best
remaining spot.  Big monuments therefore get the good flat ground and the
small roadside pieces fill in around them.

Scoring uses summed-area tables so each candidate test is O(1) regardless
of footprint size.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..facepunch import MIN_DISTANCE_SAME_TYPE, WorldConfig, tier_index
from ..layers import SEA_LEVEL, TERRAIN_HEIGHT, Biome, Splat, Topology
from ..monuments import MONUMENTS, MonumentSpec

__all__ = ["Placement", "place_monuments", "stamp_monuments", "paint_monuments"]

_BIOME_INDEX = {b.name.lower(): int(b) for b in Biome}


@dataclass
class Placement:
    spec: MonumentSpec
    x_m: float          # world X (metres, map centre = 0)
    z_m: float          # world Z
    y_m: float          # world Y (sea level = 0)
    yaw: float          # degrees
    radius: float

    def as_dict(self) -> dict:
        return {
            "key": self.spec.key,
            "name": self.spec.name,
            "category": self.spec.category,
            "x": round(self.x_m, 1),
            "z": round(self.z_m, 1),
            "y": round(self.y_m, 1),
            "yaw": round(self.yaw, 1),
            "radius": round(self.radius, 1),
            "prefab": self.spec.path,
            "prefab_id": self.spec.id,
        }


# ---------------------------------------------------------------------------
# small numeric helpers
# ---------------------------------------------------------------------------

def _block_reduce(a: np.ndarray, out_res: int, how: str = "mean") -> np.ndarray:
    """Reduce a square array to out_res x out_res by block aggregation."""
    res = a.shape[0]
    if res == out_res:
        return a.astype(np.float32)
    if res % out_res == 0:
        f = res // out_res
        v = a.reshape(out_res, f, out_res, f)
        return (v.max(axis=(1, 3)) if how == "max" else v.mean(axis=(1, 3))).astype(np.float32)
    # non-integer ratio: nearest sample
    idx = (np.arange(out_res) * (res / out_res)).astype(np.int32)
    return a[np.ix_(idx, idx)].astype(np.float32)


def _summed_area(a: np.ndarray) -> np.ndarray:
    s = np.zeros((a.shape[0] + 1, a.shape[1] + 1), dtype=np.float64)
    s[1:, 1:] = a.cumsum(axis=0).cumsum(axis=1)
    return s


def _window_mean(sat: np.ndarray, half: int) -> np.ndarray:
    """Mean over a (2*half+1) square window, centred, edge-clamped."""
    res = sat.shape[0] - 1
    idx = np.arange(res)
    lo = np.clip(idx - half, 0, res)
    hi = np.clip(idx + half + 1, 0, res)
    r0, r1 = lo[:, None], hi[:, None]
    c0, c1 = lo[None, :], hi[None, :]
    total = sat[r1, c1] - sat[r0, c1] - sat[r1, c0] + sat[r0, c0]
    count = (hi - lo)[:, None] * (hi - lo)[None, :]
    return (total / np.maximum(count, 1)).astype(np.float32)


def _dilate(m: np.ndarray, conn4: bool) -> np.ndarray:
    out = m.copy()
    out[1:, :] |= m[:-1, :]
    out[:-1, :] |= m[1:, :]
    out[:, 1:] |= m[:, :-1]
    out[:, :-1] |= m[:, 1:]
    if not conn4:
        out[1:, 1:] |= m[:-1, :-1]
        out[1:, :-1] |= m[:-1, 1:]
        out[:-1, 1:] |= m[1:, :-1]
        out[:-1, :-1] |= m[1:, 1:]
    return out


def _distance_cells(mask: np.ndarray, max_d: int = 96) -> np.ndarray:
    """Distance (in cells) to the nearest True cell.

    Alternating 4- and 8-connected dilations give an octagonal distance,
    which tracks euclidean to within a few percent — ample for siting
    heuristics and vastly faster than a per-pixel chamfer sweep.
    """
    if not mask.any():
        return np.full(mask.shape, float(max_d), dtype=np.float32)
    dist = np.where(mask, np.float32(0.0), np.float32(max_d))
    cur = mask
    for i in range(1, max_d + 1):
        nxt = _dilate(cur, conn4=(i % 2 == 1))
        newly = nxt & ~cur
        if not newly.any():
            break
        dist[newly] = np.float32(i)
        cur = nxt
    return dist


def _slope_deg_coarse(h: np.ndarray, size: int) -> np.ndarray:
    res = h.shape[0]
    spacing = size / max(res - 1, 1)
    gz, gx = np.gradient(h.astype(np.float32) * TERRAIN_HEIGHT, spacing)
    return np.degrees(np.arctan(np.hypot(gx, gz))).astype(np.float32)


# ---------------------------------------------------------------------------
# placement
# ---------------------------------------------------------------------------

def _resolve_counts(
    spec: MonumentSpec, land_km2: float, density: float, vanilla: bool = False
) -> int:
    """How many of this monument to place.

    In vanilla mode the count comes from the real composition of a procedural
    map rather than an area formula.  Facepunch's ``PlaceMonuments`` iterates
    over *prefabs* and gives each one at most one position per pass, so a map
    gets exactly one Launch Site and gets its three Fishing Villages from the
    three distinct ``fishing_village_a/b/c`` prefabs -- not from one prefab
    stamped three times.
    """
    if vanilla:
        n = spec.vanilla_count
        if density != 1.0 and n > 1:
            n = int(round(n * density))
        return max(int(n), 1 if spec.vanilla_count > 0 else 0)
    if spec.per_km2 <= 0:
        return 1
    n = int(round(spec.per_km2 * land_km2 * density))
    return int(np.clip(n, 0, spec.max_count))


def place_monuments(
    height01: np.ndarray,
    water01: np.ndarray,
    size: int,
    seed: int,
    sea: float,
    biome_coarse: np.ndarray,
    *,
    enabled: list[str] | None = None,
    density: float = 1.0,
    work_res: int = 256,
    vanilla: bool = False,
) -> list[Placement]:
    """Pick monument positions.  Returns placements in placement order."""
    rng = np.random.default_rng((seed * 2654435761 + 17) & 0xFFFFFFFF)

    wres = int(min(work_res, height01.shape[0]))
    m_per_cell = size / wres

    h = _block_reduce(height01, wres)
    w = _block_reduce(water01, wres)
    slope_full = _slope_deg_coarse(height01, size)
    slope = _block_reduce(slope_full, wres, how="mean")

    land = (h > sea).astype(np.float32)
    water_depth = np.maximum(w - h, 0.0) * TERRAIN_HEIGHT

    # distance fields (in cells)
    dist_to_water = _distance_cells(land < 0.5)
    dist_to_land = _distance_cells(land >= 0.5)

    sat_land = _summed_area(land)
    sat_slope = _summed_area(slope)
    sat_h = _summed_area(h)
    sat_h2 = _summed_area(h * h)

    if biome_coarse.shape[-1] != wres:
        biome_coarse = np.stack([_block_reduce(b, wres) for b in biome_coarse])
    biome_id = np.argmax(biome_coarse, axis=0)

    # Facepunch gates monuments by loot tier (MonumentInfo.Tier); the tiers
    # are bands across the seed-derived loot axis.
    tiers = tier_index(wres, seed, WorldConfig().normalise().tier_percentages)

    _window_cache: dict[int, tuple] = {}
    occupied = np.zeros((wres, wres), dtype=np.float32)   # radius in metres claimed
    same_type: dict[str, np.ndarray] = {}                 # key -> blocked mask
    land_km2 = float(land.mean()) * (size / 1000.0) ** 2

    # candidate coordinate grids
    cz, cx = np.meshgrid(np.arange(wres), np.arange(wres), indexing="ij")
    centre_dist = np.hypot(cx - (wres - 1) / 2.0, cz - (wres - 1) / 2.0) * m_per_cell

    enabled_keys = (
        [k for k in enabled if k in MONUMENTS]
        if enabled is not None
        else [m.key for m in MONUMENTS.values() if m.default_on]
    )
    specs = sorted((MONUMENTS[k] for k in enabled_keys), key=lambda m: -m.place_priority)

    placements: list[Placement] = []
    for spec in specs:
        if size < spec.min_map_size:
            continue
        want = _resolve_counts(spec, land_km2, density, vanilla)
        if want <= 0:
            continue

        half = max(int(round(spec.radius / m_per_cell)), 1)
        if half not in _window_cache:
            hm = _window_mean(sat_h, half)
            hv = np.maximum(_window_mean(sat_h2, half) - hm * hm, 0.0)
            _window_cache[half] = (
                _window_mean(sat_land, half),
                _window_mean(sat_slope, half),
                hm,
                np.sqrt(hv) * TERRAIN_HEIGHT,
            )
        land_frac, slope_mean, h_mean, relief_m = _window_cache[half]

        margin = spec.radius * 1.15 + (160.0 if spec.placement == 'offshore' else 40.0)
        ok = centre_dist < (size / 2.0 - margin)
        ok &= slope_mean < spec.max_slope
        ok &= relief_m < max(spec.radius * 0.30, 10.0)

        if spec.placement == "offshore":
            ok &= (water_depth > 12.0) & (land_frac < 0.02)
            ok &= dist_to_land * m_per_cell > spec.radius * 1.4
            ok &= dist_to_land * m_per_cell < max(size * 0.22, spec.radius * 4)
        elif spec.placement == "coast":
            ok &= land_frac > 0.55
            shore = dist_to_water * m_per_cell
            ok &= (shore > spec.radius * 0.35) & (shore < spec.radius * 1.5)
        else:
            ok &= land_frac > 0.985
            ok &= dist_to_water * m_per_cell > spec.radius * 1.05

        if vanilla and len(spec.tiers) < 3:
            tier_ok = np.zeros_like(ok)
            for t in spec.tiers:
                tier_ok |= tiers == t
            # don't strand a monument that has nowhere legal to go
            if (ok & tier_ok).any():
                ok &= tier_ok

        if spec.biomes:
            want_ids = [_BIOME_INDEX[b] for b in spec.biomes if b in _BIOME_INDEX]
            if want_ids:
                bm = np.zeros_like(ok)
                for bid in want_ids:
                    bm |= biome_id == bid
                ok &= bm

        if not ok.any():
            continue

        # score: prefer flat, low relief, and (for land) a little inland
        score = -slope_mean / max(spec.max_slope, 1e-3) - relief_m / 40.0
        if spec.placement == "land":
            score += np.clip(dist_to_water * m_per_cell / max(size * 0.12, 1.0), 0, 1) * 0.35
            # The shoreline shelf is the flattest ground on most themes, so a
            # pure flatness score parks every monument on the beach.  Reward
            # genuine inland elevation instead, and taper off in the peaks.
            elev_m = (h_mean - SEA_LEVEL) * TERRAIN_HEIGHT
            score += np.clip((elev_m - 4.0) / 22.0, 0.0, 1.0) * 0.55
            score -= np.clip((elev_m - 110.0) / 90.0, 0.0, 1.0) * 0.70
        score += rng.random((wres, wres)).astype(np.float32) * 0.55   # seeded variety

        blocked = same_type.setdefault(spec.key, np.zeros((wres, wres), dtype=bool))
        for _ in range(want):
            free = ok & (occupied <= 0.0) & ~blocked
            if not free.any():
                break
            masked = np.where(free, score, -np.inf)
            flat = int(np.argmax(masked))
            zi, xi = divmod(flat, wres)

            x_m = (xi + 0.5) / wres * size - size / 2.0
            z_m = (zi + 0.5) / wres * size - size / 2.0

            if spec.placement == "offshore":
                y_m = 0.0
            else:
                base = float(h_mean[zi, xi])
                if spec.placement == "coast":
                    base = max(base, sea + 2.5 / TERRAIN_HEIGHT)
                y_m = (base - SEA_LEVEL) * TERRAIN_HEIGHT

            yaw = _pick_yaw(spec, zi, xi, dist_to_water, rng)

            placements.append(Placement(spec, x_m, z_m, y_m, yaw, spec.radius))

            # claim the ground: this monument plus a spacing ring
            keep = spec.radius * 1.5 + 45.0
            rr = np.hypot((cx - xi) * m_per_cell, (cz - zi) * m_per_cell)
            occupied = np.maximum(occupied, (rr < keep).astype(np.float32))
            # PlaceMonuments.MinDistanceSameType, serialized default 500 m
            blocked |= rr < max(MIN_DISTANCE_SAME_TYPE, keep)

    return placements


def _pick_yaw(spec: MonumentSpec, zi: int, xi: int, dist_to_water: np.ndarray,
              rng: np.random.Generator) -> float:
    """Coastal monuments face the sea; everything else gets a seeded angle."""
    if spec.placement != "coast":
        return float(rng.integers(0, 24)) * 15.0
    res = dist_to_water.shape[0]
    z0, z1 = max(zi - 1, 0), min(zi + 1, res - 1)
    x0, x1 = max(xi - 1, 0), min(xi + 1, res - 1)
    # gradient points away from water; we want to look down it
    gx = float(dist_to_water[zi, x1] - dist_to_water[zi, x0])
    gz = float(dist_to_water[z1, xi] - dist_to_water[z0, xi])
    if abs(gx) < 1e-6 and abs(gz) < 1e-6:
        return float(rng.integers(0, 24)) * 15.0
    yaw = np.degrees(np.arctan2(-gx, -gz))
    return float(yaw % 360.0)


# ---------------------------------------------------------------------------
# terrain stamping
# ---------------------------------------------------------------------------

def stamp_monuments(
    height01: np.ndarray,
    placements: list[Placement],
    size: int,
    sea: float,
) -> np.ndarray:
    """Level the terrain under each monument with a smooth apron.

    Monument prefabs carry their own ``TerrainPlacement`` stamp that the game
    re-applies on spawn, but the saved heightmap still needs to be flat or the
    monument sits in a crater / on a spike in the editor and in the preview.
    """
    if not placements:
        return height01
    res = height01.shape[0]
    h = height01.copy()
    m_per_px = size / res

    for p in placements:
        if p.spec.flatten <= 0.0:
            continue
        r_in = p.radius * 0.78
        r_out = p.radius * 1.18
        cx = (p.x_m + size / 2.0) / m_per_px
        cz = (p.z_m + size / 2.0) / m_per_px
        rad = r_out / m_per_px
        x0, x1 = int(max(cx - rad, 0)), int(min(cx + rad + 2, res))
        z0, z1 = int(max(cz - rad, 0)), int(min(cz + rad + 2, res))
        if x0 >= x1 or z0 >= z1:
            continue
        xs = (np.arange(x0, x1) - cx) * m_per_px
        zs = (np.arange(z0, z1) - cz) * m_per_px
        d = np.hypot(xs[None, :], zs[:, None])
        t = np.clip((d - r_in) / max(r_out - r_in, 1e-3), 0.0, 1.0)
        blend = (1.0 - (t * t * (3.0 - 2.0 * t))) * p.spec.flatten
        target = p.y_m / TERRAIN_HEIGHT + SEA_LEVEL
        if p.spec.placement == "coast":
            target = max(target, sea + 1.5 / TERRAIN_HEIGHT)
        patch = h[z0:z1, x0:x1]
        h[z0:z1, x0:x1] = patch * (1.0 - blend) + target * blend

    return np.clip(h, 0.0, 1.0).astype(np.float32)


def paint_monuments(
    splat: np.ndarray,
    topology: np.ndarray,
    placements: list[Placement],
    size: int,
) -> None:
    """Mark monument footprints in the splat + topology layers (in place)."""
    if not placements:
        return
    res = topology.shape[0]
    m_per_px = size / res

    clear = int(
        Topology.FOREST | Topology.FORESTSIDE | Topology.FIELD
        | Topology.DECOR | Topology.CLUTTER | Topology.SUMMIT | Topology.HILLTOP
    )
    for p in placements:
        outer = p.radius * 1.12
        cx = (p.x_m + size / 2.0) / m_per_px
        cz = (p.z_m + size / 2.0) / m_per_px
        rad = outer / m_per_px
        x0, x1 = int(max(cx - rad, 0)), int(min(cx + rad + 2, res))
        z0, z1 = int(max(cz - rad, 0)), int(min(cz + rad + 2, res))
        if x0 >= x1 or z0 >= z1:
            continue
        xs = (np.arange(x0, x1) - cx) * m_per_px
        zs = (np.arange(z0, z1) - cz) * m_per_px
        d = np.hypot(xs[None, :], zs[:, None])
        core = d < p.radius
        if not core.any():
            continue
        apron = d < outer

        topo = topology[z0:z1, x0:x1]
        topo[apron] |= int(Topology.MONUMENT)
        topo[core] |= int(Topology.BUILDING)
        topo[apron] &= ~clear

        if p.spec.flatten > 0.0:
            # monuments sit on their own gravel/dirt pad.  Keep it near-binary
            # with a short feather so it reads as a built surface rather than
            # a soft dirt smudge.
            feather = max(p.radius * 0.16, 4.0)
            w = np.clip((p.radius - d) / feather, 0.0, 1.0)[core]
            for ch in range(splat.shape[0]):
                sub = splat[ch][z0:z1, x0:x1]
                sub[core] *= (1.0 - w)
            splat[int(Splat.GRAVEL)][z0:z1, x0:x1][core] += w * 0.75
            splat[int(Splat.DIRT)][z0:z1, x0:x1][core] += w * 0.25

    total = splat.sum(axis=0)
    np.divide(splat, np.maximum(total, 1e-6), out=splat)
