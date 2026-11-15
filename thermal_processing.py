"""
Crop a THEMIS thermal-inertia GeoTIFF to the Gale study box and resample it to your A* grid.

    pip install rasterio pyproj numpy
    python thermal_to_grid.py THEMIS_TI_Mosaic_Quant_30S120E_100mpp.tif --rows 200 --cols 200

Writes thermal_inertia.npy and thermal_inertia.csv (row 0 = NORTH edge, same as map_picker's grid).
Units: J m^-2 K^-1 s^-1/2 ("tiu") if you use the QUANTITATIVE (32-bit) mosaic.
"""
import argparse

import numpy as np
import rasterio
from pyproj import Transformer
from rasterio.enums import Resampling
from rasterio.windows import from_bounds

WEST, EAST, SOUTH, NORTH = 137.341979, 137.426621, -4.771627, -4.687273
MARS_R = 3396190.0   # Mars sphere radius used by USGS products (m)

ap = argparse.ArgumentParser()
ap.add_argument("tif")
ap.add_argument("--rows", type=int, default=200)
ap.add_argument("--cols", type=int, default=200)
a = ap.parse_args()

with rasterio.open(a.tif) as ds:
    if ds.dtypes[0] == "uint8":
        print("WARNING: 8-bit file = qualitative stretch, NOT real thermal inertia values. "
              "Download the Quantitative (32-bit) mosaic.")
    to_ds = Transformer.from_crs(f"+proj=longlat +R={MARS_R} +no_defs", ds.crs, always_xy=True)
    (x0, y0), (x1, y1) = to_ds.transform(WEST, SOUTH), to_ds.transform(EAST, NORTH)
    win = from_bounds(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1), ds.transform)
    data = ds.read(1, window=win, out_shape=(a.rows, a.cols), resampling=Resampling.bilinear,
                   boundless=True, fill_value=np.nan).astype("float64")
    if ds.nodata is not None:
        data[data == ds.nodata] = np.nan
    native = (win.width, win.height)

print(f"native pixels in box: {native[0]:.1f} x {native[1]:.1f}  (100 m/px => expect ~50 x 50)")
print(f"thermal inertia  min {np.nanmin(data):.0f}  mean {np.nanmean(data):.0f}  max {np.nanmax(data):.0f}")
np.save("thermal_inertia.npy", data)
np.savetxt("thermal_inertia.csv", data, delimiter=",", fmt="%.1f")
print("saved thermal_inertia.npy / .csv", data.shape)