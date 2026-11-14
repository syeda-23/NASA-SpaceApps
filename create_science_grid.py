from pathlib import Path
import json
import geopandas as gpd
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.enums import MergeAlg
from rasterio.features import rasterize
from scipy.ndimage import distance_transform_edt

GEOLOGY_DIR = Path("data/geology")
PROCESSED_DIR = Path("data/processed")
OUTPUT_DIR = Path("outputs")

PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

MASTER_GRID_PATH = PROCESSED_DIR / "glen_torridon_slope_10m.tif"
MOSAIC_PATH = PROCESSED_DIR / "glen_torridon_mosaic_10m.tif"
SLOPE_PATH = PROCESSED_DIR / "slope.npy"
TRAVERSABLE_PATH = PROCESSED_DIR / "traversable.npy"

SCIENCE_PATH = PROCESSED_DIR / "science_value.npy"
FEATURE_PATH = PROCESSED_DIR / "science_features.npy"
SCIENCE_TIF_PATH = PROCESSED_DIR / "science_value_10m.tif"
METADATA_PATH = PROCESSED_DIR / "science_metadata.json"
PREVIEW_PATH = OUTPUT_DIR / "science_value_preview.png"

PBR_VALUE = 1.00
TAR_VALUE = 0.75
RIPPLE_VALUE = 0.50
OTHER_VALUE = 0.35

DECAY_DISTANCE_M = 40.0


def load_master_grid():
    if not MASTER_GRID_PATH.exists():
        raise FileNotFoundError(
            f"Master grid not found: {MASTER_GRID_PATH}"
        )

    with rasterio.open(MASTER_GRID_PATH) as src:
        if src.crs is None:
            raise ValueError("The slope GeoTIFF has no CRS.")

        grid = {
            "crs": src.crs,
            "transform": src.transform,
            "height": src.height,
            "width": src.width,
            "shape": (src.height, src.width),
            "bounds": src.bounds,
            "cell_size_x": abs(src.transform.a),
            "cell_size_y": abs(src.transform.e),
            "profile": src.profile.copy()
        }

    print("Master grid CRS:", grid["crs"])
    print("Master grid shape:", grid["shape"])
    print(
        "Cell size:",
        grid["cell_size_x"],
        "x",
        grid["cell_size_y"],
        "m"
    )

    return grid


def find_shapefiles():
    shapefiles = sorted(GEOLOGY_DIR.rglob("*.shp"))

    if not shapefiles:
        raise FileNotFoundError(
            f"No .shp files found inside {GEOLOGY_DIR.resolve()}"
        )

    print("Found", len(shapefiles), "shapefiles")

    for shapefile in shapefiles:
        print(shapefile)

    return shapefiles


def classify_feature(path):
    name = str(path).lower()

    if "pbr" in name or "bedrock" in name:
        return "periodic_bedrock_ridge", PBR_VALUE

    if "tar" in name:
        return "transverse_aeolian_ridge", TAR_VALUE

    if "ripple" in name:
        return "ripple", RIPPLE_VALUE

    return "other", OTHER_VALUE


def bounds_overlap(vector_bounds, raster_bounds):
    vector_left = vector_bounds[0]
    vector_bottom = vector_bounds[1]
    vector_right = vector_bounds[2]
    vector_top = vector_bounds[3]

    return not (
        vector_right < raster_bounds.left
        or vector_left > raster_bounds.right
        or vector_top < raster_bounds.bottom
        or vector_bottom > raster_bounds.top
    )


def load_vector(path, grid):
    print("Reading:", path)

    data = gpd.read_file(path)

    print("Features:", len(data))
    print("Original CRS:", data.crs)
    print("Original bounds:", data.total_bounds)

    if data.empty:
        return None

    if data.crs is None:
        raise ValueError(
            f"{path} has no CRS. Check that the .prj file is beside the .shp file."
        )

    data = data[
        data.geometry.notna()
        & ~data.geometry.is_empty
    ].copy()

    if data.empty:
        return None

    data = data.to_crs(grid["crs"])

    print("Reprojected bounds:", data.total_bounds)

    if not bounds_overlap(
        data.total_bounds,
        grid["bounds"]
    ):
        print("No overlap with ROI")
        return None

    bounds = grid["bounds"]

    data = data.cx[
        bounds.left:bounds.right,
        bounds.bottom:bounds.top
    ].copy()

    if data.empty:
        return None

    print("Features inside ROI:", len(data))

    return data


