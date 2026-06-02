"""
location_pipeline.py — Build a 3D city model from a place name or coordinates.

This is the Phase 3 entry point. It chains together:
  1. Geocoding      — convert place name to lat/lon
  2. OSM fetch      — download real map polygons from OpenStreetMap
  3. DEM download   — download free elevation data
  4. CRS projection — convert lat/lon polygons to local metres
  5. GeoForge pipeline — build 3D geometry and export

Everything is logged so the viewer can stream progress to the browser.
"""
from __future__ import annotations

import logging
import tempfile
from pathlib import Path
from typing import Callable, List, Optional, Tuple

import geopandas as gpd
import numpy as np
from pyproj import CRS, Transformer
from shapely.geometry import box

from .dem_reader import DemSampler
from .exporters import export
from .geometry import Feature3D, build_feature
from .osm_fetch import fetch_city, geocode
from .config import LayerConfig, CLASS_DEFAULTS

log = logging.getLogger(__name__)

# Layer class → config defaults
_CLS_CFG = {
    cls: LayerConfig(path="", layer_class=cls,
                     height_source=d["height_source"],
                     base_source=d["base_source"],
                     min_height=d.get("min_height", 0.0),
                     offset=d.get("offset", 0.0))
    for cls, d in CLASS_DEFAULTS.items()
}
# Override building min_height
_CLS_CFG["building"].min_height = 3.0
_CLS_CFG["building"].height_field = "building_height"
_CLS_CFG["road"].offset = 0.05
_CLS_CFG["bridge"].offset = 0.3


def build_from_location(
    place:    str,
    radius_m: float = 500,
    out_dir:  Path  = None,
    log_cb:   Optional[Callable[[str], None]] = None,
) -> Tuple[List[Feature3D], Path]:
    """
    Full Phase 3 pipeline:
      place    — city name, address, or "lat,lon"
      radius_m — area radius in metres (250–2000 recommended)
      out_dir  — where to write output files
      log_cb   — callback for progress messages (used by the web server)

    Returns (features, output_directory).
    """
    def info(msg: str):
        log.info(msg)
        if log_cb:
            log_cb(msg)

    # ── Step 1: Geocode ──────────────────────────────────────────────────
    info(f"Geocoding '{place}' …")
    lat, lon = _parse_or_geocode(place)
    info(f"  Location: {lat:.5f}, {lon:.5f}")

    # ── Step 2: Fetch OSM data ───────────────────────────────────────────
    info(f"Fetching OpenStreetMap data (radius {radius_m}m) …")
    layers_gdf = fetch_city(lat, lon, radius_m)
    total_feats = sum(len(g) for g in layers_gdf.values())
    info(f"  {total_feats} OSM features across {len(layers_gdf)} layers")

    # ── Step 3: Project to local CRS (metres) ───────────────────────────
    info("Projecting to local coordinate system …")
    local_crs = _local_utm(lat, lon)
    layers_proj = {}
    for cls, gdf in layers_gdf.items():
        try:
            layers_proj[cls] = gdf.to_crs(local_crs)
        except Exception as e:
            info(f"  Warning: could not project {cls}: {e}")

    # ── Step 4: Download DEM ─────────────────────────────────────────────
    info("Downloading elevation data …")
    dem = DemSampler(lat, lon, radius_m=radius_m * 1.2, grid_pts=35)

    # Convert DEM local coords to projected CRS
    try:
        dem = _project_dem(dem, lat, lon, local_crs)
        dem.load()
        info(f"  DEM ready — z range: {dem._z.min():.1f}–{dem._z.max():.1f} m")
    except Exception as e:
        info(f"  DEM load failed ({e}) — using flat terrain")
        dem = _flat_dem(lat, lon, radius_m)

    # ── Step 5: Build 3D geometry ────────────────────────────────────────
    info("Building 3D geometry …")
    all_features: List[Feature3D] = []

    # Process terrain first (background)
    layer_order = ["terrain", "water", "road", "forest", "building", "bridge", "wall", "fence"]

    for cls in layer_order:
        gdf = layers_proj.get(cls)
        if gdf is None or len(gdf) == 0:
            continue

        cfg  = _CLS_CFG.get(cls, _CLS_CFG["terrain"])
        n_ok = 0

        for row in gdf.itertuples():
            geom = getattr(row, "geometry", None)
            if geom is None or geom.is_empty:
                continue
            fid   = getattr(row, "id", str(row.Index))
            props = {c: getattr(row, c) for c in gdf.columns
                     if c not in ("geometry",) and not c.startswith("_")}
            try:
                stats = dem.query_polygon(geom)
                feats = build_feature(fid, geom, cls, stats, cfg, dem, props)
                all_features.extend(feats)
                n_ok += 1
            except Exception as e:
                log.debug(f"  {cls} {fid}: {e}")

        info(f"  {cls}: {n_ok} features built")

    info(f"Total: {len(all_features)} 3D features")

    # ── Step 5.5: Centre all geometry at world origin ────────────────────
    # UTM coordinates are large numbers (e.g. X=400000, Y=1200000)
    # Shift everything so the model centre is at (0, 0, 0)
    # This is critical for WebGL rendering precision
    if all_features:
        all_verts = np.concatenate([f.vertices for f in all_features], axis=0)
        cx = float(all_verts[:, 0].mean())
        cy = float(all_verts[:, 1].mean())
        cz = float(all_verts[:, 2].mean())
        # Only shift XY (horizontal) — keep Z as real elevation
        # so height stats remain meaningful
        ground_z = float(all_verts[:, 2].min())
        info(f"Centring geometry (offset: {cx:.1f}, {cy:.1f}) …")
        for feat in all_features:
            feat.vertices[:, 0] -= cx
            feat.vertices[:, 1] -= cy
            feat.vertices[:, 2] -= ground_z
            feat.height_top  -= ground_z
            feat.height_base -= ground_z

    # ── Step 6: Export ───────────────────────────────────────────────────
    if out_dir is None:
        out_dir = Path(tempfile.mkdtemp(prefix="geoforge_"))
    out_dir.mkdir(parents=True, exist_ok=True)

    info("Exporting …")
    export(all_features, out_dir,
           ["obj", "cityjson", "citygml", "stl", "postgis", "csv"],
           crs=local_crs)
    info(f"✓ Done — outputs in {out_dir}")
    return all_features, out_dir


