# visual confirmation our data is being read correctly

import rasterio
import matplotlib.pyplot as plt

with rasterio.open(
    "data/raw/gale_dem_1m.tif"
) as src:

    window = rasterio.windows.Window(
        10000,
        10000,
        2000,
        2000
    )

    dem = src.read(
        1,
        window=window
    )

plt.imshow(
    dem,
    cmap="terrain"
)

plt.colorbar()
plt.title("Raw DEM")

plt.show()