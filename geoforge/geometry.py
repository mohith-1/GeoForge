"""
geometry.py — Build 3D geometry from 2D polygons + LiDAR heights.

This is the heart of GeoForge. Each polygon becomes a Feature3D object
containing a triangle mesh (vertices + faces) and metadata.

One rule per class:
  building → closed solid box  (floor + 4 walls + roof)
  road     → smooth surface draped onto LiDAR ground
  terrain  → Delaunay TIN triangulated from ground points
  water    → single flat horizontal surface
  forest   → terrain surface raised by canopy height
  bridge   → elevated draped surface
  wall     → thin vertical slab
  fence    → thin vertical slab
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from shapely.geometry import MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

log = logging.getLogger(__name__)


# ── Data model ───────────────────────────────────────────────────────────────
@dataclass
class Feature3D:
    """A single 3D feature — one polygon lifted into 3D space."""
    feature_id:  Any
    layer_class: str
    vertices:    np.ndarray      # shape (N, 3)  — X, Y, Z positions
    faces:       np.ndarray      # shape (M, 3)  — triangle vertex indices
    height_top:  float           # absolute Z of roof / top surface
    height_base: float           # absolute Z of ground contact
    properties:  Dict[str, Any] = field(default_factory=dict)

    @property
    def height(self) -> float:
        """Height in metres from base to top."""
        return self.height_top - self.height_base


# ── Public entry point ───────────────────────────────────────────────────────
def build_feature(feature_id: Any,
                  geom:        BaseGeometry,
                  layer_class: str,
                  stats:       Dict[str, float],
                  layer_cfg,
                  pc,
                  properties:  Optional[Dict] = None) -> List[Feature3D]:
    """
    Convert one 2D polygon into one or more Feature3D objects.
    Multi-polygons are split and processed individually.
    """
    props  = properties or {}
    polys  = _flatten(geom)
    result = []

    for i, poly in enumerate(polys):
        if poly.is_empty or poly.area == 0:
            continue
        sub_id = feature_id if len(polys) == 1 else f"{feature_id}_{i}"
        try:
            f = _build_single(sub_id, poly, layer_class, stats, layer_cfg, pc, props)
            if f is not None:
                result.append(f)
        except Exception as e:
            log.warning(f"  Feature {sub_id} ({layer_class}) failed: {e}")

    return result


# ── Per-class geometry builders ───────────────────────────────────────────────
def _build_single(fid, poly, layer_class, stats, cfg, pc, props) -> Optional[Feature3D]:

    # 1. Resolve heights from LiDAR statistics
    if cfg.height_field and cfg.height_field in props:
        try:
            h        = float(props[cfg.height_field])
            z_ground = stats.get("z_ground", stats["z_min"])
            z_top    = z_ground + max(h, cfg.min_height)
            z_base   = z_ground
        except (TypeError, ValueError):
            z_top, z_base = _resolve_heights(stats, cfg)
    else:
        z_top, z_base = _resolve_heights(stats, cfg)

    z_base += cfg.offset
    z_top  += cfg.offset

    # Enforce minimum height
    if cfg.min_height > 0 and (z_top - z_base) < cfg.min_height:
        z_top = z_base + cfg.min_height

    # 2. Build geometry
    if layer_class == "building":
        verts, faces = _extrude_solid(poly, z_base, z_top)

    elif layer_class == "water":
        z = stats.get("z_min", stats["z_ground"]) + cfg.offset
        verts, faces = _flat_surface(poly, z)
        z_base = z_top = z

    elif layer_class in ("road", "bridge"):
        verts, faces = _drape_surface(poly, pc)
        verts[:, 2] += cfg.offset
        if len(verts):
            z_base = z_top = float(verts[:, 2].mean())

    elif layer_class == "terrain":
        verts, faces = _drape_surface(poly, pc)
        if len(verts):
            z_base = float(verts[:, 2].min())
            z_top  = float(verts[:, 2].max())

    elif layer_class == "forest":
        verts, faces = _drape_surface(poly, pc)
        if len(verts):
            verts[:, 2] += cfg.min_height   # lift canopy above ground
            z_base = float(verts[:, 2].min())
            z_top  = float(verts[:, 2].max())

    elif layer_class in ("wall", "fence"):
        verts, faces = _extrude_solid(poly.buffer(0.15), z_base, z_top)

    else:
        verts, faces = _flat_surface(poly, z_base)

    if len(faces) == 0:
        return None

    return Feature3D(
        feature_id  = fid,
        layer_class = layer_class,
        vertices    = verts,
        faces       = faces,
        height_top  = z_top,
        height_base = z_base,
        properties  = props,
    )


# ── Geometry primitives ───────────────────────────────────────────────────────
def _extrude_solid(poly: Polygon, z_base: float, z_top: float
                   ) -> Tuple[np.ndarray, np.ndarray]:
    """
    Build a closed LOD1 building solid.
    Returns vertices (N,3) and triangle faces (M,3).
    """
    verts_2d, cap_faces = _triangulate_polygon(poly)
    n = len(verts_2d)

    bottom = np.column_stack([verts_2d, np.full(n, z_base)])
    top    = np.column_stack([verts_2d, np.full(n, z_top)])
    verts  = np.vstack([bottom, top])

    # Floor (reversed winding = normals point down)
    floor_f = cap_faces[:, ::-1].copy()
    roof_f  = cap_faces + n

    # Walls along exterior ring
    ring    = list(poly.exterior.coords)[:-1]
    r_idx   = _ring_indices(ring, verts_2d)
    n_ring  = len(ring)
    walls   = []
    for i in range(n_ring):
        a, b = r_idx[i], r_idx[(i + 1) % n_ring]
        walls += [[a, b, b + n], [a, b + n, a + n]]

    # Walls along interior rings (holes)
    for hole in poly.interiors:
        h_ring = list(hole.coords)[:-1]
        h_idx  = _ring_indices(h_ring, verts_2d)
        nh     = len(h_ring)
        for i in range(nh):
            a, b = h_idx[i], h_idx[(i + 1) % nh]
            walls += [[b, a, a + n], [b, a + n, b + n]]

    wall_f = np.array(walls, dtype=np.int32) if walls else np.empty((0, 3), dtype=np.int32)
    faces  = np.vstack([floor_f, roof_f, wall_f])
    return verts.astype(np.float64), faces.astype(np.int32)


def _flat_surface(poly: Polygon, z: float) -> Tuple[np.ndarray, np.ndarray]:
    """Single flat horizontal surface at constant Z."""
    verts_2d, faces = _triangulate_polygon(poly)
    verts = np.column_stack([verts_2d, np.full(len(verts_2d), z)])
    return verts.astype(np.float64), faces.astype(np.int32)


def _drape_surface(poly: Polygon, pc) -> Tuple[np.ndarray, np.ndarray]:
    """
    Sample a grid of points inside the polygon, get their Z from LiDAR,
    then triangulate with Delaunay to create a terrain-following surface.
    """
    from scipy.spatial import Delaunay
    from shapely import prepare, contains_xy

    minx, miny, maxx, maxy = poly.bounds
    span = max(maxx - minx, maxy - miny)
    step = max(span / 40, 0.5)

    xs = np.arange(minx, maxx + step, step)
    ys = np.arange(miny, maxy + step, step)
    gx, gy = np.meshgrid(xs, ys)
    flat   = np.column_stack([gx.ravel(), gy.ravel()])

    # Keep only points inside the polygon
    try:
        prepare(poly)
        inside = contains_xy(poly, flat[:, 0], flat[:, 1])
    except Exception:
        from shapely.geometry import Point
        inside = np.array([poly.contains(Point(p)) for p in flat])

    flat = flat[inside]

    # Always include boundary vertices for watertight edges
    ring_pts = np.array(list(poly.exterior.coords)[:-1])
    all_xy   = np.vstack([flat, ring_pts]) if len(flat) > 0 else ring_pts
    all_z    = pc.interpolate_ground_z(all_xy)

    if len(all_xy) < 3:
        return np.empty((0, 3)), np.empty((0, 3), dtype=np.int32)

    tri = Delaunay(all_xy)
    cents = all_xy[tri.simplices].mean(axis=1)
    try:
        prepare(poly)
        valid = contains_xy(poly, cents[:, 0], cents[:, 1])
    except Exception:
        from shapely.geometry import Point
        valid = np.array([poly.contains(Point(c)) for c in cents])

    faces = tri.simplices[valid].astype(np.int32)
    verts = np.column_stack([all_xy, all_z]).astype(np.float64)
    return verts, faces


# ── Triangulation ─────────────────────────────────────────────────────────────
def _triangulate_polygon(poly: Polygon) -> Tuple[np.ndarray, np.ndarray]:
    """
    Triangulate a 2D polygon into a list of triangles.
    Uses mapbox_earcut (fast) with a Shapely Delaunay fallback.
    """
    # Fast path: mapbox_earcut
    try:
        import mapbox_earcut as earcut
        coords = list(poly.exterior.coords)[:-1]
        rings  = [len(coords)]
        flat   = [c for pt in coords for c in pt[:2]]
        for hole in poly.interiors:
            hc = list(hole.coords)[:-1]
            rings.append(len(hc))
            flat.extend(c for pt in hc for c in pt[:2])
        result = earcut.triangulate_float64(np.array(flat, dtype=np.float64), rings)
        if len(result):
            verts = np.array([(flat[i*2], flat[i*2+1])
                              for i in range(sum(rings))], dtype=np.float64)
            return verts, result.reshape(-1, 3).astype(np.int32)
    except Exception:
        pass

    # Fallback: Shapely Delaunay triangulation
    try:
        from shapely.ops import triangulate
        tris = [t for t in triangulate(poly) if poly.contains(t.centroid)]
        v_map, v_list, face_list = {}, [], []
        def add(p):
            k = (round(p[0], 6), round(p[1], 6))
            if k not in v_map:
                v_map[k] = len(v_list); v_list.append(k)
            return v_map[k]
        for t in tris:
            face_list.append([add(p) for p in list(t.exterior.coords)[:3]])
        if face_list:
            return (np.array(v_list, dtype=np.float64),
                    np.array(face_list, dtype=np.int32))
    except Exception:
        pass

    # Last resort: fan triangulation from centroid
    pts = list(poly.exterior.coords)[:-1]
    cx, cy = poly.centroid.x, poly.centroid.y
    all_pts = [(cx, cy)] + pts
    faces   = [[0, i+1, (i+2) if i+2 < len(pts)+1 else 1]
               for i in range(len(pts))]
    return (np.array(all_pts, dtype=np.float64),
            np.array(faces, dtype=np.int32))


def _ring_indices(ring_pts, verts_2d: np.ndarray) -> List[int]:
    """Map each ring vertex to its nearest index in verts_2d."""
    from scipy.spatial import KDTree
    _, idx = KDTree(verts_2d).query(np.array(ring_pts))
    return idx.tolist()


def _resolve_heights(stats, cfg) -> Tuple[float, float]:
    src = {
        "lidar_max":    stats.get("z_max",    stats["z_mean"]),
        "lidar_min":    stats.get("z_min",    stats["z_mean"]),
        "lidar_ground": stats.get("z_ground", stats["z_min"]),
        "lidar_mean":   stats.get("z_mean",   stats["z_min"]),
        "lidar_p50":    stats.get("z_p50",    stats["z_mean"]),
    }
    return (src.get(cfg.height_source, stats["z_max"]),
            src.get(cfg.base_source,   stats.get("z_ground", stats["z_min"])))


def _flatten(geom: BaseGeometry) -> List[Polygon]:
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, MultiPolygon):
        return list(geom.geoms)
    try:
        return [g for g in geom.geoms if isinstance(g, Polygon)]
    except Exception:
        return []
