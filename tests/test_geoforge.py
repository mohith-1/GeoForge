"""
tests/test_geoforge.py — Unit and integration tests for GeoForge.
Run with:  pytest tests/ -v
"""
from __future__ import annotations

import json
import struct
import tempfile
from pathlib import Path

import numpy as np
import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def tmp(tmp_path):
    return tmp_path


def _make_las(path: Path, n_ground=200, n_building=50):
    """Write a minimal valid LAS 1.2 file."""
    rng = np.random.default_rng(0)
    gx  = rng.uniform(0, 50, n_ground)
    gy  = rng.uniform(0, 50, n_ground)
    gz  = rng.uniform(9.5, 10.5, n_ground)
    bx  = rng.uniform(10, 20, n_building)
    by  = rng.uniform(10, 20, n_building)
    bz  = np.full(n_building, 18.0)
    x   = np.concatenate([gx, bx])
    y   = np.concatenate([gy, by])
    z   = np.concatenate([gz, bz])
    cls = np.concatenate([np.full(n_ground, 2, np.uint8),
                          np.full(n_building, 6, np.uint8)])
    scale = 0.001
    xi = np.round(x/scale).astype(np.int32)
    yi = np.round(y/scale).astype(np.int32)
    zi = np.round(z/scale).astype(np.int32)
    n  = len(x)
    with open(path, "wb") as fh:
        fh.write(b"LASF"); fh.write(struct.pack("<HH",0,0))
        fh.write(struct.pack("<I",0)); fh.write(struct.pack("<HH",0,0))
        fh.write(b"\x00"*8); fh.write(struct.pack("<BB",1,2))
        fh.write(b"test".ljust(32,b"\x00")); fh.write(b"pytest".ljust(32,b"\x00"))
        fh.write(struct.pack("<HH",1,2026)); fh.write(struct.pack("<H",227))
        fh.write(struct.pack("<I",227)); fh.write(struct.pack("<I",0))
        fh.write(struct.pack("<B",0)); fh.write(struct.pack("<H",20))
        fh.write(struct.pack("<I",n)); fh.write(struct.pack("<5I",n,0,0,0,0))
        fh.write(struct.pack("<3d",scale,scale,scale))
        fh.write(struct.pack("<3d",0.0,0.0,0.0))
        fh.write(struct.pack("<6d",x.min(),x.max(),y.min(),y.max(),z.min(),z.max()))
        for i in range(n):
            fh.write(struct.pack("<iii",xi[i],yi[i],zi[i]))
            fh.write(struct.pack("<H",0)); fh.write(struct.pack("<B",1))
            fh.write(struct.pack("<B",cls[i])); fh.write(struct.pack("<b",0))
            fh.write(struct.pack("<B",0)); fh.write(struct.pack("<H",1))


# ── Config tests ──────────────────────────────────────────────────────────────
def test_load_config_minimal(tmp):
    (tmp/"c.yaml").write_text(
        "pointcloud: cloud.las\noutput_dir: out\nlayers:\n  - path: b.geojson\n    class: building\n"
    )
    from geoforge.config import load_config
    cfg = load_config(tmp/"c.yaml")
    assert cfg.pointcloud == "cloud.las"
    assert len(cfg.layers) == 1
    assert cfg.layers[0].layer_class == "building"


def test_load_config_bad_class(tmp):
    (tmp/"c.yaml").write_text(
        "pointcloud: c.las\noutput_dir: out\nlayers:\n  - path: x.geojson\n    class: unicorn\n"
    )
    from geoforge.config import load_config
    with pytest.raises(ValueError, match="unicorn"):
        load_config(tmp/"c.yaml")


# ── LiDAR tests ───────────────────────────────────────────────────────────────
def test_pointcloud_load(tmp):
    p = tmp/"t.las"; _make_las(p)
    from geoforge.lidar import PointCloud
    pc = PointCloud(str(p), ground_classes=[2]).load()
    assert pc._xyz is not None and len(pc._xyz) == 250


def test_pointcloud_query(tmp):
    p = tmp/"t.las"; _make_las(p)
    from geoforge.lidar import PointCloud
    from shapely.geometry import box
    pc    = PointCloud(str(p), ground_classes=[2]).load()
    stats = pc.query_polygon(box(5, 5, 45, 45))
    assert "z_max" in stats
    assert stats["z_max"] > stats["z_ground"]


