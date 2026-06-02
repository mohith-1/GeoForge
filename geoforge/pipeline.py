"""
pipeline.py — Runs the full GeoForge pipeline from start to finish.

Order:
  1. Load the point cloud
  2. For each layer: read polygons → sample heights → build 3D geometry
  3. Export everything to the requested formats
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import List

import geopandas as gpd

from .config import Config
from .exporters import export
from .geometry import Feature3D, build_feature
from .lidar import PointCloud

log = logging.getLogger(__name__)


def run(cfg: Config) -> List[Feature3D]:
    """Execute the pipeline and return all built Feature3D objects."""
    t0 = time.time()

    # ── Step 1: load point cloud ──────────────────────────────────────────
    pc = PointCloud(
        cfg.resolve(cfg.pointcloud),
        ground_classes   = cfg.lidar_ground_classes,
        building_classes = cfg.lidar_building_classes,
        z_offset         = cfg.z_offset,
    ).load()

    all_features: List[Feature3D] = []

    # ── Step 2: process each layer ────────────────────────────────────────
    for layer in cfg.layers:
        layer_path = cfg.resolve(layer.path)
        log.info(f"Layer [{layer.layer_class}] → {layer_path}")

        try:
            gdf = gpd.read_file(layer_path)
        except Exception as e:
            log.error(f"  Cannot read '{layer_path}': {e}")
            continue

        if cfg.simplify_tolerance > 0:
            gdf["geometry"] = gdf["geometry"].simplify(cfg.simplify_tolerance)

        # Determine the ID column
        id_col = layer.id_field if layer.id_field in gdf.columns else None
        if id_col is None:
            gdf["_gf_id"] = [f"{layer.layer_class}_{i}" for i in range(len(gdf))]
            id_col = "_gf_id"

        n_ok, n_fail = 0, 0
        for row in gdf.itertuples():
            geom = getattr(row, "geometry", None)
            if geom is None or geom.is_empty:
                continue

            fid   = getattr(row, id_col, row.Index)
            props = {c: getattr(row, c) for c in gdf.columns
                     if c not in ("geometry", "_gf_id")}

            try:
                stats = pc.query_polygon(geom)
                feats = build_feature(fid, geom, layer.layer_class,
                                      stats, layer, pc, props)
                all_features.extend(feats)
                n_ok += 1
            except Exception as e:
                log.debug(f"  Feature {fid}: {e}")
                n_fail += 1

        log.info(f"  {n_ok} features built · {n_fail} skipped")

    # ── Step 3: export ────────────────────────────────────────────────────
    out_dir = Path(cfg.resolve(cfg.output_dir))
    export(all_features, out_dir, cfg.output_formats, crs=cfg.crs)

    elapsed = time.time() - t0
    log.info(f"Done — {len(all_features)} features in {elapsed:.1f}s")
    log.info(f"Output: {out_dir.resolve()}")
    return all_features
