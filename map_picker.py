"""
Click-to-pick start/end points and place obstacles on a rendered DEM.

    from map_picker import pick_route_points, GRID_ROWS, GRID_COLS
    start, end = pick_route_points("data/processed/cropped_dem.tif")   # each None or dict(lon, lat, row, col)

* The GeoTIFF is rendered to a PNG-style image (browsers can't show TIFFs) and its lon/lat bounds are
  read from the file itself, so clicks always line up with the raster your A* uses.
* row/col are given on a GRID_ROWS x GRID_COLS grid over the same extent (row 0 = north edge),
  which scale_cell() maps onto the terrain array.
* Selecting "Obstacle" marks a pending placement; the app saves its local x/y and radius to CSV.
* A manual lat/lon entry box is included in case the click component doesn't display.

    pip install streamlit streamlit-image-coordinates pillow numpy matplotlib rasterio pyproj
"""
import math
import os

import numpy as np
import streamlit as st
from PIL import Image, ImageDraw
from streamlit_image_coordinates import streamlit_image_coordinates

# Fallback extent (used only for PNG/placeholder images, or a DEM without georeferencing)
WEST, EAST = 137.341979, 137.426621
SOUTH, NORTH = -4.771627, -4.687273
BBOX = (WEST, SOUTH, EAST, NORTH)

GRID_ROWS, GRID_COLS = 200, 200      # picker grid; scale_cell() maps it onto the terrain array
MARS_R = 3396190.0
M_PER_DEG = 2 * math.pi * MARS_R / 360


# ---- coordinate transforms ------------------------------------------------
def px_to_lonlat(x, y, disp_w, disp_h, bbox=BBOX):
    w, s, e, n = bbox
    return w + (x / disp_w) * (e - w), n - (y / disp_h) * (n - s)


def lonlat_to_px(lon, lat, img_w, img_h, bbox=BBOX):
    w, s, e, n = bbox
    return (lon - w) / (e - w) * img_w, (n - lat) / (n - s) * img_h


def lonlat_to_cell(lon, lat, rows=GRID_ROWS, cols=GRID_COLS, bbox=BBOX):
    w, s, e, n = bbox
    col = min(cols - 1, max(0, int((lon - w) / (e - w) * cols)))
    row = min(rows - 1, max(0, int((n - lat) / (n - s) * rows)))
    return row, col


def cell_to_lonlat(row, col, rows=GRID_ROWS, cols=GRID_COLS, bbox=BBOX):
    w, s, e, n = bbox
    return w + (col + 0.5) / cols * (e - w), n - (row + 0.5) / rows * (n - s)


def local_km_to_lonlat(x_km, y_km, bbox=BBOX):
    w, s, e, n = bbox
    width_m = (e - w) * M_PER_DEG * math.cos(math.radians((s + n) / 2))
    height_m = (n - s) * M_PER_DEG
    return w + x_km * 1000 / width_m * (e - w), n - y_km * 1000 / height_m * (n - s)


# ---- rendering the DEM ----------------------------------------------------
def box_size_px(width_px=900, bbox=BBOX):
    w, s, e, n = bbox
    ground_w = (e - w) * math.cos(math.radians((s + n) / 2))
    return width_px, round(width_px * (n - s) / ground_w)


def make_placeholder(width_px=900, bbox=BBOX):
    W, H = box_size_px(width_px, bbox)
    w, s, e, n = bbox
    img = Image.new("RGB", (W, H), (176, 120, 86))
    d = ImageDraw.Draw(img)
    for i in range(1, 5):
        x, y = W * i / 5, H * i / 5
        d.line([(x, 0), (x, H)], fill=(215, 170, 140))
        d.line([(0, y), (W, y)], fill=(215, 170, 140))
        d.text((x + 3, H - 14), f"{w + (e - w) * i / 5:.4f}E", fill="white")
        d.text((3, y + 3), f"{n - (n - s) * i / 5:.4f}", fill="white")
    d.rectangle([0, 0, W - 1, H - 1], outline="black", width=3)
    d.text((6, 6), f"NW {n:.4f}, {w:.4f}E", fill="white")
    d.text((6, H - 28), f"SW {s:.4f}, {w:.4f}E", fill="white")
    return img


