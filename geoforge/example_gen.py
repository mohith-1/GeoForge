"""
example_gen.py — Generate a self-contained GeoForge example project.

Creates a small synthetic city district with:
  - 10 buildings (varied heights)
  - Road grid
  - River
  - Forest patches
  - Parks
  - 2 bridges
  - Walls and fences
  - LiDAR point cloud matching all features
  - config.yaml wired up to all files
"""
from __future__ import annotations

import json
import logging
import math
import struct
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)


def generate(out: Path):
    """Write a complete example project to *out*."""
    out.mkdir(parents=True, exist_ok=True)
    data = out / "data"
    data.mkdir(exist_ok=True)
    (out / "output").mkdir(exist_ok=True)

    log.info("Generating example data …")
    _buildings(data / "buildings.geojson")
    _roads(data / "roads.geojson")
    _water(data / "water.geojson")
    _terrain(data / "terrain.geojson")
    _forest(data / "forest.geojson")
    _bridges(data / "bridges.geojson")
    _walls(data / "walls.geojson")
    _fences(data / "fences.geojson")
    _pointcloud(data / "pointcloud.las")
    _config(out / "config.yaml")
    log.info(f"Example project ready: {out.resolve()}")


# ── GeoJSON helpers ───────────────────────────────────────────────────────────
def _rect(x, y, w, h):
    return [[x,y],[x+w,y],[x+w,y+h],[x,y+h],[x,y]]

def _feat(fid, geom, props=None):
    return {"type":"Feature","id":fid,
            "properties":{"id":fid,**(props or {})},
            "geometry":geom}

def _fc(feats):
    return {"type":"FeatureCollection","features":feats}

def _save(path, fc):
    path.write_text(json.dumps(fc, indent=2), encoding="utf-8")
    log.info(f"  {path.name}: {len(fc['features'])} features")


# ── Layer data ────────────────────────────────────────────────────────────────
def _buildings(path):
    data = [
        (10,10,15,12,"BLD001",14.0),(35,10,10,10,"BLD002",8.0),
        (55,10,20,15,"BLD003",22.0),(10,35,12,8, "BLD004",6.0),
        (35,35,8, 8, "BLD005",10.0),(60,40,10,10,"BLD006",12.0),
        (10,55,18,10,"BLD007",16.0),(45,55,12,12,"BLD008",9.0),
        (70,60,8, 8, "BLD009",7.0), (20,70,10,10,"BLD010",20.0),
    ]
    feats = [_feat(fid,{"type":"Polygon","coordinates":[_rect(x,y,w,h)]},
                   {"building_height":bh}) for x,y,w,h,fid,bh in data]
    _save(path, _fc(feats))

def _roads(path):
    feats = [
        _feat("RD001",{"type":"Polygon","coordinates":[[[0,24],[100,24],[100,28],[0,28],[0,24]]]}),
        _feat("RD002",{"type":"Polygon","coordinates":[[[0,50],[100,50],[100,54],[0,54],[0,50]]]}),
        _feat("RD003",{"type":"Polygon","coordinates":[[[28,0],[32,0],[32,100],[28,100],[28,0]]]}),
        _feat("RD004",{"type":"Polygon","coordinates":[[[52,0],[56,0],[56,100],[52,100],[52,0]]]}),
    ]
    _save(path, _fc(feats))

def _water(path):
    feats = [
        _feat("WAT001",{"type":"Polygon","coordinates":[[[62,10],[90,10],[90,20],[62,20],[62,10]]]}),
        _feat("WAT002",{"type":"Polygon","coordinates":[[[5,80],[15,78],[25,82],[22,92],[10,95],[3,90],[5,80]]]}),
    ]
    _save(path, _fc(feats))

def _terrain(path):
    feat = _feat("TRN001", {"type":"Polygon","coordinates":[[[0,0],[100,0],[100,100],[0,100],[0,0]]]})
    _save(path, _fc([feat]))

def _forest(path):
    feats = [
        _feat("FOR001",{"type":"Polygon","coordinates":[[[70,70],[95,70],[95,95],[70,95],[70,70]]]}),
        _feat("FOR002",{"type":"Polygon","coordinates":[[[0,0],[10,0],[10,20],[0,20],[0,0]]]}),
    ]
    _save(path, _fc(feats))

def _bridges(path):
    _save(path, _fc([
        _feat("BRG001",{"type":"Polygon","coordinates":[[[25,22],[35,22],[35,30],[25,30],[25,22]]]})
    ]))

def _walls(path):
    feats = [
        _feat("WLL001",{"type":"Polygon","coordinates":[[[8,33],[28,33],[28,35],[8,35],[8,33]]]}),
        _feat("WLL002",{"type":"Polygon","coordinates":[[[58,33],[80,33],[80,35],[58,35],[58,33]]]}),
    ]
    _save(path, _fc(feats))

def _fences(path):
    _save(path, _fc([
        _feat("FNC001",{"type":"Polygon","coordinates":[[[8,53],[28,53],[28,54.5],[8,54.5],[8,53]]]})
    ]))


