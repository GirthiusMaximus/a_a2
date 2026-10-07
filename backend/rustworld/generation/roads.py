"""Road network generation.

Vanilla Rust maps are organised around a big ring road with spurs running
off it to each monument.  We reproduce that shape:

1. lay a ring of waypoints around the middle of the landmass and route
   between them with A* over a terrain-cost grid (slope + water),
2. run a spur from every road-hub monument to the closest point on the ring,
3. smooth the resulting polylines, resample them to even spacing and emit
   them as ``PathData`` so RustEdit / the server can build road meshes,
4. carve a shallow graded corridor into the heightmap and paint
   ``ROAD``/``ROADSIDE`` topology plus gravel splat along it.

If the terrain has no usable ring (tiny islands, naval maps) the ring is
skipped and monuments are linked with a minimum spanning tree instead.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass

import numpy as np

from ..layers import SEA_LEVEL, TERRAIN_HEIGHT, Splat, Topology
from ..worldfile import PathData, VectorData
from .placement import Placement, _block_reduce, _slope_deg_coarse

__all__ = ["RoadNetwork", "build_roads", "carve_roads", "paint_roads", "to_path_data"]

RING_WIDTH = 12.0
SPUR_WIDTH = 9.0
NODE_SPACING_M = 12.0


@dataclass
class Road:
    points: list[tuple[float, float]]    # world (x, z) metres
    width: float
    kind: str                            # "ring" | "spur"
    loop: bool = False


@dataclass
class RoadNetwork:
    roads: list[Road]

    @property
    def total_length_m(self) -> float:
        total = 0.0
        for r in self.roads:
            for a, b in zip(r.points, r.points[1:]):
                total += float(np.hypot(b[0] - a[0], b[1] - a[1]))
        return total


# ---------------------------------------------------------------------------
# cost grid + A*
# ---------------------------------------------------------------------------

def _cost_grid(height01: np.ndarray, water01: np.ndarray, size: int, sea: float,
               res: int) -> tuple[np.ndarray, np.ndarray]:
    h = _block_reduce(height01, res)
    w = _block_reduce(water01, res)
    slope = _block_reduce(_slope_deg_coarse(height01, size), res, how="mean")

    depth_m = np.maximum(w - h, 0.0) * TERRAIN_HEIGHT
    land = h > sea

    cost = 1.0 + (slope / 6.0) ** 2            # steep ground is expensive
    cost += np.clip(slope - 25.0, 0.0, None) * 4.0   # near-cliff: effectively barred
    cost = np.where(depth_m > 0.25, 25.0 + depth_m * 4.0, cost)  # bridges
    return cost.astype(np.float32), land


_NEIGHBOURS = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
               (-1, -1, 1.41421356), (-1, 1, 1.41421356),
               (1, -1, 1.41421356), (1, 1, 1.41421356)]


def _dijkstra_multi(cost: np.ndarray, sources: list[tuple[int, int]],
                    height: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Least-cost distance from a *set* of sources to every cell.

    One pass of this replaces running a separate A* for every monument spur,
    which is where almost all of the road-building time used to go.
    """
    res = cost.shape[0]
    flat_cost = cost.ravel()
    flat_h = height.ravel()
    dist = np.full(res * res, np.inf, dtype=np.float64)
    prev = np.full(res * res, -1, dtype=np.int32)
    done = np.zeros(res * res, dtype=bool)

    heap: list[tuple[float, int]] = []
    for z, x in sources:
        idx = z * res + x
        if dist[idx] > 0.0:
            dist[idx] = 0.0
            heap.append((0.0, idx))
    heapq.heapify(heap)

    while heap:
        d, cur = heapq.heappop(heap)
        if done[cur]:
            continue
        done[cur] = True
        cz, cx = divmod(cur, res)
        hc = flat_h[cur]
        for dz, dx, step in _NEIGHBOURS:
            nz, nx = cz + dz, cx + dx
            if nz < 0 or nz >= res or nx < 0 or nx >= res:
                continue
            nidx = nz * res + nx
            if done[nidx]:
                continue
            climb = abs(float(flat_h[nidx]) - hc) * TERRAIN_HEIGHT
            nd = d + step * flat_cost[nidx] * (1.0 + climb * 0.35)
            if nd < dist[nidx]:
                dist[nidx] = nd
                prev[nidx] = cur
                heapq.heappush(heap, (nd, nidx))
    return dist, prev


