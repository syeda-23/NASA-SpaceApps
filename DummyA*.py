import numpy as np
import math
import matplotlib.pyplot as plt

terrain = np.ones((20, 20))

# Expensive terrain
terrain[5:15, 8:12] = 10

# Impassable terrain
terrain[10:13, 8:12] = np.inf

start = (2, 2)
goal = (17, 17)

plt.imshow(terrain)
plt.scatter(start[1], start[0], color="green", label="Start")
plt.scatter(goal[1], goal[0], color="red", label="Goal")
plt.legend()
plt.show()

# Euclidean distance

def heuristic(a, b):
    return math.hypot(b[0] - a[0], b[1] - a[1])