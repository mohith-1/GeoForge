"""
lidar.py — Read LAS / LAZ point clouds and sample heights into polygons.

Think of this module like a very smart ruler:
  1. It reads every laser point from the .las file (X, Y, Z positions).
  2. It builds a spatial index (KDTree) so it can instantly find all
     points near any polygon — without checking every single point.
  3. For each polygon it returns height statistics:
       z_ground  — the ground level (robust, uses 10th percentile)
       z_max     — the highest point (roof level for buildings)
       z_mean    — the average height
       z_min     — the lowest point (water surface)
       z_p50     — the median height
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.interpolate import LinearNDInterpolator, NearestNDInterpolator
from scipy.spatial import KDTree
from shapely.geometry.base import BaseGeometry

log = logging.getLogger(__name__)


class PointCloud:
    """Loads a LAS/LAZ file and answers height queries for any polygon."""

    def __init__(self,
                 path: str,
                 ground_classes:   List[int] = (2,),
                 building_classes: List[int] = (6,),
                 z_offset: float = 0.0):
        self.path             = Path(path)
        self.ground_classes   = list(ground_classes)
        self.building_classes = list(building_classes)
        self.z_offset         = z_offset
        self._xyz:          Optional[np.ndarray] = None
        self._cls:          Optional[np.ndarray] = None
        self._tree:         Optional[KDTree]     = None
        self._ground_xyz:   Optional[np.ndarray] = None
        self._ground_interp: Optional[LinearNDInterpolator] = None
        self._ground_nn:     Optional[NearestNDInterpolator] = None

    # ── Loading ─────────────────────────────────────────────────────────────
    def load(self) -> "PointCloud":
        try:
            import laspy
        except ImportError:
            raise ImportError(
                "laspy is required to read LAS/LAZ files.\n"
                "Install it with:  pip install laspy[lazrs]"
            )

        log.info(f"Reading point cloud: {self.path}")
        las = laspy.read(str(self.path))

        x   = np.asarray(las.x, dtype=np.float64)
        y   = np.asarray(las.y, dtype=np.float64)
        z   = np.asarray(las.z, dtype=np.float64) + self.z_offset
        try:
            cls = np.asarray(las.classification, dtype=np.uint8)
        except Exception:
            cls = np.zeros(len(x), dtype=np.uint8)

        self._xyz = np.column_stack([x, y, z])
        self._cls = cls
        log.info(f"  {len(x):,} points loaded")

        # Separate ground points
        gmask = np.isin(cls, self.ground_classes)
        if not gmask.any():
            log.warning("No ground-class points found — using all points as ground.")
            gmask = np.ones(len(x), dtype=bool)

        self._ground_xyz = self._xyz[gmask]
        self._tree       = KDTree(self._xyz[:, :2])   # 2D index on X, Y only
        log.info(f"  Ground points: {gmask.sum():,}")
        return self

    def _ensure_loaded(self):
        if self._xyz is None:
            self.load()

    # ── Ground interpolation ─────────────────────────────────────────────────
    def _ground_interpolators(self):
        self._ensure_loaded()
        if self._ground_interp is None:
            log.info("Building ground interpolator …")
            pts = self._ground_xyz[:, :2]
            zs  = self._ground_xyz[:,  2]
            self._ground_interp = LinearNDInterpolator(pts, zs)
            self._ground_nn     = NearestNDInterpolator(pts, zs)
        return self._ground_interp, self._ground_nn

    def interpolate_ground_z(self, xy: np.ndarray) -> np.ndarray:
        """Return ground elevation at each (x, y) position in the array."""
        lin, nn = self._ground_interpolators()
        z = lin(xy)
        nan = np.isnan(z)
        if nan.any():
            z[nan] = nn(xy[nan])
        return z

    # ── Height sampling ──────────────────────────────────────────────────────
    def query_polygon(self, geom: BaseGeometry,
                      fallback_radius: float = 50.0) -> Dict[str, float]:
        """
        Return height statistics for all LiDAR points inside *geom*.

        Returns a dict with keys:
          z_min, z_max, z_mean, z_ground, z_p50, n_points
        """
        self._ensure_loaded()

        minx, miny, maxx, maxy = geom.bounds
        cx = (minx + maxx) / 2
        cy = (miny + maxy) / 2
        r  = max(maxx - minx, maxy - miny) * 0.71 + 2.0

        idx = self._tree.query_ball_point([cx, cy], r)
        if not idx:
            return self._fallback(cx, cy, fallback_radius)

        candidates = self._xyz[idx]
        inside     = _vectorised_contains(candidates[:, :2], geom)
        pts_in     = candidates[inside]

        if len(pts_in) == 0:
            return self._fallback(cx, cy, fallback_radius)

        cls_in   = self._cls[idx][inside]
        gnd_mask = np.isin(cls_in, self.ground_classes)
        ground_z = pts_in[gnd_mask, 2] if gnd_mask.any() else pts_in[:, 2]
        z_all    = pts_in[:, 2]

        return {
            "z_min":    float(z_all.min()),
            "z_max":    float(z_all.max()),
            "z_mean":   float(z_all.mean()),
            "z_ground": float(np.percentile(ground_z, 10)),
            "z_p50":    float(np.median(z_all)),
            "n_points": int(len(z_all)),
        }

    def _fallback(self, cx: float, cy: float, r: float) -> Dict[str, float]:
        """When no points are inside the polygon, use nearest neighbours."""
        idx = self._tree.query_ball_point([cx, cy], r)
        if not idx:
            _, i = self._tree.query([cx, cy])
            idx  = [i]
        z = self._xyz[idx, 2]
        return {
            "z_min":    float(z.min()),
            "z_max":    float(z.max()),
            "z_mean":   float(z.mean()),
            "z_ground": float(np.percentile(z, 10)),
            "z_p50":    float(np.median(z)),
            "n_points": int(len(z)),
        }

    def ground_points_in_bounds(self,
                                bounds: Tuple[float, float, float, float],
                                max_pts: int = 50_000) -> np.ndarray:
        """Return ground XYZ points within a bounding box."""
        self._ensure_loaded()
        minx, miny, maxx, maxy = bounds
        g = self._ground_xyz
        mask = (
            (g[:, 0] >= minx) & (g[:, 0] <= maxx) &
            (g[:, 1] >= miny) & (g[:, 1] <= maxy)
        )
        pts = g[mask]
        if len(pts) > max_pts:
            idx = np.random.choice(len(pts), max_pts, replace=False)
            pts = pts[idx]
        return pts


# ── Vectorised point-in-polygon ──────────────────────────────────────────────
def _vectorised_contains(xy: np.ndarray, geom: BaseGeometry) -> np.ndarray:
    """Check which points in xy are inside geom. Uses Shapely 2 fast path."""
    try:
        from shapely import prepare, contains_xy
        prepare(geom)
        return contains_xy(geom, xy[:, 0], xy[:, 1])
    except Exception:
        from shapely.geometry import Point
        return np.array([geom.contains(Point(p[0], p[1])) for p in xy])
