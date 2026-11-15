"""
Download ONLY your study area from NASA Mars Trek (WMTS tiles) and save mars_patch.png.

    pip install requests pillow
    python fetch_mars_patch.py                              # CTX mosaic, default box
    python fetch_mars_patch.py --layer curiosity_hirise_mosaic
    python fetch_mars_patch.py --zoom 15 --api-key YOUR_KEY # force zoom / add key if you get 403

It reads the layer's WMTSCapabilities.xml, works out which tiles cover the box,
downloads them in parallel, stitches them and crops to the exact bounding box.
"""
import argparse
import io
import math
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor

from PIL import Image

BASE = "https://api.nasa.gov/mars-wmts/catalog"
WEST, EAST, SOUTH, NORTH = 137.341979, 137.426621, -4.771627, -4.687273


def local(tag):
    return tag.split("}")[-1]


def parse_capabilities(xml_bytes):
    root = ET.fromstring(xml_bytes)
    info = dict(style="default", tms=None, ext="jpg", template=None, bbox=None, matrices={})
    link_tms = None
    for el in root.iter():
        t = local(el.tag)
        if t == "Style":
            ident = next((c.text for c in el if local(c.tag) == "Identifier"), None)
            info["style"] = ident or info["style"]
        elif t == "ResourceURL" and el.get("resourceType") == "tile":
            info["template"] = el.get("template")
            info["ext"] = "png" if "png" in el.get("format", "") else "jpg"
        elif t == "WGS84BoundingBox" and info["bbox"] is None:
            lo = next(c.text for c in el if local(c.tag) == "LowerCorner").split()
            hi = next(c.text for c in el if local(c.tag) == "UpperCorner").split()
            info["bbox"] = (float(lo[0]), float(lo[1]), float(hi[0]), float(hi[1]))  # lon, lat
        elif t == "TileMatrixSet" and not len(el) and el.text and info["tms"] is None:
            link_tms = el.text.strip()          # <TileMatrixSetLink><TileMatrixSet>name</...> inside the Layer
        elif t == "TileMatrixSet" and len(el) and not info["matrices"]:
            ident = next((c.text for c in el if local(c.tag) == "Identifier"), None)
            if ident is None:
                continue
            info["tms"] = ident
            for tm in el:
                if local(tm.tag) != "TileMatrix":
                    continue
                d = {local(c.tag): c.text for c in tm}
                tl = d["TopLeftCorner"].split()
                info["matrices"][d["Identifier"]] = dict(
                    top_left=(float(tl[0]), float(tl[1])),
                    tw=int(float(d["TileWidth"])), th=int(float(d["TileHeight"])),
                    mw=int(float(d["MatrixWidth"])), mh=int(float(d["MatrixHeight"])))
    if link_tms and info["tms"] and link_tms != info["tms"]:
        info["tms"] = link_tms                  # the layer says which matrix set it uses
    if not info["matrices"]:
        raise ValueError("no TileMatrix entries found in capabilities")
    return info


def tile_url(layer, info, z, row, col, api_key=None, base=BASE, ext=None):
    if info["template"]:
        url = (info["template"].replace("{Style}", info["style"]).replace("{TileMatrixSet}", info["tms"])
               .replace("{TileMatrix}", str(z)).replace("{TileRow}", str(row)).replace("{TileCol}", str(col)))
    else:
        url = f"{base}/{layer}/1.0.0/{info['style']}/{info['tms']}/{z}/{row}/{col}.{ext or info['ext']}"
    return url + (f"?api_key={api_key}" if api_key else "")


def assumed_info(ext="png"):
    """Standard Trek grid (global, 2x1 tiles at zoom 0, 256px, doubling each zoom). Used if the
    capabilities file can't be downloaded."""
    return dict(style="default", tms="default028mm", ext=ext, template=None, bbox=None,
                matrices={str(z): dict(top_left=(-180.0, 90.0), tw=256, th=256, mw=2 ** (z + 1), mh=2 ** z)
                          for z in range(16)})


def tile_range(m, bbox):
    """Fractional tile coordinates of the bbox corners in this matrix (geographic, degrees)."""
    w, s, e, n = bbox
    span_x, span_y = 360.0 / m["mw"], 180.0 / m["mh"]
    x0, y0 = m["top_left"]
    fx = lambda lon: (lon - x0) / span_x
    fy = lambda lat: (y0 - lat) / span_y
    return fx(w), fy(n), fx(e), fy(s)       # left, top, right, bottom (fractional tiles)


