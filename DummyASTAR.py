import numpy as np
import math
import heapq
import rasterio
import matplotlib.pyplot as plt

terrain = np.ones((20, 20))
terrain[5:15, 8:12] = 10        # Expensive terrain
terrain[10:13, 8:12] = np.inf   # Impassable terrain

start = (2, 2)
goal = (17, 17)

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
        neighbours = [(row - 1, col), (row + 1, col), (row, col - 1), (row, col + 1)]

        for neighbour in neighbours:
            r, c = neighbour
            if r < 0 or r >= terrain.shape[0] or c < 0 or c >= terrain.shape[1]:
                continue
            if np.isinf(terrain[r, c]):
                continue

            new_g = g_score[current] + terrain[r, c]

            if neighbour not in g_score or new_g < g_score[neighbour]:
                came_from[neighbour] = current
                g_score[neighbour] = new_g
                f = new_g + heuristic(neighbour, goal)   # heuristic 
                heapq.heappush(open_list, (f, neighbour))

    return None

path = astar(terrain, start, goal)
print(path)

display = np.where(np.isinf(terrain), 20, terrain)
plt.imshow(display, cmap="viridis")
plt.colorbar(label="Terrain cost")
plt.scatter(start[1], start[0], color="green", label="Start")
plt.scatter(goal[1], goal[0], color="red", label="Goal")

if path:
    rows = [p[0] for p in path]
    cols = [p[1] for p in path]
    plt.plot(cols, rows, color="blue", linewidth=2, label="A* Path")

plt.legend()
plt.show()