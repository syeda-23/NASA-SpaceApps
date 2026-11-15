"""
Science-aware A* route planner: library version of Astar2.py.

Nothing runs when this file is imported (no click window, no plt.show, no prints at import).
The Streamlit app calls these in order:

    layers   = load_layers()                              # slow: DEM + geology + obstacles (cache it!)
    terrain  = build_terrain(layers, max_slope, geology_weight, terrain_weight,
                             max_roughness=max_roughness)                         # fast: slider-dependent cost grid
    result   = plan_route(layers, terrain, start_cell, goal_cell)                 # A* + statistics
    fig      = create_route_figure(layers, terrain, result)                       # matplotlib Figure

Cells are (row, col) on the A* grid; row 0 is the NORTH edge. Costs are always >= 1, so the
straight-line heuristic stays admissible and A* returns the true minimum-cost route.
"""
import csv
import heapq
import math
import os
import warnings
from pathlib import Path

import numpy as np
import rasterio
from matplotlib.figure import Figure
from matplotlib.patches import Circle
from rasterio.enums import Resampling
from rasterio.windows import Window
from scipy.ndimage import uniform_filter

ROOT = Path(__file__).resolve().parent
DEFAULT_TIF = ROOT / "data" / "processed" / "cropped_dem.tif"
DEFAULT_GEOLOGY = ROOT / "data" / "processed" / "science_value.npy"
DEFAULT_OBSTACLES = ROOT / "data" / "obstacles.csv"

MAX_ROUGHNESS = 1.0          # cells rougher than this (m) are impassable
ROUGHNESS_WEIGHT = 2.0
HIGH_SCIENCE = 0.8           # "high-value geology" threshold used in the statistics