def _trace_back(prev: np.ndarray, res: int, start: tuple[int, int]) -> list[tuple[int, int]]:
    """Walk the predecessor chain from a cell back to its Dijkstra source."""
    cur = start[0] * res + start[1]
    out: list[tuple[int, int]] = []
    seen = set()
    while cur != -1 and cur not in seen:
        seen.add(cur)
        out.append(divmod(cur, res))
        cur = int(prev[cur])
    return out


def _astar(cost: np.ndarray, start: tuple[int, int], goal: tuple[int, int],
           height: np.ndarray, weight: float = 1.3) -> list[tuple[int, int]] | None:
    res = cost.shape[0]
    if start == goal:
        return [start]
    flat_cost = cost.ravel()
    flat_h = height.ravel()
    sidx = start[0] * res + start[1]
    gidx = goal[0] * res + goal[1]

    gz, gx = goal
    dist = np.full(res * res, np.inf, dtype=np.float64)
    prev = np.full(res * res, -1, dtype=np.int32)
    done = np.zeros(res * res, dtype=bool)
    dist[sidx] = 0.0
    heap: list[tuple[float, int]] = [(0.0, sidx)]
    cheapest = float(flat_cost.min())

    while heap:
        _, cur = heapq.heappop(heap)
        if done[cur]:
            continue
        done[cur] = True
        if cur == gidx:
            break
        cz, cx = divmod(cur, res)
        base = dist[cur]
        hc = flat_h[cur]
        for dz, dx, step in _NEIGHBOURS:
            nz, nx = cz + dz, cx + dx
            if nz < 0 or nz >= res or nx < 0 or nx >= res:
                continue
            nidx = nz * res + nx
            if done[nidx]:
                continue
            # grade penalty: roads hate climbing
            climb = abs(float(flat_h[nidx]) - hc) * TERRAIN_HEIGHT
            nd = base + step * flat_cost[nidx] * (1.0 + climb * 0.35)
            if nd < dist[nidx]:
                dist[nidx] = nd
                prev[nidx] = cur
                hz = abs(nz - gz)
                hx = abs(nx - gx)
                h_est = (max(hz, hx) + 0.41421356 * min(hz, hx)) * cheapest * weight
                heapq.heappush(heap, (nd + h_est, nidx))

    if not done[gidx]:
        return None
    path = []
    cur = gidx
    while cur != -1:
        path.append(divmod(cur, res))
        cur = int(prev[cur])
    return path[::-1]


# ---------------------------------------------------------------------------
# polyline helpers
# ---------------------------------------------------------------------------

def _to_world(cells: list[tuple[int, int]], res: int, size: int) -> list[tuple[float, float]]:
    return [((x + 0.5) / res * size - size / 2.0,
             (z + 0.5) / res * size - size / 2.0) for z, x in cells]


def _chaikin(points: list[tuple[float, float]], iterations: int = 3,
             closed: bool = False) -> list[tuple[float, float]]:
    pts = points
    for _ in range(iterations):
        if len(pts) < 3:
            return pts
        out: list[tuple[float, float]] = []
        if not closed:
            out.append(pts[0])
        rng = range(len(pts)) if closed else range(len(pts) - 1)
        for i in rng:
            a = pts[i]
            b = pts[(i + 1) % len(pts)]
            out.append((a[0] * 0.75 + b[0] * 0.25, a[1] * 0.75 + b[1] * 0.25))
            out.append((a[0] * 0.25 + b[0] * 0.75, a[1] * 0.25 + b[1] * 0.75))
        if not closed:
            out.append(pts[-1])
        pts = out
    return pts


