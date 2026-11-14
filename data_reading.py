from pathlib import Path

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

    dy, dx = np.gradient(dem)

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

    arr = (
        arr -
        np.nanmin(arr)
    )

    arr = (
        arr /
        np.nanmax(arr)
    )

    return arr


def build_cost_matrix(dem):

    slope = calculate_slope(
        dem
    )

    roughness = (
        calculate_roughness(
            dem
        )
    )

    slope_norm = (
        normalise(slope)
    )

    roughness_norm = (
        normalise(
            roughness
        )
    )

    cost_matrix = (
        0.7 * slope_norm +
        0.3 * roughness_norm
    )

    return cost_matrix


def main():

    with rasterio.open(
        DEM_FILE
    ) as src:

        # Hackathon-sized crop

        window = rasterio.windows.Window(
            col_off=10000,
            row_off=10000,
            width=2000,
            height=2000
        )

        dem = src.read(
            1,
            window=window
        )

    print(
        f"DEM shape: {dem.shape}"
    )

    print(
        f"Elevation range:"
        f" {dem.min():.2f}"
        f" -> {dem.max():.2f}"
    )

    cost_matrix = (
        build_cost_matrix(
            dem
        )
    )

    npy_file = (
        PROCESSED_DIR /
        "traversability_matrix.npy"
    )

    csv_file = (
        PROCESSED_DIR /
        "traversability_matrix.csv"
    )

    np.save(
        npy_file,
        cost_matrix
    )

    np.savetxt(
        csv_file,
        cost_matrix,
        delimiter=","
    )

    print("\nOutputs generated:")
    print(npy_file)
    print(csv_file)

    print(
        f"\nMatrix shape:"
        f" {cost_matrix.shape}"
    )

    print(
        f"Min cost:"
        f" {cost_matrix.min():.4f}"
    )

    print(
        f"Max cost:"
        f" {cost_matrix.max():.4f}"
    )


if __name__ == "__main__":
    main()