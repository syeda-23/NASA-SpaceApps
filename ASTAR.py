import numpy as np
import math
import heapq
import rasterio
from rasterio.windows import from_bounds
from rasterio.enums import Resampling
import matplotlib.pyplot as plt

TIF = "data/raw/gale_dem_1m.tif"    
SCALE = 20               # 1 m pixels -> 20 m pixels
MAX_SLOPE = 25           # degrees; steeper = impassable
LEFT, BOTTOM, RIGHT, TOP = 8140000, -289000, 8149000, -270000  # crop (metres)

with rasterio.open(TIF) as src:
    window = from_bounds(LEFT, BOTTOM, RIGHT, TOP, src.transform)
    dem = src.read(
        1,
        window=window,
        out_shape=(int(window.height // SCALE), int(window.width // SCALE)),
        resampling=Resampling.average,
        masked=True,
    ).astype(float).filled(np.nan)
    pixel = src.res[0] * SCALE

dy, dx = np.gradient(dem, pixel)
slope = np.degrees(np.arctan(np.hypot(dx, dy)))

terrain = 1 + slope / 5                # expensive = steeper
terrain[slope > MAX_SLOPE] = np.inf    # impassable = too steep
terrain[np.isnan(terrain)] = np.inf    # impassable = no data

rows, cols = terrain.shape


start = (rows - 50, 50) #Manual start and goal position, adapt to 
goal = (50, cols - 50)

# Euclidean distance
def heuristic(a, b):
    return math.hypot(b[0] - a[0], 
                      b[1] - a[1])

def astar(terrain, start, goal):
    open_list = []
    heapq.heappush(open_list, (0, start))
    came_from = {}
    g_score = {start: 0}

    while open_list:
        _, current = heapq.heappop(open_list)

        if current == goal:
            path = [current]
            while current in came_from:
                current = came_from[current]
                path.append(current)
            return path[::-1]

        row, col = current
        neighbours = [(row + dr, col + dc)
                      for dr in (-1, 0, 1) for dc in (-1, 0, 1)
                      if (dr, dc) != (0, 0)]

        for neighbour in neighbours:
            r, c = neighbour
            if r < 0 or r >= terrain.shape[0] or c < 0 or c >= terrain.shape[1]:
                continue
            if np.isinf(terrain[r, c]):
                continue

            step = math.hypot(r - row, c - col)        # 1 straight, 1.414 diagonal
            new_g = g_score[current] + terrain[r, c] * step

            if neighbour not in g_score or new_g < g_score[neighbour]:
                came_from[neighbour] = current
                g_score[neighbour] = new_g
                f = new_g + heuristic(neighbour, goal)   # heuristic 
                heapq.heappush(open_list, (f, neighbour))

    return None

path = astar(terrain, start, goal)
print(path)

plt.imshow(dem, cmap="terrain")
plt.colorbar(label="Elevation (m)")
plt.imshow(np.where(np.isinf(terrain), 1, np.nan), cmap="Greys", alpha=0.5)  # grey = impassable
plt.scatter(start[1], start[0], color="green", label="Start")
plt.scatter(goal[1], goal[0], color="red", label="Goal")

if path:
    rows = [p[0] for p in path]
    cols = [p[1] for p in path]
    plt.plot(cols, rows, color="blue", linewidth=2, label="A* Path")

plt.legend()
plt.show()