def _resample(points: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return points
    out = [points[0]]
    carry = 0.0
    for a, b in zip(points, points[1:]):
        seg = float(np.hypot(b[0] - a[0], b[1] - a[1]))
        if seg <= 1e-6:
            continue
        t = spacing - carry
        while t <= seg:
            f = t / seg
            out.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            t += spacing
        carry = (carry + seg) % spacing
    if out[-1] != points[-1]:
        out.append(points[-1])
    return out


def _densify(points: list[tuple[float, float]], values: list[float] | None,
             max_step: float):
    """Insert intermediate samples so stamping leaves no gaps between discs."""
    if len(points) < 2:
        return points, values
    out_p: list[tuple[float, float]] = []
    out_v: list[float] = []
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        seg = float(np.hypot(b[0] - a[0], b[1] - a[1]))
        n = max(int(np.ceil(seg / max_step)), 1)
        for k in range(n):
            f = k / n
            out_p.append((a[0] + (b[0] - a[0]) * f, a[1] + (b[1] - a[1]) * f))
            if values is not None:
                out_v.append(values[i] + (values[i + 1] - values[i]) * f)
    out_p.append(points[-1])
    if values is not None:
        out_v.append(values[-1])
    return out_p, (out_v if values is not None else None)


def _trim_near(points: list[tuple[float, float]], centre: tuple[float, float],
               radius: float, from_start: bool) -> list[tuple[float, float]]:
    """Drop points that fall inside a monument footprint."""
    seq = points if from_start else points[::-1]
    i = 0
    while i < len(seq) - 1 and np.hypot(seq[i][0] - centre[0], seq[i][1] - centre[1]) < radius:
        i += 1
    seq = seq[i:]
    return seq if from_start else seq[::-1]


# ---------------------------------------------------------------------------
# network construction
# ---------------------------------------------------------------------------

def _snap_to_land(cost: np.ndarray, land: np.ndarray, zi: int, xi: int,
                  max_r: int = 24) -> tuple[int, int] | None:
    res = cost.shape[0]
    if land[zi, xi] and cost[zi, xi] < 20.0:
        return zi, xi
    for r in range(1, max_r):
        z0, z1 = max(zi - r, 0), min(zi + r + 1, res)
        x0, x1 = max(xi - r, 0), min(xi + r + 1, res)
        window = np.where(land[z0:z1, x0:x1], cost[z0:z1, x0:x1], np.inf)
        if np.isfinite(window).any():
            k = int(np.argmin(window))
            dz, dx = divmod(k, x1 - x0)
            return z0 + dz, x0 + dx
    return None


def build_roads(
    height01: np.ndarray,
    water01: np.ndarray,
    size: int,
    sea: float,
    placements: list[Placement],
    *,
    seed: int = 0,
    ring: bool = True,
    work_res: int = 192,
) -> RoadNetwork:
    res = int(min(work_res, height01.shape[0]))
    cost, land = _cost_grid(height01, water01, size, sea, res)
    rng = np.random.default_rng((seed * 40503 + 7) & 0xFFFFFFFF)

    def to_cell(x_m: float, z_m: float) -> tuple[int, int]:
        xi = int(np.clip((x_m + size / 2.0) / size * res, 0, res - 1))
        zi = int(np.clip((z_m + size / 2.0) / size * res, 0, res - 1))
        return zi, xi

    hubs = [p for p in placements
            if p.spec.road_hub and p.spec.placement in ("land", "coast")]

    roads: list[Road] = []
    ring_points: list[tuple[float, float]] = []

    # ---- ring road ------------------------------------------------------
    if ring and land.mean() > 0.18:
        n = 11
        radius = size * 0.30
        jitter = rng.uniform(0.72, 1.20, size=n)
        waypoints: list[tuple[int, int]] = []
        for i in range(n):
            ang = 2.0 * np.pi * i / n + float(rng.uniform(-0.17, 0.17))
            x_m = float(np.cos(ang)) * radius * float(jitter[i])
            z_m = float(np.sin(ang)) * radius * float(jitter[i])
            cell = _snap_to_land(cost, land, *to_cell(x_m, z_m))
            if cell is not None:
                waypoints.append(cell)
        # dedupe consecutive duplicates
        waypoints = [c for i, c in enumerate(waypoints) if i == 0 or c != waypoints[i - 1]]
        if len(waypoints) >= 4:
            cells: list[tuple[int, int]] = []
            ok = True
            for a, b in zip(waypoints, waypoints[1:] + waypoints[:1]):
                leg = _astar(cost, a, b, _block_reduce(height01, res))
                if leg is None:
                    ok = False
                    break
                cells.extend(leg[:-1])
            if ok and len(cells) > 12:
                pts = _chaikin(_to_world(cells, res, size), iterations=3, closed=True)
                ring_points = _resample(pts + [pts[0]], NODE_SPACING_M)
                roads.append(Road(ring_points, RING_WIDTH, "ring", loop=True))

    # ---- spurs ----------------------------------------------------------
    h_coarse = _block_reduce(height01, res)
    if ring_points:
        ring_arr = np.asarray(ring_points, dtype=np.float32)
        ring_cells = sorted({to_cell(x, z) for x, z in ring_points})
        _, prev = _dijkstra_multi(cost, ring_cells, h_coarse)
        for p in hubs:
            d = np.hypot(ring_arr[:, 0] - p.x_m, ring_arr[:, 1] - p.z_m)
            if float(d.min()) < p.radius * 1.25:
                continue   # already sits on the ring
            a = _snap_to_land(cost, land, *to_cell(p.x_m, p.z_m))
            if a is None:
                continue
            leg = _trace_back(prev, res, a)
            if len(leg) < 2:
                continue
            pts = _chaikin(_to_world(leg, res, size), iterations=3)
            pts = _trim_near(pts, (p.x_m, p.z_m), p.radius * 0.85, from_start=True)
            if len(pts) < 2:
                continue
            roads.append(Road(_resample(pts, NODE_SPACING_M), SPUR_WIDTH, "spur"))
    else:
        # no ring: minimum spanning tree between hubs
        if len(hubs) >= 2:
            remaining = list(range(1, len(hubs)))
            tree = [0]
            while remaining:
                best = None
                for i in tree:
                    for j in remaining:
                        d = np.hypot(hubs[i].x_m - hubs[j].x_m, hubs[i].z_m - hubs[j].z_m)
                        if best is None or d < best[0]:
                            best = (d, i, j)
                if best is None:
                    break
                _, i, j = best
                remaining.remove(j)
                tree.append(j)
                a = _snap_to_land(cost, land, *to_cell(hubs[i].x_m, hubs[i].z_m))
                b = _snap_to_land(cost, land, *to_cell(hubs[j].x_m, hubs[j].z_m))
                if a is None or b is None:
                    continue
                leg = _astar(cost, a, b, h_coarse)
                if leg is None or len(leg) < 2:
                    continue
                pts = _chaikin(_to_world(leg, res, size), iterations=3)
                pts = _trim_near(pts, (hubs[i].x_m, hubs[i].z_m), hubs[i].radius * 0.85, True)
                pts = _trim_near(pts, (hubs[j].x_m, hubs[j].z_m), hubs[j].radius * 0.85, False)
                if len(pts) < 2:
                    continue
                roads.append(Road(_resample(pts, NODE_SPACING_M), SPUR_WIDTH, "spur"))

    return RoadNetwork(roads)


# ---------------------------------------------------------------------------
# terrain integration
# ---------------------------------------------------------------------------

def _sample_height(height01: np.ndarray, size: int, x_m: float, z_m: float) -> float:
    res = height01.shape[0]
    u = (x_m + size / 2.0) / size * res - 0.5
    v = (z_m + size / 2.0) / size * res - 0.5
    xi = int(np.clip(round(u), 0, res - 1))
    zi = int(np.clip(round(v), 0, res - 1))
    return float(height01[zi, xi])


def _road_profile(height01: np.ndarray, size: int, road: Road,
                  sea: float) -> list[float]:
    """Height (normalised) for each node, smoothed so the grade stays gentle."""
    ys = [max(_sample_height(height01, size, x, z), sea + 0.8 / TERRAIN_HEIGHT)
          for x, z in road.points]
    arr = np.asarray(ys, dtype=np.float32)
    for _ in range(6):
        pad = np.pad(arr, 1, mode="edge")
        arr = (pad[:-2] + arr * 2.0 + pad[2:]) / 4.0
    return [float(v) for v in arr]


def carve_roads(height01: np.ndarray, network: RoadNetwork, size: int,
                sea: float) -> tuple[np.ndarray, list[list[float]]]:
    """Grade a corridor into the heightmap.  Returns (height, per-road y)."""
    profiles: list[list[float]] = []
    if not network.roads:
        return height01, profiles
    res = height01.shape[0]
    h = height01.copy()
    m_per_px = size / res

    for road in network.roads:
        ys = _road_profile(height01, size, road, sea)
        profiles.append(ys)
        half = road.width * 0.5
        outer = half * 2.2
        pts, yy = _densify(road.points, ys, max(half * 0.5, m_per_px))
        for (x_m, z_m), y in zip(pts, yy):
            cx = (x_m + size / 2.0) / m_per_px
            cz = (z_m + size / 2.0) / m_per_px
            rad = outer / m_per_px
            x0, x1 = int(max(cx - rad, 0)), int(min(cx + rad + 1, res))
            z0, z1 = int(max(cz - rad, 0)), int(min(cz + rad + 1, res))
            if x0 >= x1 or z0 >= z1:
                continue
            xs = np.arange(x0, x1) - cx
            zs = np.arange(z0, z1) - cz
            d = np.hypot(xs[None, :], zs[:, None]) * m_per_px
            t = np.clip((d - half) / max(outer - half, 1e-3), 0.0, 1.0)
            blend = 1.0 - (t * t * (3.0 - 2.0 * t))
            patch = h[z0:z1, x0:x1]
            h[z0:z1, x0:x1] = patch * (1.0 - blend) + y * blend

    return np.clip(h, 0.0, 1.0).astype(np.float32), profiles


def paint_roads(splat: np.ndarray, topology: np.ndarray, network: RoadNetwork,
                size: int) -> None:
    """Paint gravel + ROAD/ROADSIDE topology along the network (in place)."""
    if not network.roads:
        return
    res = topology.shape[0]
    m_per_px = size / res
    clear = int(Topology.FOREST | Topology.FORESTSIDE | Topology.DECOR | Topology.CLUTTER)

    road_mask = np.zeros((res, res), dtype=bool)
    side_mask = np.zeros((res, res), dtype=bool)

    for road in network.roads:
        half = road.width * 0.5
        outer = half * 2.4
        pts, _ = _densify(road.points, None, max(half * 0.5, m_per_px))
        for x_m, z_m in pts:
            cx = (x_m + size / 2.0) / m_per_px
            cz = (z_m + size / 2.0) / m_per_px
            rad = outer / m_per_px
            x0, x1 = int(max(cx - rad, 0)), int(min(cx + rad + 1, res))
            z0, z1 = int(max(cz - rad, 0)), int(min(cz + rad + 1, res))
            if x0 >= x1 or z0 >= z1:
                continue
            xs = np.arange(x0, x1) - cx
            zs = np.arange(z0, z1) - cz
            d = np.hypot(xs[None, :], zs[:, None]) * m_per_px
            road_mask[z0:z1, x0:x1] |= d < half
            side_mask[z0:z1, x0:x1] |= d < outer

    side_mask &= ~road_mask
    topology[road_mask] |= int(Topology.ROAD)
    topology[side_mask] |= int(Topology.ROADSIDE)
    topology[road_mask] &= ~clear

    if road_mask.any():
        for ch in range(splat.shape[0]):
            splat[ch][road_mask] *= 0.12
        splat[int(Splat.GRAVEL)][road_mask] += 0.88
        total = splat.sum(axis=0)
        np.divide(splat, np.maximum(total, 1e-6), out=splat)


def to_path_data(network: RoadNetwork, profiles: list[list[float]]) -> list[PathData]:
    """Convert the network into ``.map`` PathData records."""
    out: list[PathData] = []
    for road, ys in zip(network.roads, profiles):
        nodes = [
            VectorData(x, (y - SEA_LEVEL) * TERRAIN_HEIGHT, z)
            for (x, z), y in zip(road.points, ys)
        ]
        if len(nodes) < 2:
            continue
        out.append(PathData(
            name="Road",
            spline=True,
            start=not road.loop,
            end=not road.loop,
            width=road.width,
            inner_padding=1.0,
            outer_padding=1.0,
            inner_fade=8.0,
            outer_fade=8.0,
            random_scale=1.0,
            mesh_offset=0.0,
            terrain_offset=0.0,
            splat=1 << int(Splat.GRAVEL),
            topology=int(Topology.ROAD),
            nodes=nodes,
        ))
    return out