def _bounds_lonlat(ds):
    """Raster bounds as (west, south, east, north) in Mars lon/lat degrees, or None."""
    b = ds.bounds
    if ds.crs is None:
        return None
    if ds.crs.is_geographic:
        return (b.left, b.bottom, b.right, b.top)
    from pyproj import Transformer
    t = Transformer.from_crs(ds.crs, f"+proj=longlat +R={MARS_R} +no_defs", always_xy=True)
    xs, ys = zip(*(t.transform(x, y) for x, y in
                   [(b.left, b.bottom), (b.right, b.bottom), (b.left, b.top), (b.right, b.top)]))
    return (min(xs), min(ys), max(xs), max(ys))


@st.cache_data(show_spinner="Rendering terrain map...")
def render_image(path, mtime, max_px=1400):
    """Return (PIL image, bbox, note). Handles .tif/.tiff DEMs and ordinary images."""
    ext = os.path.splitext(path)[1].lower()
    if ext not in (".tif", ".tiff"):
        return Image.open(path).convert("RGB"), BBOX, "Image has no georeferencing; using the default bounding box."

    import rasterio
    from matplotlib import colormaps
    from matplotlib.colors import LightSource
    from rasterio.enums import Resampling

    with rasterio.open(path) as ds:
        scale = min(1.0, max_px / max(ds.width, ds.height))
        out_h, out_w = max(1, int(ds.height * scale)), max(1, int(ds.width * scale))
        z = ds.read(1, out_shape=(out_h, out_w), resampling=Resampling.bilinear).astype("float64")
        bad = ~np.isfinite(z)
        if ds.nodata is not None:
            bad |= (z == ds.nodata)
        bbox = _bounds_lonlat(ds)
        px_x, px_y = abs(ds.transform.a) / scale, abs(ds.transform.e) / scale
        if ds.crs is not None and ds.crs.is_geographic:      # degrees -> metres for correct hillshade
            lat0 = math.radians((ds.bounds.top + ds.bounds.bottom) / 2)
            px_x, px_y = px_x * M_PER_DEG * math.cos(lat0), px_y * M_PER_DEG
    note = None
    if bbox is None:
        bbox, note = BBOX, "DEM has no georeferencing; using the default bounding box."
    if bad.all():
        raise ValueError("The DEM contains no valid elevation values.")
    z[bad] = np.nanmin(z[~bad])
    rgba = LightSource(azdeg=315, altdeg=40).shade(
        z, cmap=colormaps["gist_earth"], blend_mode="soft", vert_exag=2.0, dx=px_x, dy=px_y)
    rgb = (rgba[..., :3] * 255).astype("uint8")
    rgb[bad] = (25, 25, 25)
    return Image.fromarray(rgb), tuple(float(v) for v in bbox), note


def load_base_image(path):
    """Returns (image, bbox, note). Falls back to a placeholder box if the file is missing."""
    if path and os.path.exists(path):
        return render_image(path, os.path.getmtime(path))
    return make_placeholder(), BBOX, f"'{path}' not found; showing a placeholder box. Check the path."