# ============================================================
# LOADING (slow, do once and cache)
# ============================================================
def load_layers(tif=DEFAULT_TIF, geology_file=DEFAULT_GEOLOGY, obstacles_file=DEFAULT_OBSTACLES,
                target=800, col_off=0, row_off=0, req_width=None, req_height=None):
    """
    Read the DEM and geology layer, downsample both to the same grid (about `target` cells on the
    long side), and derive slope and roughness.  Larger `target` = finer route but much slower A*.
    """
    with rasterio.open(tif) as src:
        # Default = the WHOLE DEM, so the A* grid covers exactly what the map picker shows.
        width = min(req_width or src.width, src.width - col_off)
        height = min(req_height or src.height, src.height - row_off)
        if width <= 0 or height <= 0:
            raise ValueError("col_off/row_off is outside the DEM.")

        scale = max(1, max(width, height) // target)
        usable_w, usable_h = (width // scale) * scale, (height // scale) * scale
        out_cols, out_rows = usable_w // scale, usable_h // scale

        dem = src.read(1, window=Window(col_off, row_off, usable_w, usable_h),
                       out_shape=(out_rows, out_cols), resampling=Resampling.average,
                       masked=True).astype(np.float32).filled(np.nan)

        res_x, res_y = abs(src.res[0]), abs(src.res[1])
        if src.crs is not None and src.crs.is_geographic:          # degrees -> metres
            lat0 = math.radians((src.bounds.top + src.bounds.bottom) / 2)
            res_x, res_y = res_x * 59274.9 * math.cos(lat0), res_y * 59274.9
        pixel_x, pixel_y = res_x * usable_w / out_cols, res_y * usable_h / out_rows

    # ---- geology / science value, cut to the same area and averaged onto the DEM grid ----
    if not os.path.exists(geology_file):
        raise FileNotFoundError(f"Geology file not found: {geology_file}")
    geo_raw = np.load(geology_file, mmap_mode="r")
    if geo_raw.ndim == 3 and geo_raw.shape[0] == 1:
        geo_raw = geo_raw[0]
    if geo_raw.ndim != 2:
        raise ValueError(f"The geology NPY must be 2D. Current shape: {geo_raw.shape}")
    if geo_raw.shape[0] < row_off + usable_h or geo_raw.shape[1] < col_off + usable_w:
        raise ValueError(f"The geology NPY {geo_raw.shape} is smaller than the DEM area "
                         f"{(row_off + usable_h, col_off + usable_w)}.")
    geo_crop = np.array(geo_raw[row_off:row_off + usable_h, col_off:col_off + usable_w], dtype=np.float32)  # copy: the mmap is read-only
    geo_crop[~np.isfinite(geo_crop)] = np.nan
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        geology = np.nanmean(geo_crop.reshape(out_rows, scale, out_cols, scale), axis=(1, 3))
    del geo_crop
    if geology.shape != dem.shape:
        raise ValueError(f"Resampled geology {geology.shape} and DEM {dem.shape} do not align.")

    valid_geology = np.isfinite(geology)
    if not valid_geology.any():
        raise ValueError("The geology NPY contains no valid numbers.")
    if np.nanmin(geology) < 0 or np.nanmax(geology) > 1:            # normalise only if not already 0-1
        lo, hi = np.nanpercentile(geology, 2), np.nanpercentile(geology, 98)
        if hi <= lo:
            raise ValueError("The geology layer does not contain a usable range.")
        geology = np.clip((geology - lo) / (hi - lo), 0, 1)
    else:
        geology = np.clip(geology, 0, 1)

    # ---- slope and roughness ----
    dy, dx = np.gradient(dem, pixel_y, pixel_x)
    slope = np.degrees(np.arctan(np.hypot(dx, dy)))

    # uniform_filter uses a running sum, so a single NaN would contaminate whole rows: fill first.
    nan_dem = np.isnan(dem)
    filled = np.where(nan_dem, np.nanmean(dem), dem).astype(np.float64)
    detrended = filled - uniform_filter(filled, size=5)
    roughness = np.sqrt(uniform_filter(detrended ** 2, size=5))
    roughness[nan_dem] = np.nan

    # ---- fixed obstacles (craters, boulders...) from the CSV, if there is one ----
    blocked = np.zeros(dem.shape, dtype=bool)
    obstacle_cells = []
    for obstacle in read_obstacles(obstacles_file):
        r = obstacle["y_km"] / (pixel_y / 1000)
        c = obstacle["x_km"] / (pixel_x / 1000)
        radius_rows = obstacle["radius_m"] / pixel_y
        radius_cols = obstacle["radius_m"] / pixel_x
        obstacle_cells.append({**obstacle, "row": r, "col": c})
        r0, r1 = max(0, int(r - radius_rows) - 1), min(out_rows, int(r + radius_rows) + 2)
        c0, c1 = max(0, int(c - radius_cols) - 1), min(out_cols, int(c + radius_cols) + 2)
        if r0 >= r1 or c0 >= c1:
            continue
        yy, xx = np.mgrid[r0:r1, c0:c1]
        blocked[r0:r1, c0:c1] |= (
            ((yy - r) / radius_rows) ** 2 + ((xx - c) / radius_cols) ** 2 <= 1
        )

    return dict(dem=dem, slope=slope, roughness=roughness, geology=geology, valid_geology=valid_geology,
                blocked=blocked, pixel_x=pixel_x, pixel_y=pixel_y, scale=scale,
                rows=out_rows, cols=out_cols, obstacles=obstacle_cells)


def read_obstacles(path=DEFAULT_OBSTACLES):
    """Read and validate the obstacle CSV, accepting whitespace around legacy headers."""
    if path is None or not os.path.exists(path):
        return []

    with open(path, newline="", encoding="utf-8-sig") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError(f"Obstacle file has no header: {path}")
        fields = {name.strip() for name in reader.fieldnames if name}
        required = {"x_km", "y_km", "radius_m", "type"}
        missing = required - fields
        if missing:
            raise ValueError(f"Obstacle file is missing columns: {', '.join(sorted(missing))}")

        obstacles = []
        for line, row in enumerate(reader, start=2):
            values = {key.strip(): value for key, value in row.items() if key}
            try:
                obstacle = {
                    "x_km": float(values["x_km"]),
                    "y_km": float(values["y_km"]),
                    "radius_m": float(values["radius_m"]),
                    "type": values["type"].strip(),
                }
            except (KeyError, TypeError, ValueError) as error:
                raise ValueError(f"Invalid obstacle on line {line} of {path}.") from error
            if (not all(math.isfinite(obstacle[key]) for key in ("x_km", "y_km", "radius_m"))
                    or obstacle["x_km"] < 0 or obstacle["y_km"] < 0
                    or obstacle["radius_m"] <= 0 or not obstacle["type"]):
                raise ValueError(f"Invalid obstacle on line {line} of {path}.")
            obstacles.append(obstacle)
    return obstacles


def write_obstacles(obstacles, path=DEFAULT_OBSTACLES):
    """Replace the obstacle CSV with validated records in the planner's expected format."""
    path = Path(path)
    checked = []
    for index, obstacle in enumerate(obstacles, start=1):
        try:
            record = {
                "x_km": float(obstacle["x_km"]),
                "y_km": float(obstacle["y_km"]),
                "radius_m": float(obstacle["radius_m"]),
                "type": str(obstacle["type"]).strip(),
            }
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"Invalid obstacle record {index}.") from error
        if (not all(math.isfinite(record[key]) for key in ("x_km", "y_km", "radius_m"))
                or record["x_km"] < 0 or record["y_km"] < 0
                or record["radius_m"] <= 0 or not record["type"]):
            raise ValueError(f"Invalid obstacle record {index}.")
        checked.append(record)

    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as file:
        writer = csv.DictWriter(file, fieldnames=("x_km", "y_km", "radius_m", "type"))
        writer.writeheader()
        writer.writerows(checked)


# ============================================================
# COST GRID (fast, depends on the sliders)
# ============================================================
def build_terrain(layers, max_slope=20.0, geology_weight=3.0, terrain_weight=1.0,
                  roughness_weight=ROUGHNESS_WEIGHT, max_roughness=MAX_ROUGHNESS):
    """
    cost = 1 + terrain_weight * (slope/5 + roughness_weight*roughness) + geology_weight * (1 - science_value)

      geology_weight  0 = ignore geology, ~3 moderate preference, 5+ strong preference
      terrain_weight  1 = your original terrain cost; 0 = ignore slope/roughness (limits still apply)

    Every term is >= 0 so the cost never drops below 1 (keeps A* optimal). Cells over the slope or
    roughness limit, without data, or inside an obstacle are impassable (np.inf).
    """
    slope, rough, geo = layers["slope"], layers["roughness"], layers["geology"]
    with np.errstate(invalid="ignore"):
        cost = (1 + terrain_weight * (slope / 5 + roughness_weight * rough)
                + geology_weight * (1 - np.where(np.isfinite(geo), geo, 1.0)))
        impassable = ((slope > max_slope) | (rough > max_roughness) | ~np.isfinite(cost)
                      | np.isnan(layers["dem"]) | ~layers["valid_geology"] | layers["blocked"])
    cost[impassable] = np.inf
    return cost


# ============================================================
# CELL HELPERS
# ============================================================
def scale_cell(cell, from_shape, to_shape):
    """Map a (row, col) on one grid to the cell containing the same place on another grid."""
    row = int((cell[0] + 0.5) / from_shape[0] * to_shape[0])
    col = int((cell[1] + 0.5) / from_shape[1] * to_shape[1])
    return min(max(row, 0), to_shape[0] - 1), min(max(col, 0), to_shape[1] - 1)


def to_grid_path(path, from_shape, to_shape, max_points=600):
    """Path in A* cells -> float cells on another grid (for drawing on the picker image)."""
    step = max(1, len(path) // max_points)
    pts = path[::step] + ([path[-1]] if (len(path) - 1) % step else [])
    return [((r + 0.5) / from_shape[0] * to_shape[0] - 0.5, (c + 0.5) / from_shape[1] * to_shape[1] - 0.5)
            for r, c in pts]


def nearest_passable(terrain, point):
    """Move a selected cell to the nearest passable cell if it is impassable."""
    row, col = point
    if np.isfinite(terrain[row, col]):
        return point
    rows, cols = terrain.shape
    radius = 8
    for _ in range(2):                         # second pass makes the search window exact
        while True:
            r0, r1 = max(0, row - radius), min(rows, row + radius + 1)
            c0, c1 = max(0, col - radius), min(cols, col + radius + 1)
            rr, cc = np.nonzero(np.isfinite(terrain[r0:r1, c0:c1]))
            if len(rr):
                break
            if (r0, c0, r1, c1) == (0, 0, rows, cols):
                raise ValueError("The entire terrain is impassable.")
            radius *= 2
        d2 = (rr + r0 - row) ** 2 + (cc + c0 - col) ** 2
        i = int(d2.argmin())
        radius = int(math.ceil(math.sqrt(d2[i]))) + 1
    return int(rr[i] + r0), int(cc[i] + c0)


# ============================================================
# A*
# ============================================================
def astar(terrain, start, goal):
    """8-connected A* over the cost grid. Returns a list of (row, col), or None if unreachable."""
    rows, cols = terrain.shape
    flat = terrain.ravel()
    F = flat.tolist()                                    # plain Python floats: much faster than numpy indexing
    s_idx, g_idx = start[0] * cols + start[1], goal[0] * cols + goal[1]
    INF = math.inf
    if F[s_idx] == INF or F[g_idx] == INF:
        return None
    if s_idx == g_idx:
        return [tuple(start)]

    finite = flat[np.isfinite(flat)]
    cmin = float(finite.min())                           # cheapest possible cell (>= 1) -> tighter, still admissible
    gi, gj = goal
    moves = [(-1, 0, 1.0), (1, 0, 1.0), (0, -1, 1.0), (0, 1, 1.0),
             (-1, -1, math.sqrt(2)), (-1, 1, math.sqrt(2)), (1, -1, math.sqrt(2)), (1, 1, math.sqrt(2))]

    g = [INF] * (rows * cols)
    parent = [-1] * (rows * cols)
    closed = bytearray(rows * cols)
    g[s_idx] = 0.0
    heap = [(cmin * math.hypot(start[0] - gi, start[1] - gj), s_idx)]

    while heap:
        _, u = heapq.heappop(heap)
        if closed[u]:
            continue
        closed[u] = 1
        if u == g_idx:
            path = []
            while u != -1:
                path.append(divmod(u, cols))
                u = parent[u]
            return path[::-1]
        ur, uc = divmod(u, cols)
        fu, gu = F[u], g[u]
        for dr, dc, dist in moves:
            vr, vc = ur + dr, uc + dc
            if vr < 0 or vr >= rows or vc < 0 or vc >= cols:
                continue
            v = vr * cols + vc
            fv = F[v]
            if closed[v] or fv == INF:
                continue
            if dr and dc and (F[(ur + dr) * cols + uc] == INF or F[ur * cols + uc + dc] == INF):
                continue                                  # no cutting corners between blocked cells
            ng = gu + dist * (fu + fv) * 0.5
            if ng < g[v]:
                g[v] = ng
                parent[v] = u
                heapq.heappush(heap, (ng + cmin * math.hypot(vr - gi, vc - gj), v))
    return None


# ============================================================
# STATISTICS & ONE-CALL PLANNER
# ============================================================
def route_stats(path, layers, start, goal):
    p = np.asarray(path)
    r, c = p[:, 0], p[:, 1]
    length_km = float(np.hypot(np.diff(r) * layers["pixel_y"], np.diff(c) * layers["pixel_x"]).sum() / 1000)
    straight_km = math.hypot((goal[0] - start[0]) * layers["pixel_y"],
                             (goal[1] - start[1]) * layers["pixel_x"]) / 1000
    sci = layers["geology"][r, c]
    return dict(
        cells=len(path), length_km=length_km, straight_km=straight_km,
        detour_pct=(100 * (length_km / straight_km - 1)) if straight_km > 0 else 0.0,
        mean_science=float(np.nanmean(sci)), max_science=float(np.nanmax(sci)),
        high_science_pct=float(100 * np.mean(sci >= HIGH_SCIENCE)),
        max_slope=float(np.nanmax(layers["slope"][r, c])),
        elevation=layers["dem"][r, c],
    )


def plan_route(layers, terrain, start, goal):
    """Snap start/goal to passable cells, run A*, return everything the UI needs."""
    s, g = nearest_passable(terrain, tuple(start)), nearest_passable(terrain, tuple(goal))
    path = astar(terrain, s, g)
    return dict(start=s, goal=g, moved_start=s != tuple(start), moved_goal=g != tuple(goal),
                path=path, stats=route_stats(path, layers, s, g) if path else None)


# ============================================================
# FIGURE (returned, never shown here: the caller does st.pyplot)
# ============================================================
def create_route_figure(layers, terrain, result):
    dem, geo = layers["dem"], layers["geology"]
    rows, cols = terrain.shape
    kx, ky = layers["pixel_x"] / 1000, layers["pixel_y"] / 1000
    extent = [0, cols * kx, rows * ky, 0]
    start, goal, path = result["start"], result["goal"], result["path"]

    fig = Figure(figsize=(14, 6.5))
    ax1, ax2 = fig.subplots(1, 2)

    im1 = ax1.imshow(dem, cmap="terrain", extent=extent)
    fig.colorbar(im1, ax=ax1, label="Elevation (m)")
    ax1.imshow(np.where(np.isinf(terrain), 1, np.nan), cmap="Greys", alpha=0.45, vmin=0, vmax=1, extent=extent)
    ax1.set_title("Safe route over DEM")

    im2 = ax2.imshow(geo, cmap="plasma", vmin=0, vmax=1, extent=extent)
    fig.colorbar(im2, ax=ax2, label="Scientific value")
    ax2.imshow(np.where(np.isinf(terrain), 1, np.nan), cmap="Greys", alpha=0.3, vmin=0, vmax=1, extent=extent)
    ax2.set_title("Route through scientifically valuable geology")

    for ax in (ax1, ax2):
        ax.scatter(start[1] * kx, start[0] * ky, color="lime", edgecolors="black", s=60, label="Start", zorder=3)
        ax.scatter(goal[1] * kx, goal[0] * ky, color="red", edgecolors="black", s=60, label="Goal", zorder=3)
        for index, obstacle in enumerate(layers.get("obstacles", [])):
            ax.add_patch(
                Circle(
                    (obstacle["col"] * kx, obstacle["row"] * ky),
                    obstacle["radius_m"] / 1000,
                    fill=False,
                    edgecolor="orangered",
                    linewidth=1.5,
                    label="Obstacle" if index == 0 else None,
                    zorder=3,
                )
            )
        if path:
            ax.plot([q[1] * kx for q in path], [q[0] * ky for q in path], color="cyan", lw=2.5,
                    label="Science-aware A* route")
        ax.set_xlabel("Distance east (km)")
        ax.set_ylabel("Distance south (km)")
        ax.legend(loc="upper left")
    fig.tight_layout()
    return fig