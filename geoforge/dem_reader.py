"""
dem_reader.py — Download and read free elevation data (DEM).

When a user types a city name, we have no LiDAR file.
This module downloads a free Digital Elevation Model (DEM) for
the area and creates a PointCloud-compatible height sampler from it.

Data sources (tried in order):
  1. Open-Elevation API  — free, global, 30m resolution
  2. SRTM via OpenTopoData — free, global, 90m resolution
  3. Flat fallback        — if all APIs fail, use sea level

The result is a DemSampler object that has the same interface
as PointCloud, so the rest of the pipeline works unchanged.
"""
from __future__ import annotations

import logging
import math
from typing import Dict, Tuple

import numpy as np
import requests
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
from scipy.spatial import KDTree
from shapely.geometry.base import BaseGeometry

log = logging.getLogger(__name__)


class DemSampler:
    """
    Replaces PointCloud for locations without LiDAR.
    Samples terrain elevation from a grid of DEM readings.

    Has the same interface as PointCloud so the pipeline
    doesn't know the difference.
    """

    def __init__(self, lat: float, lon: float,
                 radius_m: float = 500,
                 grid_pts: int = 30):
        self.lat      = lat
        self.lon      = lon
        self.radius_m = radius_m
        self.grid_pts = grid_pts

        self._xy:   np.ndarray = None
        self._z:    np.ndarray = None
        self._tree: KDTree     = None
        self._lin:  LinearNDInterpolator = None
        self._nn:   NearestNDInterpolator = None

    # ── Load ──────────────────────────────────────────────────────────────
    def load(self) -> "DemSampler":
        """Download elevation grid and build spatial index."""
        log.info(f"Downloading DEM for ({self.lat:.4f}, {self.lon:.4f}) …")

        # Build a grid of lat/lon sample points
        dlat = self.radius_m / 111_320
        dlon = self.radius_m / (111_320 * math.cos(math.radians(self.lat)))

        lats = np.linspace(self.lat - dlat, self.lat + dlat, self.grid_pts)
        lons = np.linspace(self.lon - dlon, self.lon + dlon, self.grid_pts)
        glat, glon = np.meshgrid(lats, lons)
        flat_lat = glat.ravel()
        flat_lon = glon.ravel()

        # Download elevations
        elevations = self._fetch_elevations(flat_lat, flat_lon)
        log.info(f"  DEM: {len(elevations)} points, "
                 f"z range [{elevations.min():.1f} – {elevations.max():.1f}] m")

        # Convert lat/lon to local metres (simple equirectangular)
        # x = east (metres), y = north (metres)
        cx  = np.cos(math.radians(self.lat))
        x   = (flat_lon - self.lon) * 111_320 * cx
        y   = (flat_lat - self.lat) * 111_320
        self._xy   = np.column_stack([x, y])
        self._z    = elevations
        self._tree = KDTree(self._xy)
        self._lin  = LinearNDInterpolator(self._xy, self._z)
        self._nn   = NearestNDInterpolator(self._xy, self._z)
        return self

    # ── Elevation fetch ────────────────────────────────────────────────────
    def _fetch_elevations(self, lats: np.ndarray,
                          lons: np.ndarray) -> np.ndarray:
        """Try multiple free DEM APIs, fall back gracefully."""

        # API 1: Open-Elevation (batch up to 100 points)
        try:
            z = self._open_elevation(lats, lons)
            if z is not None:
                return z
        except Exception as e:
            log.warning(f"  Open-Elevation failed: {e}")

        # API 2: OpenTopoData SRTM
        try:
            z = self._opentopodata(lats, lons)
            if z is not None:
                return z
        except Exception as e:
            log.warning(f"  OpenTopoData failed: {e}")

        # Fallback: flat terrain at sea level
        log.warning("  All DEM APIs failed — using flat terrain at 0m")
        return np.zeros(len(lats))

    def _open_elevation(self, lats, lons) -> np.ndarray:
        """Open-Elevation API — free, no key required."""
        # Batch into chunks of 100
        results = []
        chunk = 80
        for i in range(0, len(lats), chunk):
            batch = [{"latitude": float(la), "longitude": float(lo)}
                     for la, lo in zip(lats[i:i+chunk], lons[i:i+chunk])]
            r = requests.post(
                "https://api.open-elevation.com/api/v1/lookup",
                json={"locations": batch},
                timeout=30,
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            data = r.json()
            results.extend([p["elevation"] for p in data["results"]])

        z = np.array(results, dtype=np.float64)
        log.info("  DEM source: Open-Elevation API")
        return z

    def _opentopodata(self, lats, lons) -> np.ndarray:
        """OpenTopoData SRTM API — free, no key required."""
        results = []
        chunk = 100
        for i in range(0, len(lats), chunk):
            pts = "|".join(f"{la:.6f},{lo:.6f}"
                           for la, lo in zip(lats[i:i+chunk], lons[i:i+chunk]))
            r = requests.get(
                f"https://api.opentopodata.org/v1/srtm90m?locations={pts}",
                timeout=30,
            )
            r.raise_for_status()
            data = r.json()
            results.extend([
                p["elevation"] if p["elevation"] is not None else 0
                for p in data["results"]
            ])

        z = np.array(results, dtype=np.float64)
        log.info("  DEM source: OpenTopoData SRTM")
        return z

    # ── PointCloud-compatible interface ────────────────────────────────────
    def query_polygon(self, geom: BaseGeometry,
                      fallback_radius: float = 200.0) -> Dict[str, float]:
        """Return height statistics for a polygon (same as PointCloud)."""
        from shapely import prepare, contains_xy
        minx,miny,maxx,maxy = geom.bounds
        cx = (minx+maxx)/2; cy = (miny+maxy)/2
        r  = max(maxx-minx, maxy-miny)*0.71 + 5

        idx = self._tree.query_ball_point([cx,cy], r)
        if not idx:
            return self._fallback(cx, cy, fallback_radius)

        candidates = self._xy[idx]
        try:
            prepare(geom)
            inside = contains_xy(geom, candidates[:,0], candidates[:,1])
        except Exception:
            from shapely.geometry import Point
            inside = np.array([geom.contains(Point(p)) for p in candidates])

        z_in = self._z[idx][inside]
        if not len(z_in):
            return self._fallback(cx, cy, fallback_radius)

        return {
            "z_min":    float(z_in.min()),
            "z_max":    float(z_in.max()),
            "z_mean":   float(z_in.mean()),
            "z_ground": float(np.percentile(z_in, 10)),
            "z_p50":    float(np.median(z_in)),
            "n_points": int(len(z_in)),
        }

    def _fallback(self, cx, cy, r) -> Dict[str, float]:
        idx = self._tree.query_ball_point([cx,cy], r)
        if not idx:
            _, i = self._tree.query([cx,cy])
            idx  = [i]
        z = self._z[idx]
        return {
            "z_min": float(z.min()), "z_max": float(z.max()),
            "z_mean": float(z.mean()), "z_ground": float(np.percentile(z,10)),
            "z_p50": float(np.median(z)), "n_points": int(len(z)),
        }

    def interpolate_ground_z(self, xy: np.ndarray) -> np.ndarray:
        """Interpolate ground elevation at arbitrary XY positions."""
        z = self._lin(xy)
        nan = np.isnan(z)
        if nan.any():
            z[nan] = self._nn(xy[nan])
        return z

    def ground_points_in_bounds(self, bounds, max_pts=50_000) -> np.ndarray:
        minx,miny,maxx,maxy = bounds
        mask = ((self._xy[:,0]>=minx)&(self._xy[:,0]<=maxx)&
                (self._xy[:,1]>=miny)&(self._xy[:,1]<=maxy))
        pts  = np.column_stack([self._xy[mask], self._z[mask]])
        if len(pts) > max_pts:
            idx = np.random.choice(len(pts), max_pts, replace=False)
            pts = pts[idx]
        return pts
