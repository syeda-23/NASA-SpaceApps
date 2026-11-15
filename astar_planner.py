import heapq
import math
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.windows import Window

TIF = Path(__file__).resolve().parent / "data" / "processed" / "cropped_dem.tif"

TARGET = 800
MAX_SLOPE = 25
COL_OFF, ROW_OFF = 0, 0
WIDTH, HEIGHT = 32980, 57440


def load_terrain(max_slope=MAX_SLOPE):
    """Load the DEM and derive a terrain cost grid for the requested slope limit."""
    with rasterio.open(TIF) as src:
        width = min(WIDTH, src.width - COL_OFF)
        height = min(HEIGHT, src.height - ROW_OFF)
        if width <= 0 or height <= 0:
            raise ValueError("COL_OFF / ROW_OFF are outside the DEM")

        scale = max(1, max(width, height) // TARGET)
        out_rows, out_cols = height // scale, width // scale
        dem = src.read(
            1,
            window=Window(COL_OFF, ROW_OFF, width, height),
            out_shape=(out_rows, out_cols),
            resampling=Resampling.average,
            masked=True,
        ).astype(float).filled(np.nan)

        pixel_x = src.res[0] * width / out_cols
        pixel_y = src.res[1] * height / out_rows

    slope_y, slope_x = np.gradient(dem, pixel_y, pixel_x)
    slope = np.degrees(np.arctan(np.hypot(slope_x, slope_y)))
    terrain = 1 + slope / 5
    terrain[slope > max_slope] = np.inf
    terrain[np.isnan(terrain)] = np.inf
    return dem, terrain, pixel_x, pixel_y


def nearest_passable(terrain, point):
    """Return the closest traversable cell to a requested cell."""
    if not (0 <= point[0] < terrain.shape[0] and 0 <= point[1] < terrain.shape[1]):
        raise ValueError(f"Cell {point} is outside terrain grid {terrain.shape}")
    if not np.isinf(terrain[point]):
        return point

    passable_rows, passable_cols = np.where(np.isfinite(terrain))
    if len(passable_rows) == 0:
        raise ValueError("The terrain grid has no passable cells at this slope limit")
    nearest = np.argmin(
        (passable_rows - point[0]) ** 2 + (passable_cols - point[1]) ** 2
    )
    return int(passable_rows[nearest]), int(passable_cols[nearest])


def scale_cell(cell, source_shape, target_shape):
    """Map a cell between grids that cover the same area."""
    return tuple(
        min(target_size - 1, round(index * (target_size - 1) / max(source_size - 1, 1)))
        for index, source_size, target_size in zip(cell, source_shape, target_shape)
    )


def astar(terrain, start, goal):
    """Find a least-cost 8-connected path through a terrain cost grid."""
    rows, cols = terrain.shape
    for cell in (start, goal):
        if not (0 <= cell[0] < rows and 0 <= cell[1] < cols):
            raise ValueError(f"Cell {cell} is outside terrain grid {terrain.shape}")
        if not np.isfinite(terrain[cell]):
            raise ValueError(f"Cell {cell} is impassable")

    def heuristic(a, b):
        return math.hypot(b[0] - a[0], b[1] - a[1])

    open_list = [(heuristic(start, goal), 0, start)]
    came_from = {}
    g_score = {start: 0}

    while open_list:
        _, current_g, current = heapq.heappop(open_list)
        if current_g > g_score.get(current, math.inf):
            continue
        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return path[::-1]

        row, col = current
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                next_row, next_col = row + dr, col + dc
                if not (0 <= next_row < rows and 0 <= next_col < cols):
                    continue
                if not np.isfinite(terrain[next_row, next_col]):
                    continue

                neighbor = (next_row, next_col)
                step = math.hypot(dr, dc)
                new_g = current_g + terrain[neighbor] * step
                if new_g < g_score.get(neighbor, math.inf):
                    came_from[neighbor] = current
                    g_score[neighbor] = new_g
                    score = new_g + heuristic(neighbor, goal)
                    heapq.heappush(open_list, (score, new_g, neighbor))

    return None


def path_length_km(path, pixel_x, pixel_y):
    """Calculate the length of a path using the DEM cell dimensions."""
    return sum(
        math.hypot((a[0] - b[0]) * pixel_y, (a[1] - b[1]) * pixel_x)
        for a, b in zip(path, path[1:])
    ) / 1000


def create_route_figure(dem, terrain, pixel_x, pixel_y, start, goal, path):
    """Build the Matplotlib terrain and route figure for display or saving."""
    rows, cols = dem.shape
    kx, ky = pixel_x / 1000, pixel_y / 1000
    extent = [0, cols * kx, rows * ky, 0]

    fig, ax = plt.subplots(figsize=(7, 9))
    image = ax.imshow(dem, cmap="terrain", extent=extent)
    fig.colorbar(
        image, ax=ax, label="Elevation (m)", fraction=0.046 * rows / cols, pad=0.04
    )
    ax.imshow(
        np.where(np.isinf(terrain), 1, np.nan),
        cmap="Greys",
        alpha=0.5,
        vmin=0,
        vmax=1,
        extent=extent,
    )
    ax.scatter(start[1] * kx, start[0] * ky, color="green", label="Start", zorder=3)
    ax.scatter(goal[1] * kx, goal[0] * ky, color="red", label="Goal", zorder=3)
    if path:
        ax.plot(
            [cell[1] * kx for cell in path],
            [cell[0] * ky for cell in path],
            color="blue",
            linewidth=2,
            label="A* Path",
        )
    ax.set_xlabel("Distance east (km)")
    ax.set_ylabel("Distance south (km)")
    ax.legend(loc="upper left")
    fig.tight_layout()
    return fig
