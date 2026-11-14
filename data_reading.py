from pathlib import Path
import json

import numpy as np
import rasterio

from scipy.ndimage import gaussian_filter

RAW_DIR = Path("data/raw")

PROCESSED_DIR = Path(
    "data/processed"
)

PROCESSED_DIR.mkdir(
    parents=True,
    exist_ok=True
)

DEM_FILE = (
    RAW_DIR /
    "gale_dem_1m.tif"
)


def calculate_slope(dem):

    dy, dx = np.gradient(
        dem
    )

    slope = np.sqrt(
        dx**2 +
        dy**2
    )

    return slope


def calculate_roughness(dem):

    smooth = gaussian_filter(
        dem,
        sigma=3
    )

    roughness = np.abs(
        dem - smooth
    )

    return roughness


def normalise(arr):

    mn = np.nanmin(arr)
    mx = np.nanmax(arr)

    if mx == mn:
        return np.zeros_like(arr)

    return (
        arr - mn
    ) / (
        mx - mn
    )


def main():

    with rasterio.open(
        DEM_FILE
    ) as src:

        window = (
            rasterio.windows.Window(
                col_off=10000,
                row_off=10000,
                width=2000,
                height=2000
            )
        )

        dem = src.read(
            1,
            window=window
        )

        transform = (
            src.window_transform(
                window
            )
        )

        profile = (
            src.profile.copy()
        )

        profile.update(
            width=window.width,
            height=window.height,
            transform=transform
        )

    print(
        f"DEM Shape: {dem.shape}"
    )

    print(
        f"Elevation Range:"
        f" {dem.min():.2f}"
        f" -> "
        f"{dem.max():.2f}"
    )

    # -----------------------
    # Save cropped DEM
    # -----------------------

    cropped_dem_file = (
        PROCESSED_DIR /
        "cropped_dem.tif"
    )

    with rasterio.open(
        cropped_dem_file,
        "w",
        **profile
    ) as dst:

        dst.write(
            dem,
            1
        )

    # -----------------------
    # Slope
    # -----------------------

    slope = (
        calculate_slope(
            dem
        )
    )

    slope_norm = (
        normalise(
            slope
        )
    )

    np.save(
        PROCESSED_DIR /
        "slope.npy",
        slope_norm
    )

    # -----------------------
    # Roughness
    # -----------------------

    roughness = (
        calculate_roughness(
            dem
        )
    )

    roughness_norm = (
        normalise(
            roughness
        )
    )

    # -----------------------
    # Traversability
    # -----------------------

    traversability = (
        0.7 * slope_norm +
        0.3 * roughness_norm
    )

    np.save(
        PROCESSED_DIR /
        "traversability_matrix.npy",
        traversability
    )

    np.savetxt(
        PROCESSED_DIR /
        "traversability_matrix.csv",
        traversability,
        delimiter=","
    )

    traversable = (
        traversability < 0.8
    )

    np.save(
        PROCESSED_DIR /
        "traversable.npy",
        traversable
    )

    metadata = {

        "rows":
        int(
            traversability.shape[0]
        ),

        "cols":
        int(
            traversability.shape[1]
        ),

        "cell_size_m":
        1,

        "roi_width_pixels":
        2000,

        "roi_height_pixels":
        2000,

        "col_off":
        10000,

        "row_off":
        10000
    }

    with open(
        PROCESSED_DIR /
        "grid_metadata.json",
        "w"
    ) as f:

        json.dump(
            metadata,
            f,
            indent=2
        )

    print("\nGenerated:\n")

    print(
        "cropped_dem.tif"
    )

    print(
        "slope.npy"
    )

    print(
        "traversability_matrix.npy"
    )

    print(
        "traversable.npy"
    )

    print(
        "grid_metadata.json"
    )

    print(
        "\nCost Stats"
    )

    print(
        "Min:",
        traversability.min()
    )

    print(
        "Max:",
        traversability.max()
    )

    print(
        "Mean:",
        traversability.mean()
    )


if __name__ == "__main__":
    main()