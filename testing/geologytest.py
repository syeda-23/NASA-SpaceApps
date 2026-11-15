import rasterio

with rasterio.open(
    "data/raw/gale_dem_1m.tif"
) as src:

    # Approximate centre of your geology dataset
    x = 8144000
    y = -280000

    row, col = src.index(
        x,
        y
    )

    print("Row:", row)
    print("Col:", col)

    print(
        "DEM size:",
        src.width,
        src.height
    )