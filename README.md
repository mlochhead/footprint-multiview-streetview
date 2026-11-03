# Street View Images for Building Footprints

Download Google Street View images of buildings, given their footprints.

For each building, the notebook finds nearby Street View panoramas, throws out the ones that don't have a clear view of the building, and saves one image per remaining panorama with the camera pointed at the building. It records why each candidate view was kept or skipped.

## Files

| File | What it is |
|---|---|
| `download_images.ipynb` | The notebook you run. Edit the **INPUTS** cell, then run all cells. |
| `streetview_images.py` | Helper functions used by the notebook. |
| `Hayward_Test_Footprints.geojson` | Example input: 1,579 building footprints in one Hayward, CA neighborhood (census tract 06001436300). |

## Setup

**1. Install** (Python 3.9+):

```bash
pip install -r requirements.txt
```

**2. Get a Google Maps API key.** In the [Google Cloud Console](https://console.cloud.google.com/), create a project, enable billing, enable the **Street View Static API**, and create an API key under *APIs & Services > Credentials*.

**3. Give the notebook your API key.** The notebook reads the key from the `GOOGLE_MAPS_API_KEY` environment variable, so the key is never saved in the notebook. Set it in the same terminal you launch Jupyter from:

```bash
# macOS / Linux
export GOOGLE_MAPS_API_KEY="your-key-here"
jupyter notebook download_images.ipynb
```

```powershell
# Windows (PowerShell)
$env:GOOGLE_MAPS_API_KEY="your-key-here"
jupyter notebook download_images.ipynb
```

If you use VS Code or another editor, set the variable in that environment instead, or run `os.environ["GOOGLE_MAPS_API_KEY"] = "your-key-here"` in a cell *you don't save or commit*. Never commit your API key to GitHub.

**Cost:** looking up panoramas uses the Street View metadata endpoint, which is free. Each downloaded image with the `'api'` method is billed by Google under the Street View Static API. See [Google's pricing](https://developers.google.com/maps/billing-and-pricing/pricing). Start with a small `MAX_FOOTPRINTS` to check results and cost.

## Usage

1. Open `download_images.ipynb` and edit the **INPUTS** cell:
   - `ALL_FOOTPRINTS_PATH`: every footprint in and around the study area (used as obstacles for line-of-sight checks; include ~100 m beyond the buildings you want).
   - `NEEDED_FOOTPRINTS_PATH`: the buildings you want images of (can be the same file).
   - `ID_COL`: a unique building ID column present in both files.
   - `MAX_FOOTPRINTS`: limit the run for a quick test (`None` = all).
   - `DOWNLOAD_METHOD`: `'api'` (default) or `'brails'` (see below).
   - `SAVE_DIAGRAMS`: `True` to save a diagram for each building (default `False`).
2. Run all cells.

Footprints must be GeoJSON (or any format GeoPandas can read) with a CRS defined. Distances are computed in a UTM zone chosen automatically from the data, so the tool works anywhere.

### Outputs

Everything is written to `OUTPUT_DIR` (default `output/`):

- `images/<ID>_view<N>.jpg`: downloaded images. `N` is the sample point (0 to `N_SEARCH_POINTS - 1`).
- `image_info.csv`: one row per building per sample point (see columns below).
- `diagrams/<ID>.png` (only if `SAVE_DIAGRAMS = True`): a map of the building, nearby footprints, the requested sample points, and each panorama with its line of sight, colored by `download_tag`. Useful for checking the filters. Duplicate panoramas aren't drawn.
- `checkpoint.csv`: progress so far. If the run stops, re-run the notebook to continue where it left off. Delete this file to start over.

| Column | Meaning |
|---|---|
| `<ID_COL>` | Building ID |
| `view` | Sample point index (matches `_view<N>` in the image filename) |
| `pano_id` | Street View panorama ID |
| `distance_to_ftpt` | Distance (m) from the panorama to the nearest edge of the footprint |
| `min_line_of_sight_clearance` | Closest distance (m) between the line of sight and any other footprint |
| `image_year` | Panorama capture date, e.g. `2019-05` |
| `download_tag` | What happened (see below) |

### `download_tag` values

| Tag | Meaning |
|---|---|
| `downloaded` | Passed all filters; image saved. |
| `no_pano_found` | No Street View panorama near this sample point. |
| `duplicate_pano` | Same panorama as an earlier sample point for this building; skipped. |
| `intersects` | Line of sight from the panorama to the building crosses another footprint. |
| `too_far_away` | Panorama is farther than `MAX_DIST_TO_FTPT_M` (default 33 m) from the building. |
| `line_of_sight_too_close` | Line of sight passes within `MIN_LOS_CLEARANCE_M` (default 0.66 m) of another footprint. |
| `download_failed` | Passed all filters, but the download request failed (error is printed). |

## How it works

1. Place `N_SEARCH_POINTS` (default 8) points on a circle of `SEARCH_RADIUS_M` (default 15 m) around the building centroid.
2. For each point, look up the nearest outdoor Street View panorama.
3. Draw a line of sight from the panorama to the **nearest point on the building's edge**, and apply the filters in the table above against footprints within `NEIGHBOR_BUFFER_M` (default 100 m).
4. Download a 640x640 image pointed at the building **centroid**. The field of view depends on distance (closer = wider), set by `FOV_BY_DISTANCE_M` and `FOV_DEFAULT`.

Buildings are processed in parallel (`MAX_WORKERS`). The checkpoint is saved after each building.

## Download methods

### `'api'` (default, recommended)

Uses the official [Google Street View Static API](https://developers.google.com/maps/documentation/streetview). Requires an API key with billing enabled; billed per image.

### `'brails'`: multi-image modification of the BRAILS++ image download

An alternative that builds on the image download in [BRAILS++](https://github.com/NHERI-SimCenter/BrailsPlusPlus) (NHERI SimCenter, BSD 3-Clause). As in BRAILS++, it gets panorama metadata from Google Maps' `photometa` endpoint and stitches the full panorama from Google's tile endpoint. This version then reprojects the panorama into a perspective image at any heading and field of view, so several views can be cut from one panorama. It still needs an API key for the panorama lookup, but the images aren't billed.

> **Warning:** this method uses undocumented Google endpoints that are not part of the official Maps Platform APIs. Use at your own risk.

## Terms of use

You are responsible for following the [Google Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms), including the limits on storing and sharing Street View imagery. Don't redistribute downloaded images unless the terms allow it.

## Credits and license

- Code: BSD 3-Clause License, see [LICENSE](LICENSE).
- The `'brails'` download method is derived from [BRAILS++](https://github.com/NHERI-SimCenter/BrailsPlusPlus), Copyright (c) The Regents of the University of California, BSD 3-Clause License.
- Example footprints: building footprints for Hayward, CA, licensed separately from this code. <!-- TODO: add the data source and its license/attribution -->