def build_patch(layer, bbox, fetch, zoom=None, max_width=2000, max_tiles=400, api_key=None, log=print,
                base=BASE, assume_grid=False, workers=8):
    info = None
    if not assume_grid:
        try:
            info = parse_capabilities(fetch(f"{base}/{layer}/1.0.0/WMTSCapabilities.xml"))
        except Exception as exc:
            log(f"Could not use the layer index ({type(exc).__name__}: {exc}); assuming the standard Trek tile grid.")
    info = info or assumed_info()
    if info["bbox"]:
        cw, cs, ce, cn = info["bbox"]
        if bbox[0] < cw or bbox[2] > ce or bbox[1] < cs or bbox[3] > cn:
            log(f"WARNING: layer covers lon {cw}..{ce}, lat {cs}..{cn}; your box is not fully inside it.")
    zooms = sorted(int(z) for z in info["matrices"])
    if zoom is None:   # highest zoom whose native width fits max_width and tile budget
        zoom = zooms[0]
        for z in zooms:
            l, t, r, b = tile_range(info["matrices"][str(z)], bbox)
            tiles = (math.floor(r) - math.floor(l) + 1) * (math.floor(b) - math.floor(t) + 1)
            if (r - l) * info["matrices"][str(z)]["tw"] <= max_width and tiles <= max_tiles:
                zoom = z
    m = info["matrices"][str(zoom)]
    l, t, r, b = tile_range(m, bbox)
    c0, c1, r0, r1 = math.floor(l), math.floor(r), math.floor(t), math.floor(b)
    log(f"zoom {zoom}: {(c1 - c0 + 1) * (r1 - r0 + 1)} tiles, ~{(r - l) * m['tw']:.0f} x {(b - t) * m['th']:.0f} px")

    jobs = [(rr, cc) for rr in range(r0, r1 + 1) for cc in range(c0, c1 + 1)]

    exts = [info["ext"]] + [e for e in ("png", "jpg") if e != info["ext"]]
    done = [0]

    def get(job):
        rr, cc = job
        im = None
        for ext in ([None] if info["template"] else exts):
            try:
                data = fetch(tile_url(layer, info, zoom, rr, cc, api_key, base, ext))
                im = Image.open(io.BytesIO(data)).convert("RGB")
                break
            except Exception:
                continue
        done[0] += 1
        if done[0] % 10 == 0:
            log(f"  {done[0]}/{len(jobs)} tiles")
        return job, im      # None = missing tile (no coverage / blocked)

    canvas = Image.new("RGB", ((c1 - c0 + 1) * m["tw"], (r1 - r0 + 1) * m["th"]))
    missing = 0
    with ThreadPoolExecutor(workers) as ex:
        for (rr, cc), im in ex.map(get, jobs):
            if im is None:
                missing += 1
            else:
                canvas.paste(im, ((cc - c0) * m["tw"], (rr - r0) * m["th"]))
    if missing:
        log(f"WARNING: {missing}/{len(jobs)} tiles missing (no coverage / blocked); they appear black.")
    box = (round((l - c0) * m["tw"]), round((t - r0) * m["th"]),
           round((r - c0) * m["tw"]), round((b - r0) * m["th"]))
    return canvas.crop(box)


def http_fetch(timeout=60, retries=3):
    import time
    import requests
    sess = requests.Session()
    sess.headers["User-Agent"] = "Mozilla/5.0 (mars-route-planner)"

    def fetch(url):
        last = None
        for attempt in range(retries):
            try:
                resp = sess.get(url, timeout=(10, timeout))
                if resp.status_code in (429, 500, 502, 503, 504):
                    raise requests.HTTPError(f"{resp.status_code} from server")
                resp.raise_for_status()          # 403/404 etc: no point retrying
                return resp.content
            except (requests.Timeout, requests.ConnectionError) as exc:
                last = exc
            except requests.HTTPError as exc:
                if exc.response is not None and exc.response.status_code < 429:
                    raise
                last = exc
            time.sleep(2 ** attempt)
        raise last

    return fetch


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", default="curiosity_ctx_mosaic")
    ap.add_argument("--bbox", nargs=4, type=float, metavar=("W", "S", "E", "N"),
                    default=[WEST, SOUTH, EAST, NORTH])
    ap.add_argument("--zoom", type=int)
    ap.add_argument("--max-width", type=int, default=2000)
    ap.add_argument("--api-key", help="e.g. DEMO_KEY or your own key from api.nasa.gov")
    ap.add_argument("--base", default=BASE, help="tile service root, if you use a different host")
    ap.add_argument("--assume-grid", action="store_true", help="skip the capabilities download")
    ap.add_argument("--timeout", type=int, default=60, help="read timeout per request (s)")
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--out", default="mars_patch.png")
    a = ap.parse_args()
    img = build_patch(a.layer, tuple(a.bbox), http_fetch(a.timeout), a.zoom, a.max_width,
                      api_key=a.api_key, base=a.base, assume_grid=a.assume_grid, workers=a.workers)
    img.save(a.out)
    print(f"saved {a.out}  {img.size}")