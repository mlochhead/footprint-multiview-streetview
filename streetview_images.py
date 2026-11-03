"""
Helper functions for downloading Google Street View images of building footprints.

Used by `download_images.ipynb`. The file has three parts:

  1. Geometry helpers       -- sample points around a building, compute headings
  2. Google Street View API -- pano lookup (free metadata endpoint) and the official Static Street View image download
  3. BRAILS-based download  -- a multi-image modification of the BRAILS++ image download
  4. Diagrams               -- optional map of each building's candidate views
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from io import BytesIO
import json

import numpy as np
import requests
from PIL import Image
from pyproj import Transformer
from requests.adapters import HTTPAdapter, Retry
from shapely.geometry import Point

REQUESTS_TIMEOUT_S = 30


# =============================================================================
# 1. Geometry helpers
# =============================================================================

def generate_surrounding_points(centroid: Point, crs_metric, radius_m=15, n_points=8):
    """
    Generate `n_points` evenly spaced on a circle of `radius_m` around a centroid.

    Args:
        centroid:   Building centroid, in the projected (meters) CRS `crs_metric`.
        crs_metric: The projected CRS the centroid is in (e.g. 'EPSG:3310' or a UTM zone).
        radius_m:   Circle radius in meters.
        n_points:   Number of points on the circle.

    Returns:
        List of dicts with 'lat' and 'lon' (WGS84) for each point.
    """
    to_latlon = Transformer.from_crs(crs_metric, "EPSG:4326", always_xy=True)
    angles = np.radians(np.linspace(0, 360, n_points, endpoint=False))

    points = []
    for a in angles:
        lon, lat = to_latlon.transform(centroid.x + radius_m * np.cos(a),
                                       centroid.y + radius_m * np.sin(a))
        points.append({'lat': lat, 'lon': lon})
    return points


def compute_heading(from_lat, from_lon, to_lat, to_lon):
    """Compass heading (degrees, 0 = north, clockwise) from one lat/lon point to another."""
    delta_lon = np.radians(to_lon - from_lon)
    lat1 = np.radians(from_lat)
    lat2 = np.radians(to_lat)

    x = np.sin(delta_lon) * np.cos(lat2)
    y = np.cos(lat1) * np.sin(lat2) - np.sin(lat1) * np.cos(lat2) * np.cos(delta_lon)
    return (np.degrees(np.arctan2(x, y)) + 360) % 360


# =============================================================================
# 2. Google Street View API (official, requires an API key)
# =============================================================================

METADATA_URL = 'https://maps.googleapis.com/maps/api/streetview/metadata'
STATIC_IMAGE_URL = 'https://maps.googleapis.com/maps/api/streetview'


def get_pano(latlon: tuple[float, float], api_key: str) -> dict:
    """
    Find the nearest outdoor Street View panorama to a lat/lon point.

    Uses the Street View metadata endpoint, which does not incur image charges.

    Args:
        latlon:  (lat, lon) of the point to search from.
        api_key: Google Maps Platform API key.

    Returns:
        dict with:
            - 'pano_id' (str):           Panorama ID.
            - 'location' (lat, lon):     Where the panorama was captured.
            - 'date' (str):              Capture date, e.g. '2019-05' ('NA' if missing).

    Raises:
        ValueError: if no panorama is found near the point.
    """
    params = {
        'location': f'{latlon[0]},{latlon[1]}',
        'key': api_key,
        'source': 'outdoor',
    }
    response = requests.get(METADATA_URL, params=params, timeout=REQUESTS_TIMEOUT_S)
    response.raise_for_status()
    data = response.json()

    if data.get('status') != 'OK':
        raise ValueError(f"No pano found at {latlon}: {data.get('status')}")

    loc = data['location']
    return {
        'pano_id': data['pano_id'],
        'location': (loc['lat'], loc['lng']),
        'date': data.get('date', 'NA'),
    }


def download_street_view_api(pano_id: str, heading: float, api_key: str, filename: str,
                             fov=60, pitch=0, size=(640, 640)) -> None:
    """
    Download one image with the Google Static Street View API (billed per image).

    Args:
        pano_id:  Panorama ID.
        heading:  Compass direction to look in (degrees).
        api_key:  Google Maps Platform API key.
        filename: Path to save the image (.jpg).
        fov:      Horizontal field of view in degrees (10-120).
        pitch:    Up/down angle in degrees (-90 to 90).
        size:     (width, height) in pixels; 640x640 is the maximum on the standard plan.

    Raises:
        requests.HTTPError: if the download fails.
    """
    params = {
        'size': f'{size[0]}x{size[1]}',
        'pano': pano_id,
        'heading': heading,
        'fov': fov,
        'pitch': pitch,
        'key': api_key,
    }
    response = requests.get(STATIC_IMAGE_URL, params=params, timeout=REQUESTS_TIMEOUT_S)
    response.raise_for_status()
    with open(filename, 'wb') as f:
        f.write(response.content)


# =============================================================================
# 3. BRAILS-based download (multi-image modification of the BRAILS++ image download)
# =============================================================================
#
# Origin: this approach comes from BRAILS++ (NHERI SimCenter), specifically
# `brails/scrapers/google_streetview/google_streetview.py`:
#     https://github.com/NHERI-SimCenter/BrailsPlusPlus
# BRAILS++ fetches panorama metadata from Google Maps' `photometa` endpoint and
# stitches the full panorama from Google's internal tile endpoint, instead of
# using the official Static Street View API. Modifications made here:
#   - looks up per-panorama dimensions instead of assuming them
#   - uses the `streetviewpixels-pa.googleapis.com` tile endpoint with
#     browser-style request headers
#   - reprojects the panorama to a perspective image at any heading/FOV/pitch,
#     so several views can be cut from one panorama
#
# These endpoints are not part of the official Google Maps Platform APIs.
# and may stop working at any time. The official API download above is 
# the default and recommended method.
#
# Portions of this section are derived from BRAILS++:
#
# Copyright (c) 2024 The Regents of the University of California
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice,
# this list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
# this list of conditions and the following disclaimer in the documentation
# and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
# may be used to endorse or promote products derived from this software without
# specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

TILE_SIZE = 512
PHOTOMETA_URL = 'https://www.google.com/maps/photometa/v1'
TILE_URL_TEMPLATE = (
    'https://streetviewpixels-pa.googleapis.com/v1/tile'
    '?cb_client=maps_sv.tactile&panoid={pano_id}&x={x}&y={y}&zoom={zoom}&nbt=1&fover=2'
)

RETRY_STRATEGY = Retry(total=5, backoff_factor=0.5, status_forcelist=[429, 500, 502, 503, 504])

BROWSER_HEADERS = {
    "Origin": "https://www.google.com",
    "Referer": "https://www.google.com/",
    "User-Agent": "Mozilla/5.0 (Windows NT 11.0; Win64; x64; rv:151.0) Gecko/20100101 Firefox/151.0",
}


def _make_session() -> requests.Session:
    """requests session with retries and browser-style headers."""
    session = requests.Session()
    session.headers.update(BROWSER_HEADERS)
    session.mount("https://", HTTPAdapter(max_retries=RETRY_STRATEGY))
    return session


def _get_pano_metadata(pano_id: str, zoom: int) -> dict:
    """
    Get the camera heading and panorama pixel size at `zoom` from `photometa`.

    Both vary per panorama: the panorama's center column faces the camera's
    capture heading (not north), and the tile grid size differs between panos.
    The `pb` request string and response indexing follow BRAILS++.
    """
    params = {
        'authuser': '0',
        'hl': 'en',
        'gl': 'us',
        'pb': (
            '!1m4!1smaps_sv.tactile!11m2!2m1!1b1!2m2!1sen!2suk!3m3!1m2!'
            '1e2!2s' + pano_id +
            '!4m57!1e1!1e2!1e3!1e4!1e5!1e6!1e8!'
            '1e12!2m1!1e1!4m1!1i48!5m1!1e1!5m1!1e2!6m1!1e1!6m1!1e2!'
            '9m36!1m3!1e2!2b1!3e2!1m3!1e2!2b0!3e3!1m3!1e3!2b1!3e2!1m3!'
            '1e3!2b0!3e3!1m3!1e8!2b0!3e3!1m3!1e1!2b0!3e3!1m3!1e4!2b0!'
            '3e3!1m3!1e10!2b1!3e2!1m3!1e10!2b0!3e3'
        ),
    }
    response = _make_session().get(PHOTOMETA_URL, params=params, timeout=REQUESTS_TIMEOUT_S)
    response.raise_for_status()
    try:
        data = json.loads(response.content[4:])  # response starts with a 4-byte junk prefix
        cam_heading = data[1][0][5][0][1][2][0]
        pano_w, pano_h = tuple(data[1][0][2][3][0][zoom][0])[::-1]
    except (KeyError, TypeError, IndexError) as e:
        raise ValueError(f"Could not read metadata for pano {pano_id} at zoom {zoom}: {e}")

    return {
        'cam_heading': cam_heading,
        'pano_w': pano_w,
        'pano_h': pano_h,
        'tiles_x': pano_w // TILE_SIZE,
        'tiles_y': pano_h // TILE_SIZE,
    }


def _download_tiles(urls: list[str]) -> list[Image.Image]:
    """Download panorama tiles in parallel; returns images in the same order as `urls`."""
    session = _make_session()
    results = {}
    with ThreadPoolExecutor() as executor:
        futures = {executor.submit(session.get, url, timeout=REQUESTS_TIMEOUT_S): i
                   for i, url in enumerate(urls)}
        for future in as_completed(futures):
            response = future.result()
            response.raise_for_status()
            results[futures[future]] = Image.open(BytesIO(response.content))
    return [results[i] for i in range(len(urls))]


def _equirect_to_perspective(panorama: Image.Image, heading: float, cam_heading: float,
                             fov: float, pitch: float, output_size: tuple[int, int]) -> Image.Image:
    """
    Reproject part of an equirectangular panorama into a perspective (pinhole camera) image.

    A plain rectangular crop of an equirectangular panorama bends straight lines,
    so instead each output pixel casts a ray from a virtual camera, finds where it
    hits the panorama sphere, and samples that pixel (bilinear interpolation).

    Args:
        panorama:    Full stitched equirectangular panorama.
        heading:     Compass heading to look in (degrees).
        cam_heading: Heading of the panorama's center column (from photometa).
        fov:         Horizontal field of view (degrees, 10-120).
        pitch:       Vertical tilt (degrees, -90 to 90).
        output_size: (width, height) of the output image.
    """
    pano_w, pano_h = panorama.size
    out_w, out_h = output_size

    fov_rad = np.radians(np.clip(fov, 10, 120))
    pitch_rad = np.radians(np.clip(pitch, -90, 90))

    # Camera-space ray for every output pixel (x=right, y=up, z=forward)
    xv, yv = np.meshgrid(np.linspace(-1, 1, out_w), np.linspace(-1, 1, out_h))
    f = 1.0 / np.tan(fov_rad / 2)
    ray_x, ray_y, ray_z = xv, -yv, np.full_like(xv, f)
    norm = np.sqrt(ray_x**2 + ray_y**2 + ray_z**2)
    ray_x, ray_y, ray_z = ray_x / norm, ray_y / norm, ray_z / norm

    # Pitch: rotate around the x-axis
    cos_p, sin_p = np.cos(pitch_rad), np.sin(pitch_rad)
    ray_y, ray_z = ray_y * cos_p - ray_z * sin_p, ray_y * sin_p + ray_z * cos_p

    # Heading: rotate around the y-axis, relative to the panorama's center heading
    h = np.radians(heading - cam_heading)
    cos_h, sin_h = np.cos(h), np.sin(h)
    ray_x, ray_z = ray_x * cos_h + ray_z * sin_h, -ray_x * sin_h + ray_z * cos_h

    # Ray direction -> (lon, lat) on the sphere -> panorama pixel coordinates
    lon = np.arctan2(ray_x, ray_z)
    lat = np.arcsin(np.clip(ray_y, -1, 1))
    src_x = (((lon / (2 * np.pi)) + 0.5) * pano_w) % pano_w
    src_y = np.clip((0.5 - lat / np.pi) * pano_h, 0, pano_h - 1)

    # Bilinear interpolation
    x0 = np.floor(src_x).astype(int) % pano_w
    y0 = np.floor(src_y).astype(int)
    x1 = (x0 + 1) % pano_w
    y1 = np.clip(y0 + 1, 0, pano_h - 1)
    wx = (src_x - np.floor(src_x))[..., np.newaxis]
    wy = (src_y - np.floor(src_y))[..., np.newaxis]

    pano = np.array(panorama, dtype=np.float32)
    out = (pano[y0, x0] * (1 - wx) * (1 - wy) +
           pano[y0, x1] * wx * (1 - wy) +
           pano[y1, x0] * (1 - wx) * wy +
           pano[y1, x1] * wx * wy)
    return Image.fromarray(np.uint8(np.clip(out, 0, 255)))


def download_street_view_brails(pano_id: str, heading: float, filename: str, fov: float = 60,
                                pitch: float = 0, zoom: int = 4,
                                output_size: tuple[int, int] = (640, 640)) -> None:
    """
    Download one view using the BRAILS-based method (see the warning above).

    Stitches the full panorama from tiles, then reprojects it to a perspective
    image looking in `heading`. Does not use the billed Static API.

    Args:
        pano_id:     Panorama ID.
        heading:     Compass direction to look in (degrees).
        filename:    Path to save the image.
        fov:         Horizontal field of view in degrees (10-120).
        pitch:       Up/down angle in degrees (-90 to 90).
        zoom:        Tile zoom level (higher = larger panorama, more tiles).
        output_size: (width, height) of the saved image.
    """
    meta = _get_pano_metadata(pano_id, zoom)

    urls, offsets = [], []
    for x in range(meta['tiles_x']):
        for y in range(meta['tiles_y']):
            urls.append(TILE_URL_TEMPLATE.format(pano_id=pano_id, x=x, y=y, zoom=zoom))
            offsets.append((x * TILE_SIZE, y * TILE_SIZE))

    panorama = Image.new('RGB', (meta['pano_w'], meta['pano_h']))
    for tile, offset in zip(_download_tiles(urls), offsets):
        panorama.paste(tile, offset)

    image = _equirect_to_perspective(panorama, heading, meta['cam_heading'], fov, pitch, output_size)
    image.save(filename)


# =============================================================================
# 4. Diagrams (optional)
# =============================================================================

# Colors for each download_tag in the diagrams
TAG_COLORS = {
    'downloaded': 'tab:green',
    'intersects': 'tab:red',
    'too_far_away': 'tab:orange',
    'line_of_sight_too_close': 'tab:purple',
    'download_failed': 'black',
    'duplicate_pano': 'tab:gray',
}


def plot_download_diagram(footprint, other_footprints, sample_points, panos, crs_metric,
                          title: str, filename: str, view_extent_m: float = 50,
                          lines_to: str = 'centroid') -> None:
    """
    Save a map of one building showing where views were requested, where the
    panoramas actually were, and why each was kept or skipped.

    Uses matplotlib's object-oriented API (no pyplot), so it is safe to call
    from multiple threads.

    Args:
        footprint:        Building footprint geometry, in `crs_metric`.
        other_footprints: GeoDataFrame of nearby footprints, in `crs_metric`.
        sample_points:    Output of `generate_surrounding_points` (lat/lon dicts).
        panos:            List of dicts with 'point' (pano location, in `crs_metric`),
                          'target' (point on the footprint the line of sight goes to,
                          or None) and 'tag' (download_tag).
        crs_metric:       Projected CRS (meters) of the geometries.
        title:            Plot title.
        filename:         Path to save the .png.
        view_extent_m:    Half-width of the plotted area around the centroid (meters).
        lines_to:         Where each panorama's line is drawn to: 'centroid' (the
                          footprint centroid, where the camera points; default) or
                          'nearest' (the closest point on the footprint edge, which
                          is what the line-of-sight filters check).
    """
    if lines_to not in ('centroid', 'nearest'):
        raise ValueError("lines_to must be 'centroid' or 'nearest'")

    from matplotlib.figure import Figure
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    def draw_polygon(geom, **style):
        # Polygons are drawn directly (not with GeoDataFrame.plot, which uses pyplot)
        for poly in getattr(geom, 'geoms', [geom]):
            x, y = poly.exterior.xy
            ax.fill(x, y, **style)

    fig = Figure(figsize=(6, 6))
    ax = fig.add_subplot()

    # Footprints
    for geom in other_footprints.geometry:
        draw_polygon(geom, facecolor='lightgrey', edgecolor='black', alpha=0.3)
    draw_polygon(footprint, facecolor='lightsteelblue', edgecolor='black')
    centroid = footprint.centroid
    ax.plot(centroid.x, centroid.y, 'k*', markersize=12)

    # Requested sample points
    to_metric = Transformer.from_crs("EPSG:4326", crs_metric, always_xy=True)
    sx, sy = zip(*(to_metric.transform(p['lon'], p['lat']) for p in sample_points))
    ax.plot(sx, sy, 'bx', markersize=7)

    # Panoramas and their lines of sight, colored by download_tag
    tags_used = []
    for p in panos:
        color = TAG_COLORS.get(p['tag'], 'tab:gray')
        end = centroid if lines_to == 'centroid' else p['target']
        if end is not None:
            ax.plot([p['point'].x, end.x], [p['point'].y, end.y],
                    color=color, linestyle='--', linewidth=1.5)
        ax.plot(p['point'].x, p['point'].y, 'o', color=color, markersize=7)
        if p['tag'] not in tags_used:
            tags_used.append(p['tag'])

    # Legend
    handles = [
        Patch(facecolor='lightsteelblue', edgecolor='black', label='Building'),
        Patch(facecolor='lightgrey', edgecolor='black', alpha=0.3, label='Other footprints'),
        Line2D([], [], marker='*', color='k', linestyle='', markersize=12, label='Centroid'),
        Line2D([], [], marker='x', color='b', linestyle='', label='Requested points'),
    ] + [
        Line2D([], [], marker='o', color=TAG_COLORS.get(t, 'tab:gray'), linestyle='--', label=f'Pano: {t}')
        for t in tags_used
    ]
    ax.legend(handles=handles, loc='upper left', bbox_to_anchor=(1.02, 1), fontsize=8)

    ax.set_xlim(centroid.x - view_extent_m, centroid.x + view_extent_m)
    ax.set_ylim(centroid.y - view_extent_m, centroid.y + view_extent_m)
    ax.set_aspect('equal')
    ax.set_xticks([])
    ax.set_yticks([])
    ax.set_title(title)

    fig.savefig(filename, dpi=200, bbox_inches='tight')
