import numpy as np
import math
import heapq
import rasterio
from rasterio.windows import Window
from rasterio.enums import Resampling
import matplotlib.pyplot as plt

TIF = "data/processed/cropped_dem.tif"


# ---- Choose the area (in 1 m pixels) ----
COL_OFF, ROW_OFF = 0, 0          # top-left corner of the area
WIDTH, HEIGHT = 32980, 57440     # size (gets clipped to the file automatically)

TARGET = 800                     
MAX_SLOPE = 25                   # degrees; steeper = impassable

# ---- Load DEM ----
with rasterio.open(TIF) as src:
    # Clip the window so it never runs past the edge of the file
    WIDTH = min(WIDTH, src.width - COL_OFF)
    HEIGHT = min(HEIGHT, src.height - ROW_OFF)
    if WIDTH <= 0 or HEIGHT <= 0:
        raise ValueError("COL_OFF / ROW_OFF are outside the file")

    SCALE = max(1, max(WIDTH, HEIGHT) // TARGET)
    out_rows, out_cols = HEIGHT // SCALE, WIDTH // SCALE

    dem = src.read(
        1,
        window=Window(COL_OFF, ROW_OFF, WIDTH, HEIGHT),
        out_shape=(out_rows, out_cols),
        resampling=Resampling.average,
        masked=True,
    ).astype(float).filled(np.nan)

    # Exact cell size in metres (x and y)
    pixel_x = src.res[0] * WIDTH / out_cols
    pixel_y = src.res[1] * HEIGHT / out_rows

pixel = (pixel_x + pixel_y) / 2
print("Grid:", dem.shape, "| cell size: %.1f x %.1f m" % (pixel_x, pixel_y),
      "| area: %.1f x %.1f km" % (WIDTH / 1000, HEIGHT / 1000))

# ---- Elevation -> slope -> cost ----
dy, dx = np.gradient(dem, pixel_y, pixel_x)
slope = np.degrees(np.arctan(np.hypot(dx, dy)))

terrain = 1 + slope / 5                # expensive = steeper
terrain[slope > MAX_SLOPE] = np.inf    # impassable = too steep
terrain[np.isnan(terrain)] = np.inf    # impassable = no data
print("Impassable cells: %.1f %%" % (100 * np.isinf(terrain).mean()))

rows, cols = terrain.shape


def nearest_passable(point):
    """Move a point to the closest cell the rover can actually stand on."""
    if not np.isinf(terrain[point]):
        return point
    ok_r, ok_c = np.where(~np.isinf(terrain))
    i = np.argmin((ok_r - point[0]) ** 2 + (ok_c - point[1]) ** 2)
    new = (int(ok_r[i]), int(ok_c[i]))
    print(point, "was impassable -> moved to", new)
    return new


# ---- Click to choose start and goal ----
kx, ky = pixel_x / 1000, pixel_y / 1000
extent = [0, cols * kx, rows * ky, 0]

fig, ax = plt.subplots(figsize=(8, 7))
ax.imshow(dem, cmap="terrain", extent=extent)
ax.imshow(np.where(np.isinf(terrain), 1, np.nan), cmap="Greys", alpha=0.5,
          vmin=0, vmax=1, extent=extent)   # grey = impassable
ax.set_title("Left-click START, then GOAL  (right-click = undo)")
ax.set_xlabel("Distance east (km)")
ax.set_ylabel("Distance south (km)")

pts = plt.ginput(2, timeout=0)   # wait for 2 clicks
plt.close(fig)

if len(pts) < 2:
    raise SystemExit("You need to click two points")


def km_to_cell(x, y):
    """Convert a click (in km) to a grid cell (row, col)."""
    r = min(max(int(y / ky), 0), rows - 1)
    c = min(max(int(x / kx), 0), cols - 1)
    return (r, c)


start = nearest_passable(km_to_cell(*pts[0]))
goal = nearest_passable(km_to_cell(*pts[1]))
print("Start:", start, "| Goal:", goal)
print("Start (km): %.2f, %.2f | Goal (km): %.2f, %.2f" % (*pts[0], *pts[1]))


# Euclidean distance
def heuristic(a, b):
    return math.hypot(b[0] - a[0], 
                      b[1] - a[1])


def astar(terrain, start, goal):
    open_list = [(heuristic(start, goal), 0, start)]
    came_from = {}
    g_score = {start: 0}

    while open_list:
        _, g, current = heapq.heappop(open_list)

        if g > g_score.get(current, math.inf): # old entry, a better route was already found
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
                r, c = row + dr, col + dc
                if r < 0 or r >= rows or c < 0 or c >= cols:
                    continue
                if np.isinf(terrain[r, c]):
                    continue

                step = math.hypot(dr, dc)          # 1 straight, 1.414 diagonal
                new_g = g + terrain[r, c] * step

                if new_g < g_score.get((r, c), math.inf):
                    came_from[(r, c)] = current
                    g_score[(r, c)] = new_g
                    f = new_g + heuristic((r, c), goal)
                    heapq.heappush(open_list, (f, new_g, (r, c)))

    return None


path = astar(terrain, start, goal)

if path:
    length_km = sum(math.hypot((a[0] - b[0]) * pixel_y, (a[1] - b[1]) * pixel_x)
                    for a, b in zip(path, path[1:])) / 1000
    straight_km = math.hypot((goal[0] - start[0]) * pixel_y,
                             (goal[1] - start[1]) * pixel_x) / 1000
    print("Path: %d cells = %.2f km (straight line %.2f km, +%.0f %%)"
          % (len(path), length_km, straight_km, 100 * (length_km / straight_km - 1)))
else:
    print("No path found - try a higher MAX_SLOPE or different start/goal")

# ---- Plot in km ----
kx, ky = pixel_x / 1000, pixel_y / 1000
extent = [0, cols * kx, rows * ky, 0]   # left, right, bottom, top

fig, ax = plt.subplots(figsize=(7, 9))  # fits on screen; change if needed
im = ax.imshow(dem, cmap="terrain", extent=extent)
fig.colorbar(im, ax=ax, label="Elevation (m)", fraction=0.046 * rows / cols, pad=0.04)
ax.imshow(np.where(np.isinf(terrain), 1, np.nan), cmap="Greys", alpha=0.5,
          vmin=0, vmax=1, extent=extent)   # grey = impassable

ax.scatter(start[1] * kx, start[0] * ky, color="green", label="Start", zorder=3)
ax.scatter(goal[1] * kx, goal[0] * ky, color="red", label="Goal", zorder=3)

if path:
    ax.plot([p[1] * kx for p in path], [p[0] * ky for p in path],
            color="blue", linewidth=2, label="A* Path")

ax.set_xlabel("Distance east (km)")
ax.set_ylabel("Distance south (km)")
ax.legend(loc="upper left")
plt.tight_layout()
plt.savefig("astar_path.png", dpi=200, bbox_inches="tight")
plt.show()