def annotate(img, start, end, path_cells=None, bbox=BBOX, obstacles=None, pending_obstacle=None):
    out = img.copy()
    d = ImageDraw.Draw(out)
    W, H = out.size
    r = max(5, W // 80)
    if path_cells:
        pts = [lonlat_to_px(*cell_to_lonlat(rr, cc, bbox=bbox), W, H, bbox) for rr, cc in path_cells]
        d.line(pts, fill=(0, 229, 255), width=max(2, r // 2))

    w, s, e, n = bbox
    width_m = (e - w) * M_PER_DEG * math.cos(math.radians((s + n) / 2))
    height_m = (n - s) * M_PER_DEG

    def draw_obstacle(obstacle, color):
        lon, lat = local_km_to_lonlat(obstacle["x_km"], obstacle["y_km"], bbox)
        x, y = lonlat_to_px(lon, lat, W, H, bbox)
        radius_m = float(obstacle["radius_m"])
        rx = max(4, radius_m * W / width_m)
        ry = max(4, radius_m * H / height_m)
        d.ellipse([x - rx, y - ry, x + rx, y + ry], outline=color, width=2)
        d.ellipse([x - 3, y - 3, x + 3, y + 3], fill=color, outline="black")

    for obstacle in obstacles or ():
        draw_obstacle(obstacle, (255, 112, 32))
    if pending_obstacle:
        draw_obstacle(pending_obstacle, (255, 235, 59))

    for pt, col in ((start, (0, 220, 0)), (end, (230, 30, 30))):
        if pt:
            x, y = lonlat_to_px(pt["lon"], pt["lat"], W, H, bbox)
            d.ellipse([x - r, y - r, x + r, y + r], fill=col, outline="black", width=2)
    return out


# ---- the widget -----------------------------------------------------------
def _point(lon, lat, bbox):
    row, col = lonlat_to_cell(lon, lat, bbox=bbox)
    w, s, _, n = bbox
    x_km = (lon - w) * M_PER_DEG * math.cos(math.radians((s + n) / 2)) / 1000
    y_km = (n - lat) * M_PER_DEG / 1000
    return dict(lon=lon, lat=lat, row=row, col=col, x_km=x_km, y_km=y_km)


def pick_route_points(image_path="data/processed/cropped_dem.tif", display_width=700, path_cells=None,
                      obstacles=None):
    ss = st.session_state
    ss.setdefault("start", None)
    ss.setdefault("end", None)
    ss.setdefault("last_click", None)

    img, bbox, note = load_base_image(image_path)
    if note:
        st.warning(note)
    w, s, e, n = bbox
    ratio = img.height / img.width

    if "next_mode" in ss:                            # applied BEFORE the radio is created
        ss["pick_mode"] = ss.pop("next_mode")
    mode = st.radio("Next click sets:", ["Start", "End", "Obstacle"], horizontal=True, key="pick_mode")
    pending_obstacle = ss.get("pending_obstacle")
    if pending_obstacle:
        pending_obstacle = dict(pending_obstacle, radius_m=ss.get("obstacle_radius", 25))
    shown = annotate(
        img, ss["start"], ss["end"], path_cells, bbox,
        obstacles=obstacles, pending_obstacle=pending_obstacle,
    ).resize(
        (display_width, int(display_width * ratio)))

    click = streamlit_image_coordinates(shown, key="mars_click")
    st.caption(f"Map extent: lon {w:.4f}° to {e:.4f}°E, lat {s:.4f}° to {n:.4f}°")

    if click and click != ss["last_click"]:          # ignore re-delivery of the same click
        ss["last_click"] = click
        lon, lat = px_to_lonlat(click["x"], click["y"], click["width"], click["height"], bbox)
        point = _point(lon, lat, bbox)
        if mode == "Obstacle":
            ss["pending_obstacle"] = point
        else:
            ss["start" if mode == "Start" else "end"] = point
            if mode == "Start":
                ss["next_mode"] = "End"
        st.rerun()

    with st.expander("Or type coordinates"):
        cols = st.columns(2)
        for col_, name in zip(cols, ("start", "end")):
            with col_:
                lat_in = st.number_input(f"{name.title()} latitude", value=float((s + n) / 2),
                                         format="%.5f", key=f"{name}_lat_in")
                lon_in = st.number_input(f"{name.title()} longitude (°E)", value=float((w + e) / 2),
                                         format="%.5f", key=f"{name}_lon_in")
                if st.button(f"Set {name}", key=f"set_{name}"):
                    if w <= lon_in <= e and s <= lat_in <= n:
                        ss[name] = _point(lon_in, lat_in, bbox)
                        st.rerun()
                    else:
                        st.error("That point is outside the map.")

    c1, c2, c3 = st.columns([2, 2, 1])
    for col_, name in ((c1, "start"), (c2, "end")):
        p = ss[name]
        col_.metric(name.title(), f"{p['lat']:.5f}°, {p['lon']:.5f}°E" if p else "not set",
                    f"cell ({p['row']}, {p['col']})" if p else None, delta_color="off")
    if c3.button("Reset"):
        ss["start"] = ss["end"] = ss["last_click"] = None
        ss["pending_obstacle"] = None
        ss["next_mode"] = "Start"
        st.rerun()
    return ss["start"], ss["end"]


if __name__ == "__main__":
    st.set_page_config(page_title="Pick route points", layout="centered")
    st.title("Pick start and end on the map")
    s_, e_ = pick_route_points("data/processed/cropped_dem.tif")
    if s_ and e_:
        st.success(f"A* inputs -> start={(s_['row'], s_['col'])}, goal={(e_['row'], e_['col'])}")