# ── Synthetic LAS 1.2 point cloud ─────────────────────────────────────────────
def _terrain_z(x, y):
    return 10.0 + 0.02*x + 0.01*y + 0.3*math.sin(x*0.07)*math.cos(y*0.05)

def _pointcloud(path: Path):
    rng = np.random.default_rng(42)

    # Ground points
    gx = rng.uniform(0, 100, 8000)
    gy = rng.uniform(0, 100, 8000)
    gz = np.array([_terrain_z(x,y) for x,y in zip(gx,gy)]) + rng.normal(0, 0.15, 8000)

    # Building roof points
    bldgs = [(10,10,25,22,24),(35,10,45,20,18),(55,10,75,25,32),(10,35,22,43,16),
             (35,35,43,43,20),(60,40,70,50,22),(10,55,28,65,26),(45,55,57,67,19),
             (70,60,78,68,17),(20,70,30,80,30)]
    bx_l, by_l, bz_l = [], [], []
    for x0,y0,x1,y1,zr in bldgs:
        n = 200
        bx_l.append(rng.uniform(x0,x1,n)); by_l.append(rng.uniform(y0,y1,n))
        bz_l.append(np.full(n,zr)+rng.normal(0,0.3,n))
    bx = np.concatenate(bx_l); by = np.concatenate(by_l); bz = np.concatenate(bz_l)

    # Vegetation
    vx = np.concatenate([rng.uniform(70,95,500), rng.uniform(0,10,200)])
    vy = np.concatenate([rng.uniform(70,95,500), rng.uniform(0,20,200)])
    vz = np.array([_terrain_z(x,y) for x,y in zip(vx,vy)]) + rng.uniform(6,18,700)

    x   = np.concatenate([gx,bx,vx])
    y   = np.concatenate([gy,by,vy])
    z   = np.concatenate([gz,bz,vz])
    cls = np.concatenate([np.full(len(gx),2),np.full(len(bx),6),np.full(len(vx),5)])

    scale = 0.001
    xi = np.round(x/scale).astype(np.int32)
    yi = np.round(y/scale).astype(np.int32)
    zi = np.round(z/scale).astype(np.int32)
    n_pts = len(x)

    with open(path,"wb") as fh:
        fh.write(b"LASF")
        fh.write(struct.pack("<HH",0,0)); fh.write(struct.pack("<I",0))
        fh.write(struct.pack("<HH",0,0)); fh.write(b"\x00"*8)
        fh.write(struct.pack("<BB",1,2))
        fh.write(b"geoforge".ljust(32,b"\x00"))
        fh.write(b"example_gen".ljust(32,b"\x00"))
        fh.write(struct.pack("<HH",1,2026))
        fh.write(struct.pack("<H",227)); fh.write(struct.pack("<I",227))
        fh.write(struct.pack("<I",0)); fh.write(struct.pack("<B",0))
        fh.write(struct.pack("<H",20)); fh.write(struct.pack("<I",n_pts))
        fh.write(struct.pack("<5I",n_pts,0,0,0,0))
        fh.write(struct.pack("<3d",scale,scale,scale))
        fh.write(struct.pack("<3d",0.0,0.0,0.0))
        fh.write(struct.pack("<6d",x.min(),x.max(),y.min(),y.max(),z.min(),z.max()))
        for i in range(n_pts):
            fh.write(struct.pack("<iii",xi[i],yi[i],zi[i]))
            fh.write(struct.pack("<H",0)); fh.write(struct.pack("<B",1))
            fh.write(struct.pack("<B",cls[i])); fh.write(struct.pack("<b",0))
            fh.write(struct.pack("<B",0)); fh.write(struct.pack("<H",1))

    log.info(f"  pointcloud.las: {n_pts:,} points")


# ── Config YAML ───────────────────────────────────────────────────────────────
def _config(path: Path):
    path.write_text("""\
# GeoForge example config
pointcloud: data/pointcloud.las
output_dir: output
grid_resolution: 1.0
simplify_tolerance: 0.1
z_offset: 0.0

output_formats:
  - obj
  - cityjson
  - citygml
  - stl
  - postgis
  - csv

layers:
  - path: data/terrain.geojson
    class: terrain
    id_field: id

  - path: data/water.geojson
    class: water
    id_field: id

  - path: data/roads.geojson
    class: road
    id_field: id
    offset: 0.05

  - path: data/forest.geojson
    class: forest
    id_field: id
    min_height: 8.0

  - path: data/buildings.geojson
    class: building
    id_field: id
    height_field: building_height
    min_height: 3.0

  - path: data/bridges.geojson
    class: bridge
    id_field: id

  - path: data/walls.geojson
    class: wall
    id_field: id
    min_height: 2.0

  - path: data/fences.geojson
    class: fence
    id_field: id
    min_height: 1.2
""", encoding="utf-8")
    log.info("  config.yaml written")
