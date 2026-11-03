# Street View Images for Building Footprints

Based on building footprint geometry, this code downloads multiple street view images per footprint (if available). 

For each building footprint, the notebook finds nearby Street View panoramas, uses a series of filters to remove poor-quality or misleading views, and saves one image per remaining panorama with the camera pointed at the building. 

## Files

- `download_images.ipynb`: notebook used to download images.
- `streetview_images.py`: helper functions used by the notebook.
- `example_footprints.geojson`: example input footprints from Hayward, CA. 

## Setup

1. Install the requirements (Python 3.9+):

   ```bash
   pip install -r requirements.txt
   ```

2. Get a Google Maps API key. In the [Google Cloud Console](https://console.cloud.google.com/), create a project, enable billing, enable the Street View Static API, and create an API key under APIs & Services > Credentials.

3. Give the notebook your API key. The notebook reads the key from the `GOOGLE_MAPS_API_KEY` environment variable, so the key is never saved in the notebook. Set it in the same terminal you launch Jupyter from:

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

   If you use VS Code or another editor, set the variable in that environment instead, or run `os.environ["GOOGLE_MAPS_API_KEY"] = "your-key-here"` in a cell you don't save or commit. Never commit your API key to GitHub.

Cost: looking up panoramas uses the Street View metadata endpoint, which is free. Each downloaded image with the `'api'` method is billed by Google under the Street View Static API. See [Google's pricing](https://developers.google.com/maps/billing-and-pricing/pricing). Start with a small `MAX_FOOTPRINTS` to check results and cost.

## Input

File containing footprints of the buildings you want images of, as a GeoJSON file (or any format GeoPandas can read) with a CRS defined.

## Outputs

- `images/`: the downloaded Street View images.
- `image_info.csv`: one row per candidate view of each building, with the panorama ID, capture date, distances, and a `download_tag` saying whether the image was downloaded or why it was skipped.
- `diagrams/` (optional): a map for each building showing its footprint, nearby panoramas, and their lines of sight.

Possible `download_tag` values in `image_info.csv`:

- `downloaded`: passed all filters; image saved.
- `no_pano_found`: no Street View panorama near this sample point.
- `duplicate_pano`: same panorama as an earlier sample point for this building; skipped.
- `intersects`: line of sight from the panorama to the building crosses another footprint.
- `too_far_away`: panorama is farther than `MAX_DIST_TO_FTPT_M` (default 33 m) from the building.
- `line_of_sight_too_close`: line of sight passes within `MIN_LOS_CLEARANCE_M` (default 0.66 m) of another footprint.
- `download_failed`: passed all filters, but the download request failed (error is printed).

## How it works

1. Place `N_SEARCH_POINTS` (default 8) points on a circle of `SEARCH_RADIUS_M` (default 15 m) around the building centroid.
2. For each point, look up the nearest outdoor Street View panorama.
3. Draw a line of sight from the panorama to the nearest point on the building's edge, and apply the filters listed above against footprints within `NEIGHBOR_BUFFER_M` (default 100 m).
4. Download a 640x640 image pointed at the building centroid. The field of view depends on distance (closer = wider), set by `FOV_BY_DISTANCE_M` and `FOV_DEFAULT`.


## Download methods

- `'api'` (default, recommended): uses the official [Google Street View Static API](https://developers.google.com/maps/documentation/streetview). Requires an API key with billing enabled; billed per image.
- `'brails'` (multi-image modification of the BRAILS++ image download): an alternative that builds on the image download in [BRAILS++](https://github.com/NHERI-SimCenter/BrailsPlusPlus) (NHERI SimCenter, BSD 3-Clause). As in BRAILS++, it gets panorama metadata from Google Maps' `photometa` endpoint and stitches the full panorama from Google's tile endpoint. This version then reprojects the panorama into a perspective image at any heading and field of view, so several views can be cut from one panorama. It still needs an API key for the panorama lookup, but the images aren't billed. Note: this method uses undocumented Google endpoints that are not part of the official Maps Platform APIs. Use at your own risk.

## Terms of use

You are responsible for following the [Google Maps Platform Terms of Service](https://cloud.google.com/maps-platform/terms), including the limits on storing and sharing Street View imagery. Don't redistribute downloaded images unless the terms allow it.

## Citation

The image download setup and filtering thresholds come from the following citation: 

Lochhead, M., Deierlein, G., & Armeni, I. (2026). Residential Seismic Vulnerability Identification using Large Vision and Language Models. engrXiv. https://doi.org/10.31224/8396

```bibtex
@misc{lochhead2026residential,
  title     = {Residential Seismic Vulnerability Identification using Large Vision and Language Models},
  author    = {Lochhead, Meredith and Deierlein, Gregory and Armeni, Iro},
  year      = {2026},
  publisher = {engrXiv},
  doi       = {10.31224/8396},
  url       = {https://doi.org/10.31224/8396}
}
```

## Credits and license

- Code: BSD 3-Clause License, see [LICENSE](LICENSE).
- The `'brails'` download method is derived from [BRAILS++](https://github.com/NHERI-SimCenter/BrailsPlusPlus), Copyright (c) The Regents of the University of California, BSD 3-Clause License.