# ── Geometry tests ────────────────────────────────────────────────────────────
def test_building_extrusion(tmp):
    p = tmp/"t.las"; _make_las(p)
    from geoforge.lidar import PointCloud
    from geoforge.geometry import build_feature
    from geoforge.config import LayerConfig
    from shapely.geometry import box
    pc    = PointCloud(str(p), ground_classes=[2]).load()
    poly  = box(11, 11, 19, 19)
    stats = pc.query_polygon(poly)
    lc    = LayerConfig(path="", layer_class="building", min_height=3.0)
    feats = build_feature("B1", poly, "building", stats, lc, pc)
    assert len(feats) == 1
    assert feats[0].vertices.shape[1] == 3
    assert feats[0].height >= 3.0


def test_water_is_flat(tmp):
    p = tmp/"t.las"; _make_las(p)
    from geoforge.lidar import PointCloud
    from geoforge.geometry import build_feature
    from geoforge.config import LayerConfig
    from shapely.geometry import box
    pc    = PointCloud(str(p), ground_classes=[2]).load()
    stats = pc.query_polygon(box(5, 5, 15, 15))
    lc    = LayerConfig(path="", layer_class="water")
    feats = build_feature("W1", box(5,5,15,15), "water", stats, lc, pc)
    assert len(feats) == 1
    zs = feats[0].vertices[:, 2]
    assert float(zs.max() - zs.min()) < 0.01   # flat = all Z same


# ── Exporter tests ────────────────────────────────────────────────────────────
def _dummy_features():
    from geoforge.geometry import Feature3D
    v = np.array([[0,0,0],[10,0,0],[10,10,0],[0,10,0],
                  [0,0,8],[10,0,8],[10,10,8],[0,10,8]], dtype=np.float64)
    f = np.array([[0,1,2],[0,2,3],[4,5,6],[4,6,7],
                  [0,1,5],[0,5,4],[1,2,6],[1,6,5],
                  [2,3,7],[2,7,6],[3,0,4],[3,4,7]], dtype=np.int32)
    return [Feature3D("B1","building",v,f,8.0,0.0)]


def test_obj_export(tmp):
    from geoforge.exporters import export
    export(_dummy_features(), tmp, ["obj"])
    txt = (tmp/"model.obj").read_text()
    assert "v " in txt and "f " in txt and "g building" in txt


def test_cityjson_export(tmp):
    from geoforge.exporters import export
    export(_dummy_features(), tmp, ["cityjson"])
    d = json.loads((tmp/"model.city.json").read_text())
    assert d["type"] == "CityJSON"
    assert "B1" in d["CityObjects"]


def test_stl_export(tmp):
    from geoforge.exporters import export
    export(_dummy_features(), tmp, ["stl"])
    data = (tmp/"model.stl").read_bytes()
    n = struct.unpack("<I", data[80:84])[0]
    assert n == 12 and len(data) == 84 + 12*50


def test_csv_export(tmp):
    from geoforge.exporters import export
    export(_dummy_features(), tmp, ["csv"])
    lines = (tmp/"building_heights.csv").read_text().splitlines()
    assert lines[0].startswith("source_id") and "B1" in lines[1]


def test_postgis_export(tmp):
    from geoforge.exporters import export
    export(_dummy_features(), tmp, ["postgis"])
    sql = (tmp/"model_postgis.sql").read_text()
    assert "CREATE TABLE" in sql and "INSERT INTO" in sql


# ── Integration test ──────────────────────────────────────────────────────────
def test_full_pipeline(tmp):
    from geoforge.example_gen import generate
    proj = tmp/"proj"; generate(proj)
    from geoforge.config import load_config
    from geoforge.pipeline import run
    cfg = load_config(proj/"config.yaml")
    cfg.output_dir     = str(tmp/"out")
    cfg.output_formats = ["obj", "cityjson", "csv"]
    features = run(cfg)
    assert len(features) > 0
    assert (Path(cfg.output_dir)/"model.obj").exists()
    assert (Path(cfg.output_dir)/"model.city.json").exists()
    assert (Path(cfg.output_dir)/"building_heights.csv").exists()