def rasterise_features(data, grid, value):
    shapes = [
        (geometry, float(value))
        for geometry in data.geometry
    ]

    raster = rasterize(
        shapes=shapes,
        out_shape=grid["shape"],
        transform=grid["transform"],
        fill=0.0,
        all_touched=True,
        dtype="float32",
        merge_alg=MergeAlg.max
    )

    return raster


def create_science_value(feature_grid, grid):
    feature_mask = feature_grid > 0

    if not np.any(feature_mask):
        raise ValueError(
            "No scientific features were mapped inside the ROI."
        )

    cell_size = (
        grid["cell_size_x"]
        + grid["cell_size_y"]
    ) / 2.0

    distance_cells, nearest_indices = distance_transform_edt(
        ~feature_mask,
        return_indices=True
    )

    distance_metres = distance_cells * cell_size

    nearest_feature_value = feature_grid[
        nearest_indices[0],
        nearest_indices[1]
    ]

    science_value = (
        nearest_feature_value
        * np.exp(
            -distance_metres / DECAY_DISTANCE_M
        )
    )

    science_value = np.clip(
        science_value,
        0.0,
        1.0
    ).astype(np.float32)

    return science_value


def save_geotiff(path, array, grid):
    profile = grid["profile"].copy()

    profile.update(
        driver="GTiff",
        dtype="float32",
        count=1,
        nodata=-9999.0,
        compress="deflate",
        tiled=True
    )

    with rasterio.open(path, "w", **profile) as dst:
        dst.write(array.astype(np.float32), 1)

    print("Saved:", path)


def validate_astar_data(science_value):
    print("Science grid:", science_value.shape)

    if SLOPE_PATH.exists():
        slope = np.load(SLOPE_PATH)

        print("Slope grid:", slope.shape)

        if slope.shape != science_value.shape:
            raise ValueError(
                "slope.npy and science_value.npy have different shapes."
            )

    if TRAVERSABLE_PATH.exists():
        traversable = np.load(TRAVERSABLE_PATH)

        print("Traversable grid:", traversable.shape)

        if traversable.shape != science_value.shape:
            raise ValueError(
                "traversable.npy and science_value.npy have different shapes."
            )

    print("SUCCESS: science grid matches A* grid")


def load_mosaic():
    if not MOSAIC_PATH.exists():
        return None

    with rasterio.open(MOSAIC_PATH) as src:
        image = src.read()

    if image.shape[0] >= 3:
        image = np.moveaxis(
            image[:3],
            0,
            -1
        ).astype(np.float32)

        for band in range(3):
            values = image[:, :, band]

            low = np.percentile(values, 2)
            high = np.percentile(values, 98)

            if high > low:
                image[:, :, band] = np.clip(
                    (values - low) / (high - low),
                    0.0,
                    1.0
                )

        return image

    return image[0]


