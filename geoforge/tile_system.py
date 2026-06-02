"""
tile_system.py — Phase 4 tile streaming engine.

Divides the world into 500m x 500m tiles identified by (zoom, tx, ty).
Each tile is built independently and cached to disk.

Flow:
  1. Camera moves → viewer sends new camera centre to /api/tiles/update
  2. TileManager computes which tiles are visible
  3. Missing tiles go into a priority queue (nearest first)
  4. Background worker threads build tiles from OSM + DEM data
  5. Built tiles are cached to disk (survive server restarts)
  6. Viewer polls /api/tiles/ready to pick up newly built tiles
  7. Tiles far from camera are marked for unload to save memory
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from queue import PriorityQueue
from typing import Dict, List, Optional, Set, Tuple

log = logging.getLogger(__name__)

# ── Tile size in metres at each zoom level ─────────────────────────────────
TILE_SIZE_M = {
    0: 2000,   # city overview
    1: 1000,   # district
    2: 500,    # neighbourhood  ← default
    3: 250,    # block
}
DEFAULT_ZOOM = 2

# How many tiles to keep loaded around the camera
LOAD_RADIUS   = 2    # tiles in each direction = (2*r+1)^2 = 25 tiles max
UNLOAD_RADIUS = 4    # tiles beyond this are evicted from scene

# Background worker threads
N_WORKERS = 2


@dataclass(order=True)
class TileJob:
    """A queued tile build job, ordered by distance from camera."""
    priority: float
    tile_id:  str = field(compare=False)
    lat:      float = field(compare=False)
    lon:      float = field(compare=False)
    zoom:     int   = field(compare=False)
    tx:       int   = field(compare=False)
    ty:       int   = field(compare=False)


class TileManager:
    """
    Manages the tile grid, build queue, cache, and worker threads.
    One instance lives for the lifetime of the server.
    """

    def __init__(self, cache_dir: Path):
        self.cache_dir    = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)

        self._queue:   PriorityQueue = PriorityQueue()
        self._queued:  Set[str]      = set()      # tile_ids in queue
        self._built:   Dict[str, dict]= {}         # tile_id → tile data
        self._building: Set[str]     = set()      # currently building
        self._lock     = threading.Lock()

        # Camera state
        self._cam_lat  = 0.0
        self._cam_lon  = 0.0
        self._zoom     = DEFAULT_ZOOM
        self._active   = False

        # Start background workers
        for i in range(N_WORKERS):
            t = threading.Thread(target=self._worker, daemon=True, name=f"tile-worker-{i}")
            t.start()
        log.info(f"TileManager started — {N_WORKERS} workers, cache: {cache_dir}")

    # ── Camera update ──────────────────────────────────────────────────────
    def set_camera(self, lat: float, lon: float, zoom: int = DEFAULT_ZOOM):
        """Called when the user pans. Queues tiles around new position."""
        self._cam_lat = lat
        self._cam_lon = lon
        self._zoom    = max(0, min(zoom, 3))
        self._active  = True
        self._queue_visible_tiles()

    # ── Tile coordinate math ───────────────────────────────────────────────
    def _lat_lon_to_tile(self, lat: float, lon: float,
                         zoom: int) -> Tuple[int, int]:
        """Convert lat/lon to tile grid coordinates."""
        size_deg = TILE_SIZE_M[zoom] / 111_320
        tx = int(math.floor(lon / size_deg))
        ty = int(math.floor(lat / size_deg))
        return tx, ty

    def _tile_centre(self, tx: int, ty: int,
                     zoom: int) -> Tuple[float, float]:
        """Return lat/lon centre of a tile."""
        size_deg = TILE_SIZE_M[zoom] / 111_320
        lat = (ty + 0.5) * size_deg
        lon = (tx + 0.5) * size_deg
        return lat, lon

    def _tile_id(self, tx: int, ty: int, zoom: int) -> str:
        return f"{zoom}_{tx}_{ty}"

    # ── Queue visible tiles ────────────────────────────────────────────────
    def _queue_visible_tiles(self):
        cam_tx, cam_ty = self._lat_lon_to_tile(
            self._cam_lat, self._cam_lon, self._zoom)

        for dx in range(-LOAD_RADIUS, LOAD_RADIUS + 1):
            for dy in range(-LOAD_RADIUS, LOAD_RADIUS + 1):
                tx    = cam_tx + dx
                ty    = cam_ty + dy
                tid   = self._tile_id(tx, ty, self._zoom)
                dist  = math.sqrt(dx*dx + dy*dy)

                with self._lock:
                    # Skip if already built or queued or building
                    if tid in self._built:
                        continue
                    if tid in self._queued:
                        continue
                    if tid in self._building:
                        continue

                    # Check disk cache
                    cached = self._load_cache(tid)
                    if cached:
                        self._built[tid] = cached
                        continue

                    # Queue for building
                    lat, lon = self._tile_centre(tx, ty, self._zoom)
                    job = TileJob(
                        priority = dist,
                        tile_id  = tid,
                        lat      = lat,
                        lon      = lon,
                        zoom     = self._zoom,
                        tx       = tx,
                        ty       = ty,
                    )
                    self._queue.put(job)
                    self._queued.add(tid)
                    log.debug(f"Queued tile {tid} (dist={dist:.1f})")

    # ── Background worker ──────────────────────────────────────────────────
    def _worker(self):
        """Continuously picks jobs from the queue and builds tiles."""
        while True:
            try:
                job = self._queue.get(timeout=1)
            except Exception:
                continue

            with self._lock:
                self._queued.discard(job.tile_id)
                if job.tile_id in self._built:
                    self._queue.task_done()
                    continue
                self._building.add(job.tile_id)

            try:
                log.info(f"Building tile {job.tile_id} "
                         f"({job.lat:.4f}, {job.lon:.4f}) zoom={job.zoom}")
                tile_data = self._build_tile(job)

                with self._lock:
                    self._built[job.tile_id] = tile_data
                    self._building.discard(job.tile_id)

                self._save_cache(job.tile_id, tile_data)
                log.info(f"Tile {job.tile_id} ready — "
                         f"{tile_data.get('n_features', 0)} features")

            except Exception as e:
                log.error(f"Tile {job.tile_id} failed: {e}")
                with self._lock:
                    self._building.discard(job.tile_id)
                # Put an error tile so we don't keep retrying
                with self._lock:
                    self._built[job.tile_id] = {
                        "tile_id": job.tile_id,
                        "status":  "error",
                        "error":   str(e),
                        "lat":     job.lat,
                        "lon":     job.lon,
                        "zoom":    job.zoom,
                    }

            self._queue.task_done()

    # ── Tile build ─────────────────────────────────────────────────────────
    def _build_tile(self, job: TileJob) -> dict:
        """Build one tile from OSM + DEM data."""
        from .osm_fetch import fetch_city
        from .dem_reader import DemSampler
        from .geometry import build_feature
        from .config import CLASS_DEFAULTS, LayerConfig
        from .exporters import _write_cityjson
        import geopandas as gpd
        import tempfile

        zoom        = job.zoom
        radius_m    = TILE_SIZE_M[zoom] * 0.7   # slightly larger than tile

        # ── Fetch OSM data ─────────────────────────────────────────────
        layers_gdf = fetch_city(job.lat, job.lon, radius_m)

        # ── Project to local UTM ───────────────────────────────────────
        zone = int((job.lon + 180) / 6) + 1
        crs  = f"EPSG:{32600 + zone}" if job.lat >= 0 else f"EPSG:{32700 + zone}"
        layers_proj = {}
        for cls, gdf in layers_gdf.items():
            try:
                layers_proj[cls] = gdf.to_crs(crs)
            except Exception:
                pass

        # ── DEM ────────────────────────────────────────────────────────
        try:
            from .location_pipeline import _project_dem
            dem = DemSampler(job.lat, job.lon,
                             radius_m=radius_m * 1.1, grid_pts=20)
            dem = _project_dem(dem, job.lat, job.lon, crs)
            dem.load()
        except Exception as e:
            log.warning(f"DEM failed for {job.tile_id}: {e} — using flat")
            from .location_pipeline import _flat_dem
            dem = _flat_dem(job.lat, job.lon, radius_m)

        # ── Build geometry ─────────────────────────────────────────────
        CLASS_DEFAULTS_LOCAL = {
            cls: LayerConfig(
                path="", layer_class=cls,
                height_source=d["height_source"],
                base_source=d["base_source"],
                min_height=d.get("min_height", 0.0),
                offset=d.get("offset", 0.0),
            )
            for cls, d in CLASS_DEFAULTS.items()
        }
        CLASS_DEFAULTS_LOCAL["building"].min_height   = 3.0
        CLASS_DEFAULTS_LOCAL["building"].height_field = "building_height"
        CLASS_DEFAULTS_LOCAL["road"].offset    = 0.05
        CLASS_DEFAULTS_LOCAL["bridge"].offset  = 0.3

        features = []
        order = ["terrain","water","road","forest","building","bridge","wall","fence"]
        for cls in order:
            gdf = layers_proj.get(cls)
            if gdf is None or len(gdf) == 0:
                continue
            cfg = CLASS_DEFAULTS_LOCAL.get(cls, CLASS_DEFAULTS_LOCAL["terrain"])
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
                    features.extend(feats)
                except Exception:
                    pass

        # ── Serialise to CityJSON dict ─────────────────────────────────
        cj = _features_to_cityjson(features, crs)
        cj["tile_id"]    = job.tile_id
        cj["lat"]        = job.lat
        cj["lon"]        = job.lon
        cj["zoom"]       = job.zoom
        cj["tile_size"]  = TILE_SIZE_M[zoom]
        cj["n_features"] = len(features)
        cj["status"]     = "ok"
        return cj

    # ── CityJSON serialiser ────────────────────────────────────────────────
    # ── Cache ──────────────────────────────────────────────────────────────
    def _cache_path(self, tile_id: str) -> Path:
        return self.cache_dir / f"{tile_id}.json"

    def _save_cache(self, tile_id: str, data: dict):
        try:
            p = self._cache_path(tile_id)
            p.write_text(json.dumps(data), encoding="utf-8")
        except Exception as e:
            log.warning(f"Cache write failed for {tile_id}: {e}")

    def _load_cache(self, tile_id: str) -> Optional[dict]:
        p = self._cache_path(tile_id)
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            log.debug(f"Cache hit: {tile_id}")
            return data
        except Exception:
            return None

    # ── Public API ─────────────────────────────────────────────────────────
    def get_ready_tiles(self, known_ids: List[str]) -> List[dict]:
        """Return tiles that are built but not yet known to the viewer."""
        with self._lock:
            return [
                v for k, v in self._built.items()
                if k not in known_ids and v.get("status") == "ok"
            ]

    def get_status(self) -> dict:
        with self._lock:
            return {
                "built":    len(self._built),
                "building": len(self._building),
                "queued":   self._queue.qsize(),
                "zoom":     self._zoom,
                "cam_lat":  self._cam_lat,
                "cam_lon":  self._cam_lon,
            }

    def clear_cache(self):
        """Delete all cached tiles."""
        for f in self.cache_dir.glob("*.json"):
            f.unlink()
        with self._lock:
            self._built.clear()
            self._queued.clear()
            self._building.clear()
        log.info("Tile cache cleared")


# ── CityJSON feature serialiser ────────────────────────────────────────────
def _features_to_cityjson(features, crs: str) -> dict:
    """Convert Feature3D list to a CityJSON-compatible dict."""
    from .exporters import CITYJSON_TYPES
    import numpy as np

    v_idx, v_list = {}, []

    def add_v(pt):
        key = (round(float(pt[0]), 3), round(float(pt[1]), 3), round(float(pt[2]), 3))
        if key not in v_idx:
            v_idx[key] = len(v_list)
            v_list.append(list(key))
        return v_idx[key]

    city_objects = {}
    for feat in features:
        boundaries = []
        for tri in feat.faces:
            boundaries.append([[add_v(feat.vertices[i]) for i in tri]])

        oid = str(feat.feature_id)
        n   = 0
        while oid in city_objects:
            n += 1
            oid = f"{feat.feature_id}_{n}"

        city_objects[oid] = {
            "type":     CITYJSON_TYPES.get(feat.layer_class, "GenericCityObject"),
            "geometry": [{"type": "MultiSurface", "lod": "1", "boundaries": boundaries}],
            "attributes": {
                "source_id":   feat.feature_id,
                "layer_class": feat.layer_class,
                "height":      round(feat.height, 2),
            },
        }

    epsg = crs.split(":")[-1] if ":" in crs else "0"
    return {
        "type":        "CityJSON",
        "version":     "2.0",
        "transform":   {"scale": [1.0, 1.0, 1.0], "translate": [0.0, 0.0, 0.0]},
        "CityObjects": city_objects,
        "vertices":    v_list,
        "metadata":    {
            "referenceSystem": f"https://www.opengis.net/def/crs/EPSG/0/{epsg}"
        },
    }
