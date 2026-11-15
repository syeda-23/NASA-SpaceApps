import numpy as np
import math
import heapq
import rasterio
from rasterio.windows import Window
from rasterio.enums import Resampling
import matplotlib.pyplot as plt


# ============================================================
# SETTINGS
# ============================================================

TIF = "data/processed/cropped_dem.tif"
GEOLOGY_FILE = "data/processed/science_value.npy"

TARGET = 1600
MAX_SLOPE = 25

# 0 = geology ignored
# 1-3 = moderate geological preference
# 5+ = strong geological preference
GEOLOGY_WEIGHT = 3.0

# Window inside the cropped files
COL_OFF = 0
ROW_OFF = 0

# Your cropped DEM and geology array are 5000 x 5000
REQUESTED_WIDTH = 5000
REQUESTED_HEIGHT = 5000


# ============================================================
# LOAD DEM AND DETERMINE OUTPUT GRID
# ============================================================

with rasterio.open(TIF) as src:

    width = min(REQUESTED_WIDTH, src.width - COL_OFF)
    height = min(REQUESTED_HEIGHT, src.height - ROW_OFF)

    if width <= 0 or height <= 0:
        raise ValueError(
            "COL_OFF or ROW_OFF is outside the DEM."
        )

    # Calculate the downsampling factor
    scale = max(1, max(width, height) // TARGET)

    # Trim dimensions so they divide exactly by scale.
    # This ensures the DEM and NPY layer align exactly.
    usable_width = (width // scale) * scale
    usable_height = (height // scale) * scale

    out_cols = usable_width // scale
    out_rows = usable_height // scale

    window = Window(
        COL_OFF,
        ROW_OFF,
        usable_width,
        usable_height
    )

    dem = src.read(
        1,
        window=window,
        out_shape=(out_rows, out_cols),
        resampling=Resampling.average,
        masked=True
    ).astype(np.float32).filled(np.nan)

    pixel_x = abs(src.res[0]) * usable_width / out_cols
    pixel_y = abs(src.res[1]) * usable_height / out_rows


print("DEM source area:", usable_width, "x", usable_height, "pixels")
print("A* grid:", dem.shape)
print(
    "A* cell size: %.2f x %.2f m"
    % (pixel_x, pixel_y)
)
print(
    "Mapped area: %.3f x %.3f km"
    % (
        usable_width * abs(pixel_x / scale) / 1000,
        usable_height * abs(pixel_y / scale) / 1000
    )
)


# ============================================================
# LOAD GEOLOGY / SCIENCE-VALUE NPY
# ============================================================

geology_raw = np.load(
    GEOLOGY_FILE,
    mmap_mode="r"
)

print("Original geology shape:", geology_raw.shape)
print("Original geology dtype:", geology_raw.dtype)

# Handle a file saved as (1, rows, cols)
if geology_raw.ndim == 3 and geology_raw.shape[0] == 1:
    geology_raw = geology_raw[0]

if geology_raw.ndim != 2:
    raise ValueError(
        "The geology NPY must be a 2D matrix. "
        f"Current shape: {geology_raw.shape}"
    )

required_rows = ROW_OFF + usable_height
required_cols = COL_OFF + usable_width

if (
    geology_raw.shape[0] < required_rows
    or geology_raw.shape[1] < required_cols
):
    raise ValueError(
        "The geology NPY is smaller than the requested DEM area.\n"
        f"Geology shape: {geology_raw.shape}\n"
        f"Required minimum: {(required_rows, required_cols)}"
    )

# Select the same area as the DEM
geology_crop = np.asarray(
    geology_raw[
        ROW_OFF:ROW_OFF + usable_height,
        COL_OFF:COL_OFF + usable_width
    ],
    dtype=np.float32
)

# Change invalid values to NaN
geology_crop[~np.isfinite(geology_crop)] = np.nan

# Downsample to exactly the same grid as the DEM.
#
# Mean is used because geological interest is being treated as
# a continuous scientific-reward layer.
with np.errstate(invalid="ignore"):
    geology = np.nanmean(
        geology_crop.reshape(
            out_rows,
            scale,
            out_cols,
            scale
        ),
        axis=(1, 3)
    )

if geology.shape != dem.shape:
    raise ValueError(
        "The resampled geology and DEM do not align.\n"
        f"DEM: {dem.shape}\n"
        f"Geology: {geology.shape}"
    )

print("Resampled geology shape:", geology.shape)


# ============================================================
# NORMALISE GEOLOGY TO 0-1
# ============================================================

valid_geology = np.isfinite(geology)

if not np.any(valid_geology):
    raise ValueError(
        "The geology NPY contains no valid numbers."
    )

geology_min = np.nanmin(geology)
geology_max = np.nanmax(geology)

print(
    "Raw geology range:",
    geology_min,
    "to",
    geology_max
)

# The image suggests the array is already 0-1.
# Normalise only if it is outside that range.
if geology_min < 0 or geology_max > 1:

    geology_low = np.nanpercentile(geology, 2)
    geology_high = np.nanpercentile(geology, 98)

    if geology_high <= geology_low:
        raise ValueError(
            "The geology layer does not contain a usable range."
        )

    geology_normalised = np.clip(
        (geology - geology_low)
        / (geology_high - geology_low),
        0,
        1
    )

else:
    geology_normalised = np.clip(
        geology,
        0,
        1
    )

print(
    "Normalised geology range:",
    np.nanmin(geology_normalised),
    "to",
    np.nanmax(geology_normalised)
)


# ============================================================
# CALCULATE SLOPE
# ============================================================

dy, dx = np.gradient(
    dem,
    pixel_y,
    pixel_x
)

slope = np.degrees(
    np.arctan(
        np.hypot(dx, dy)
    )
)

print(
    "Slope range: %.2f to %.2f degrees"
    % (
        np.nanmin(slope),
        np.nanmax(slope)
    )
)


# ============================================================
# COMBINE SLOPE AND GEOLOGY INTO TERRAIN COST
# ============================================================

# Flat terrain begins near cost 1.
# Steeper terrain becomes more expensive.
slope_cost = slope / 5

# High scientific value should be cheaper.
#
# geology = 1 -> geology cost = 0
# geology = 0 -> geology cost = GEOLOGY_WEIGHT
geology_cost = (
    GEOLOGY_WEIGHT
    * (1 - geology_normalised)
)

terrain = (
    1
    + slope_cost
    + geology_cost
)

# Hard safety restrictions
terrain[slope > MAX_SLOPE] = np.inf
terrain[np.isnan(dem)] = np.inf
terrain[~valid_geology] = np.inf

rows, cols = terrain.shape

print(
    "Impassable cells: %.1f %%"
    % (
        100
        * np.isinf(terrain).mean()
    )
)


# ============================================================
# FIND NEAREST PASSABLE CELL
# ============================================================

def nearest_passable(point):
    """
    Move a selected point to the nearest passable cell
    if the selected cell is impassable.
    """

    row, col = point

    if not np.isinf(terrain[row, col]):
        return point

    valid_rows, valid_cols = np.where(
        ~np.isinf(terrain)
    )

    if len(valid_rows) == 0:
        raise ValueError(
            "The entire terrain is impassable."
        )

    index = np.argmin(
        (valid_rows - row) ** 2
        + (valid_cols - col) ** 2
    )

    new_point = (
        int(valid_rows[index]),
        int(valid_cols[index])
    )

    print(
        point,
        "was impassable -> moved to",
        new_point
    )

    return new_point


# ============================================================
# CLICK START AND GOAL POINTS
# ============================================================

kx = pixel_x / 1000
ky = pixel_y / 1000

extent = [
    0,
    cols * kx,
    rows * ky,
    0
]

fig, axes = plt.subplots(
    1,
    2,
    figsize=(13, 6)
)

# DEM panel
axes[0].imshow(
    dem,
    cmap="terrain",
    extent=extent
)

axes[0].imshow(
    np.where(
        np.isinf(terrain),
        1,
        np.nan
    ),
    cmap="Greys",
    alpha=0.45,
    vmin=0,
    vmax=1,
    extent=extent
)

axes[0].set_title(
    "Click START, then GOAL"
)

axes[0].set_xlabel(
    "Distance east (km)"
)

axes[0].set_ylabel(
    "Distance south (km)"
)

# Geology panel
geology_image = axes[1].imshow(
    geology_normalised,
    cmap="plasma",
    vmin=0,
    vmax=1,
    extent=extent
)

fig.colorbar(
    geology_image,
    ax=axes[1],
    label="Scientific value"
)

axes[1].set_title(
    "Geological scientific-value layer"
)

axes[1].set_xlabel(
    "Distance east (km)"
)

axes[1].set_ylabel(
    "Distance south (km)"
)

plt.tight_layout()

# Make sure clicks are collected from the DEM panel
plt.sca(axes[0])

points = plt.ginput(
    2,
    timeout=0
)

plt.close(fig)

if len(points) < 2:
    raise SystemExit(
        "You must click a start and goal point."
    )


def km_to_cell(x_km, y_km):
    """
    Convert plot coordinates in km to a grid cell.
    """

    row = int(y_km / ky)
    col = int(x_km / kx)

    row = min(
        max(row, 0),
        rows - 1
    )

    col = min(
        max(col, 0),
        cols - 1
    )

    return row, col


start = nearest_passable(
    km_to_cell(*points[0])
)

goal = nearest_passable(
    km_to_cell(*points[1])
)

print("Start cell:", start)
print("Goal cell:", goal)

print(
    "Start: %.3f km east, %.3f km south"
    % (
        start[1] * kx,
        start[0] * ky
    )
)

print(
    "Goal: %.3f km east, %.3f km south"
    % (
        goal[1] * kx,
        goal[0] * ky
    )
)


# ============================================================
# EUCLIDEAN HEURISTIC
# ============================================================

def heuristic(a, b):
    """
    Estimate remaining distance in grid-cell units.

    The minimum terrain cost is 1, so Euclidean distance
    is an admissible heuristic.
    """

    return math.hypot(
        b[0] - a[0],
        b[1] - a[1]
    )


# ============================================================
# A-STAR
# ============================================================

def astar(terrain, start, goal):

    open_list = [
        (
            heuristic(start, goal),
            0,
            start
        )
    ]

    came_from = {}
    g_score = {
        start: 0
    }

    while open_list:

        _, current_g, current = heapq.heappop(
            open_list
        )

        # Ignore outdated queue entries
        if current_g > g_score.get(
            current,
            math.inf
        ):
            continue

        # Goal found
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

                new_row = row + dr
                new_col = col + dc

                # Stay inside the map
                if (
                    new_row < 0
                    or new_row >= rows
                    or new_col < 0
                    or new_col >= cols
                ):
                    continue

                # Skip impassable cells
                if np.isinf(
                    terrain[new_row, new_col]
                ):
                    continue

                # Prevent diagonal movement through the corner
                # between two blocked cells.
                if dr != 0 and dc != 0:

                    if (
                        np.isinf(
                            terrain[row + dr, col]
                        )
                        or np.isinf(
                            terrain[row, col + dc]
                        )
                    ):
                        continue

                # Straight = 1 cell
                # Diagonal = sqrt(2) cells
                step_distance = math.hypot(
                    dr,
                    dc
                )

                # Average the cost of the current and new cells
                step_cost = (
                    terrain[row, col]
                    + terrain[new_row, new_col]
                ) / 2

                new_g = (
                    current_g
                    + step_distance
                    * step_cost
                )

                neighbour = (
                    new_row,
                    new_col
                )

                if new_g < g_score.get(
                    neighbour,
                    math.inf
                ):

                    came_from[neighbour] = current
                    g_score[neighbour] = new_g

                    f_score = (
                        new_g
                        + heuristic(
                            neighbour,
                            goal
                        )
                    )

                    heapq.heappush(
                        open_list,
                        (
                            f_score,
                            new_g,
                            neighbour
                        )
                    )

    return None


# ============================================================
# RUN A-STAR
# ============================================================

path = astar(
    terrain,
    start,
    goal
)


# ============================================================
# ROUTE STATISTICS
# ============================================================

if path:

    length_km = sum(
        math.hypot(
            (point_a[0] - point_b[0])
            * pixel_y,
            (point_a[1] - point_b[1])
            * pixel_x
        )
        for point_a, point_b
        in zip(path, path[1:])
    ) / 1000

    straight_km = math.hypot(
        (goal[0] - start[0])
        * pixel_y,
        (goal[1] - start[1])
        * pixel_x
    ) / 1000

    geology_on_path = np.array(
        [
            geology_normalised[row, col]
            for row, col in path
        ]
    )

    slope_on_path = np.array(
        [
            slope[row, col]
            for row, col in path
        ]
    )

    mean_science = np.nanmean(
        geology_on_path
    )

    max_science = np.nanmax(
        geology_on_path
    )

    high_science_percentage = (
        np.sum(geology_on_path >= 0.8)
        / len(geology_on_path)
        * 100
    )

    print()
    print("========== ROUTE RESULTS ==========")

    print(
        "Path:",
        len(path),
        "cells"
    )

    print(
        "Route distance:",
        round(length_km, 3),
        "km"
    )

    print(
        "Straight-line distance:",
        round(straight_km, 3),
        "km"
    )

    if straight_km > 0:
        print(
            "Route detour:",
            round(
                100
                * (
                    length_km
                    / straight_km
                    - 1
                ),
                1
            ),
            "%"
        )

    print(
        "Mean scientific value:",
        round(mean_science, 3)
    )

    print(
        "Maximum scientific value:",
        round(max_science, 3)
    )

    print(
        "Route through high-value geology:",
        round(
            high_science_percentage,
            1
        ),
        "%"
    )

    print(
        "Maximum route slope:",
        round(
            np.nanmax(slope_on_path),
            2
        ),
        "degrees"
    )

else:

    print(
        "No path found. Try different points, "
        "increase MAX_SLOPE slightly, or reduce GEOLOGY_WEIGHT."
    )


# ============================================================
# FINAL PLOTS
# ============================================================

fig, axes = plt.subplots(
    1,
    2,
    figsize=(14, 7)
)

# ------------------------------------------------------------
# Plot 1: DEM and route
# ------------------------------------------------------------

dem_image = axes[0].imshow(
    dem,
    cmap="terrain",
    extent=extent
)

fig.colorbar(
    dem_image,
    ax=axes[0],
    label="Elevation (m)"
)

axes[0].imshow(
    np.where(
        np.isinf(terrain),
        1,
        np.nan
    ),
    cmap="Greys",
    alpha=0.45,
    vmin=0,
    vmax=1,
    extent=extent
)

axes[0].scatter(
    start[1] * kx,
    start[0] * ky,
    color="lime",
    edgecolors="black",
    s=60,
    label="Start",
    zorder=3
)

axes[0].scatter(
    goal[1] * kx,
    goal[0] * ky,
    color="red",
    edgecolors="black",
    s=60,
    label="Goal",
    zorder=3
)

if path:

    path_x = [
        point[1] * kx
        for point in path
    ]

    path_y = [
        point[0] * ky
        for point in path
    ]

    axes[0].plot(
        path_x,
        path_y,
        color="cyan",
        linewidth=2.5,
        label="Science-aware A* route"
    )

axes[0].set_title(
    "Safe route over DEM"
)

axes[0].set_xlabel(
    "Distance east (km)"
)

axes[0].set_ylabel(
    "Distance south (km)"
)

axes[0].legend(
    loc="upper left"
)


# ------------------------------------------------------------
# Plot 2: geology and route
# ------------------------------------------------------------

geology_image = axes[1].imshow(
    geology_normalised,
    cmap="plasma",
    vmin=0,
    vmax=1,
    extent=extent
)

fig.colorbar(
    geology_image,
    ax=axes[1],
    label="Scientific value"
)

# Only show slope-blocked cells here
axes[1].imshow(
    np.where(
        slope > MAX_SLOPE,
        1,
        np.nan
    ),
    cmap="Greys",
    alpha=0.3,
    vmin=0,
    vmax=1,
    extent=extent
)

axes[1].scatter(
    start[1] * kx,
    start[0] * ky,
    color="lime",
    edgecolors="black",
    s=60,
    label="Start",
    zorder=3
)

axes[1].scatter(
    goal[1] * kx,
    goal[0] * ky,
    color="red",
    edgecolors="black",
    s=60,
    label="Goal",
    zorder=3
)

if path:

    axes[1].plot(
        path_x,
        path_y,
        color="cyan",
        linewidth=2.5,
        label="Science-aware A* route"
    )

axes[1].set_title(
    "Route through scientifically valuable geology"
)

axes[1].set_xlabel(
    "Distance east (km)"
)

axes[1].set_ylabel(
    "Distance south (km)"
)

axes[1].legend(
    loc="upper left"
)

plt.tight_layout()

plt.savefig(
    "astar_geology_route.png",
    dpi=200,
    bbox_inches="tight"
)

plt.show()