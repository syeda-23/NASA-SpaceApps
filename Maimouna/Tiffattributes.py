import numpy as np
import rasterio
import matplotlib.pyplot as plt

TIF = "data/processed/cropped_dem.tif"   # change to your file name / path
MARS_RADIUS = 3396190  # metres, used if the CRS is in degrees

with rasterio.open(TIF) as src:
    print("=== FILE ===")
    print("Driver:", src.driver)
    print("Size (cols x rows):", src.width, "x", src.height)
    print("Bands:", src.count)
    print("Data type:", src.dtypes)
    print("NoData value:", src.nodata)
    print("Compression:", src.compression)

    print("\n=== GEOREFERENCING ===")
    print("CRS:", src.crs)
    geographic = bool(src.crs and src.crs.is_geographic)
    print("Units in degrees?:", geographic)
    print("Pixel size (x, y):", src.res)
    print("Bounds:", src.bounds)
    print("Transform:")
    print(src.transform)

    print("\n=== METADATA TAGS ===")
    for k, v in src.tags().items():
        print(" ", k, "=", v)
    print("Band 1 tags:", src.tags(1))
    print("Band units:", src.units)
    print("Scale / offset:", src.scales, src.offsets)

    dem = src.read(1, masked=True).astype(float).filled(np.nan)
    pixel_x, pixel_y = src.res

# ---- Pixel size in metres ----
if geographic:
    m_per_deg = 2 * np.pi * MARS_RADIUS / 360
    pixel_x = pixel_x * m_per_deg
    pixel_y = pixel_y * m_per_deg
    print("\nConverted pixel size (m):", round(pixel_x, 2), "x", round(pixel_y, 2))

# ---- Elevation stats ----
print("\n=== ELEVATION ===")
print("Array shape (rows, cols):", dem.shape)
print("Min / max (m):", np.nanmin(dem), "/", np.nanmax(dem))
print("Mean / std (m):", round(np.nanmean(dem), 1), "/", round(np.nanstd(dem), 1))
print("NoData cells: %.2f %%" % (100 * np.isnan(dem).mean()))

# ---- Slope stats ----
dy, dx = np.gradient(dem, pixel_y, pixel_x)
slope = np.degrees(np.arctan(np.hypot(dx, dy)))
print("\n=== SLOPE (degrees) ===")
for p in (50, 75, 90, 95, 99):
    print(f"  {p}th percentile: {np.nanpercentile(slope, p):.1f}")
print("Max slope:", round(np.nanmax(slope), 1))

# ---- Suggestions for A-star ----
rows, cols = dem.shape
suggested_ds = max(1, max(rows, cols) // 500)
print("\n=== SUGGESTED A-STAR SETTINGS ===")
print("DOWNSAMPLE =", suggested_ds, "-> grid", rows // suggested_ds, "x", cols // suggested_ds)
print("Pixel size after downsample (m):", round(pixel_x * suggested_ds, 1))
print("Real map size (km): %.1f x %.1f" % (cols * pixel_x / 1000, rows * pixel_y / 1000))

# ---- Quick look ----
fig, ax = plt.subplots(1, 3, figsize=(15, 4))
ax[0].imshow(dem, cmap="terrain")
ax[0].set_title("Elevation")
ax[1].imshow(slope, cmap="magma", vmax=np.nanpercentile(slope, 99))
ax[1].set_title("Slope")
ax[2].hist(slope[~np.isnan(slope)].ravel(), bins=100)
ax[2].set_title("Slope histogram")
plt.tight_layout()
plt.show()