# ── Helpers ────────────────────────────────────────────────────────────────
def _parse_or_geocode(place: str) -> Tuple[float, float]:
    """Accept 'lat,lon' string or place name."""
    parts = place.replace(" ", "").split(",")
    if len(parts) == 2:
        try:
            return float(parts[0]), float(parts[1])
        except ValueError:
            pass
    return geocode(place)


def _local_utm(lat: float, lon: float) -> str:
    """Return the EPSG code of the UTM zone covering this point."""
    zone = int((lon + 180) / 6) + 1
    if lat >= 0:
        return f"EPSG:{32600 + zone}"
    else:
        return f"EPSG:{32700 + zone}"


def _project_dem(dem: DemSampler, lat: float, lon: float,
                 target_crs: str) -> DemSampler:
    """
    Wrap DemSampler so its XY coordinates are in target_crs (metres)
    instead of local equirectangular metres.
    """
    import math
    # Patch the load method to project after fetching
    original_load = dem.load

    def patched_load():
        original_load()
        # dem._xy is currently in local equirectangular metres
        # Convert back to lat/lon then project to target CRS
        cx    = math.cos(math.radians(lat))
        lons  = dem._xy[:, 0] / (111_320 * cx) + lon
        lats  = dem._xy[:, 1] / 111_320 + lat

        tf = Transformer.from_crs("EPSG:4326", target_crs, always_xy=True)
        xs, ys = tf.transform(lons, lats)
        dem._xy   = np.column_stack([xs, ys])
        from scipy.spatial import KDTree
        from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
        dem._tree = KDTree(dem._xy)
        dem._lin  = LinearNDInterpolator(dem._xy, dem._z)
        dem._nn   = NearestNDInterpolator(dem._xy, dem._z)
        return dem

    dem.load = patched_load
    return dem


def _flat_dem(lat: float, lon: float, radius_m: float) -> DemSampler:
    """Emergency fallback — flat terrain at 0 metres."""
    import math
    dem = DemSampler(lat, lon, radius_m, grid_pts=10)
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    lats = np.linspace(lat-dlat, lat+dlat, 10)
    lons = np.linspace(lon-dlon, lon+dlon, 10)
    glat, glon = np.meshgrid(lats, lons)
    cx = math.cos(math.radians(lat))
    x  = (glon.ravel() - lon) * 111_320 * cx
    y  = (glat.ravel() - lat) * 111_320
    dem._xy   = np.column_stack([x, y])
    dem._z    = np.zeros(len(x))
    from scipy.spatial import KDTree
    from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
    dem._tree = KDTree(dem._xy)
    dem._lin  = LinearNDInterpolator(dem._xy, dem._z)
    dem._nn   = NearestNDInterpolator(dem._xy, dem._z)
    return dem
