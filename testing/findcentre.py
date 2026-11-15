import rasterio
from pyproj import Transformer
DEM_PATH = "data/raw/gale_dem_1m.tif"
col_off = 13506
row_off = 32718
with rasterio.open(DEM_PATH) as src:
    print("CRS:", src.crs)
    print("Transform:", src.transform)
    x, y = src.xy(
        row_off,
        col_off,
        offset="center"
    )
    print("Projected X:", x)
    print("Projected Y:", y)
    mars_lonlat = (
        "+proj=longlat "
        "+a=3396190 "
        "+b=3396190 "
        "+no_defs"
    )
    transformer = Transformer.from_crs(
        src.crs,
        mars_lonlat,
        always_xy=True
    )
    longitude, latitude = transformer.transform(x, y)
    print("Longitude:", longitude)
    print("Latitude:", latitude)