def create_preview(feature_grid, science_value):
    mosaic = load_mosaic()

    figure, axes = plt.subplots(
        1,
        3,
        figsize=(18, 6)
    )

    if mosaic is not None:
        axes[0].imshow(mosaic, origin="upper")
        axes[0].set_title("Glen Torridon")
    else:
        axes[0].text(
            0.5,
            0.5,
            "Mosaic unavailable",
            ha="center",
            va="center"
        )

    axes[0].axis("off")

    feature_plot = axes[1].imshow(
        feature_grid,
        cmap="hot",
        origin="upper",
        vmin=0,
        vmax=1
    )

    axes[1].set_title("Mapped Scientific Features")
    axes[1].axis("off")

    figure.colorbar(
        feature_plot,
        ax=axes[1],
        label="Feature importance"
    )

    if mosaic is not None:
        axes[2].imshow(mosaic, origin="upper")

        overlay = np.ma.masked_where(
            science_value < 0.02,
            science_value
        )

        science_plot = axes[2].imshow(
            overlay,
            cmap="viridis",
            origin="upper",
            vmin=0,
            vmax=1,
            alpha=0.75
        )
    else:
        science_plot = axes[2].imshow(
            science_value,
            cmap="viridis",
            origin="upper",
            vmin=0,
            vmax=1
        )

    axes[2].set_title("Scientific Discovery Potential")
    axes[2].axis("off")

    figure.colorbar(
        science_plot,
        ax=axes[2],
        label="Science score (0-1)"
    )

    figure.tight_layout()
    figure.savefig(PREVIEW_PATH, dpi=200)
    plt.close(figure)

    print("Saved preview:", PREVIEW_PATH)


def main():
    grid = load_master_grid()
    shapefiles = find_shapefiles()

    combined_features = np.zeros(
        grid["shape"],
        dtype=np.float32
    )

    dataset_report = []

    for shapefile in shapefiles:
        feature_type, feature_value = classify_feature(
            shapefile
        )

        print("Processing:", shapefile)
        print("Type:", feature_type)
        print("Science importance:", feature_value)

        data = load_vector(
            shapefile,
            grid
        )

        if data is None:
            dataset_report.append({
                "file": str(shapefile),
                "type": feature_type,
                "status": "empty_or_no_overlap"
            })
            continue

        feature_layer = rasterise_features(
            data,
            grid,
            feature_value
        )

        combined_features = np.maximum(
            combined_features,
            feature_layer
        )

        dataset_report.append({
            "file": str(shapefile),
            "type": feature_type,
            "status": "processed",
            "features_in_roi": int(len(data)),
            "science_importance": float(feature_value)
        })

    mapped_cells = int(
        np.sum(combined_features > 0)
    )

    print("Mapped feature cells:", mapped_cells)

    if mapped_cells == 0:
        raise ValueError(
            "No mapped features landed inside the ROI. Check the CRS output."
        )

    science_value = create_science_value(
        combined_features,
        grid
    )

    validate_astar_data(
        science_value
    )

    np.save(
        SCIENCE_PATH,
        science_value
    )

    np.save(
        FEATURE_PATH,
        combined_features
    )

    print("Saved:", SCIENCE_PATH)
    print("Saved:", FEATURE_PATH)

    save_geotiff(
        SCIENCE_TIF_PATH,
        science_value,
        grid
    )

    metadata = {
        "region": "Glen Torridon, Gale Crater, Mars",
        "grid_rows": int(grid["height"]),
        "grid_columns": int(grid["width"]),
        "cell_size_m": float(grid["cell_size_x"]),
        "science_value_range": [0.0, 1.0],
        "decay_distance_m": DECAY_DISTANCE_M,
        "feature_scoring": {
            "periodic_bedrock_ridge": PBR_VALUE,
            "transverse_aeolian_ridge": TAR_VALUE,
            "ripple": RIPPLE_VALUE,
            "other": OTHER_VALUE
        },
        "interpretation": (
            "Relative scientific discovery potential based on "
            "proximity to mapped Glen Torridon geomorphological features."
        ),
        "use": "Discovery A* route",
        "datasets": dataset_report
    }

    with open(
        METADATA_PATH,
        "w",
        encoding="utf-8"
    ) as file:
        json.dump(
            metadata,
            file,
            indent=4
        )

    create_preview(
        combined_features,
        science_value
    )

    print("FINISHED")
    print("Grid shape:", science_value.shape)
    print(
        "Minimum science score:",
        float(np.min(science_value))
    )
    print(
        "Maximum science score:",
        float(np.max(science_value))
    )
    print(
        "Mean science score:",
        float(np.mean(science_value))
    )
    print(
        "High-interest cells >= 0.5:",
        int(np.sum(science_value >= 0.5))
    )

    print(
        "Give this file to your A* teammate:",
        SCIENCE_PATH
    )


if __name__ == "__main__":
    main()