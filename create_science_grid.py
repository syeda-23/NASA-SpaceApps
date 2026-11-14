from pathlib import Path

import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio

from rasterio.features import rasterize
from scipy.ndimage import distance_transform_edt


# --------------------------------------------------
# PATHS
# --------------------------------------------------

PROCESSED = Path("data/processed")
GEOLOGY = Path("data/geology")

PBR_FILE = GEOLOGY / "GT_PBRs.shp"
TAR_FILE = GEOLOGY / "GT_TARs.shp"

CROPPED_DEM = PROCESSED / "cropped_dem.tif"

SCIENCE_FEATURES = (
    PROCESSED /
    "science_features.npy"
)

SCIENCE_VALUES = (
    PROCESSED /
    "science_value.npy"
)

PREVIEW = (
    PROCESSED /
    "science_preview.png"
)

# --------------------------------------------------
# SETTINGS
# --------------------------------------------------

PBR_SCORE = 1.0
TAR_SCORE = 0.75

DECAY_DISTANCE = 40


# --------------------------------------------------
# MAIN
# --------------------------------------------------

def main():

    print("Loading DEM...")

    with rasterio.open(
        CROPPED_DEM
    ) as src:

        width = src.width
        height = src.height

        transform = src.transform
        crs = src.crs

        shape = (
            height,
            width
        )

    print(
        f"DEM Shape: {shape}"
    )

    print("Loading geology...")

    pbr = gpd.read_file(
        PBR_FILE
    )

    tar = gpd.read_file(
        TAR_FILE
    )

    print(
        f"PBR features: {len(pbr)}"
    )

    print(
        f"TAR features: {len(tar)}"
    )

    if pbr.crs != crs:

        print(
            "Reprojecting PBR..."
        )

        pbr = pbr.to_crs(
            crs
        )

    if tar.crs != crs:

        print(
            "Reprojecting TAR..."
        )

        tar = tar.to_crs(
            crs
        )

    print(
        "Rasterizing geology..."
    )

    pbr_raster = rasterize(

        (
            (
                geom,
                PBR_SCORE
            )
            for geom in pbr.geometry
        ),

        out_shape=shape,

        transform=transform,

        fill=0,

        dtype=np.float32
    )

    tar_raster = rasterize(

        (
            (
                geom,
                TAR_SCORE
            )
            for geom in tar.geometry
        ),

        out_shape=shape,

        transform=transform,

        fill=0,

        dtype=np.float32
    )

    science_features = np.maximum(
        pbr_raster,
        tar_raster
    )

    np.save(
        SCIENCE_FEATURES,
        science_features
    )

    print(
        "Generating science value layer..."
    )

    feature_mask = (
        science_features > 0
    )

    distance = distance_transform_edt(
        ~feature_mask
    )

    science_value = np.exp(
        -distance /
        DECAY_DISTANCE
    )

    if (
        science_features.max()
        > 0
    ):

        science_value *= (
            science_features.max()
        )

    science_value = np.clip(
        science_value,
        0,
        1
    )

    np.save(
        SCIENCE_VALUES,
        science_value
    )

    print(
        "Creating preview image..."
    )

    plt.figure(
        figsize=(10, 8)
    )

    plt.imshow(
        science_value,
        cmap="plasma"
    )

    plt.colorbar(
        label="Science Value"
    )

    plt.title(
        "Scientific Discovery Layer"
    )

    plt.tight_layout()

    plt.savefig(
        PREVIEW,
        dpi=300
    )

    plt.close()

    print("\nSUCCESS")

    print(
        f"\nSaved:\n"
    )

    print(
        SCIENCE_FEATURES
    )

    print(
        SCIENCE_VALUES
    )

    print(
        PREVIEW
    )

    print()

    print(
        "Science Range:"
    )

    print(
        science_value.min(),
        science_value.max()
    )


if __name__ == "__main__":
    main()