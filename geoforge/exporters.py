"""
exporters.py — Write 3D features to OBJ, CityJSON, CityGML, STL, PostGIS SQL, CSV.

Each function takes a list of Feature3D objects and writes one file.
The dispatcher at the top routes to the right writer based on format name.
"""
from __future__ import annotations

import csv
import json
import logging
import struct
from pathlib import Path
from typing import List

import numpy as np

from .geometry import Feature3D

log = logging.getLogger(__name__)

# CityJSON type mapping
CITYJSON_TYPES = {
    "building": "Building",
    "water":    "WaterBody",
    "road":     "Road",
    "terrain":  "TINRelief",
    "forest":   "PlantCover",
    "bridge":   "Bridge",
    "wall":     "GenericCityObject",
    "fence":    "GenericCityObject",
}


# ── Dispatcher ────────────────────────────────────────────────────────────────
def export(features: List[Feature3D], out_dir: Path,
           formats: List[str], crs: str = None):
    """Write all requested formats to out_dir."""
    out_dir.mkdir(parents=True, exist_ok=True)

    writers = {
        "obj":      (_write_obj,     "model.obj"),
        "cityjson": (_write_cityjson,"model.city.json"),
        "citygml":  (_write_citygml, "model.gml"),
        "stl":      (_write_stl,     "model.stl"),
        "postgis":  (_write_postgis, "model_postgis.sql"),
        "csv":      (_write_csv,     "building_heights.csv"),
    }

    for fmt in formats:
        fmt = fmt.lower()
        if fmt not in writers:
            log.warning(f"Unknown format '{fmt}' — skipped.")
            continue
        fn, fname = writers[fmt]
        try:
            fn(features, out_dir / fname, crs=crs)
        except Exception as e:
            log.error(f"Export '{fmt}' failed: {e}", exc_info=True)


# ── OBJ ───────────────────────────────────────────────────────────────────────
def _write_obj(features, path, **_):
    log.info(f"Writing OBJ → {path}")
    lines  = ["# GeoForge — Wavefront OBJ", ""]
    offset = 1   # OBJ indices start at 1

    from itertools import groupby
    for cls, grp in groupby(sorted(features, key=lambda f: f.layer_class),
                            key=lambda f: f.layer_class):
        lines.append(f"g {cls}")
        for feat in grp:
            lines.append(f"# id={feat.feature_id}")
            for v in feat.vertices:
                # OBJ uses Y-up: swap Y and Z
                lines.append(f"v {v[0]:.4f} {v[2]:.4f} {v[1]:.4f}")
            for tri in feat.faces:
                a, b, c = tri[0]+offset, tri[1]+offset, tri[2]+offset
                lines.append(f"f {a} {b} {c}")
            offset += len(feat.vertices)

    path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"  {sum(len(f.vertices) for f in features):,} vertices · "
             f"{sum(len(f.faces) for f in features):,} faces")


# ── CityJSON ─────────────────────────────────────────────────────────────────
def _write_cityjson(features, path, crs=None, **_):
    log.info(f"Writing CityJSON → {path}")
    v_idx, v_list = {}, []

    def add_v(pt):
        key = (round(pt[0], 4), round(pt[1], 4), round(pt[2], 4))
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
        while oid in city_objects:
            oid += "_x"

        city_objects[oid] = {
            "type":     CITYJSON_TYPES.get(feat.layer_class, "GenericCityObject"),
            "geometry": [{"type": "MultiSurface", "lod": "1", "boundaries": boundaries}],
            "attributes": {
                "source_id":   feat.feature_id,
                "layer_class": feat.layer_class,
                "height_top":  round(feat.height_top,  3),
                "height_base": round(feat.height_base, 3),
                "height":      round(feat.height,      3),
                **{k: v for k, v in feat.properties.items()
                   if isinstance(v, (str, int, float, bool, type(None)))},
            },
        }

    doc = {
        "type":        "CityJSON",
        "version":     "2.0",
        "transform":   {"scale": [1.0, 1.0, 1.0], "translate": [0.0, 0.0, 0.0]},
        "CityObjects": city_objects,
        "vertices":    v_list,
    }
    if crs:
        epsg = crs.split(":")[-1] if ":" in crs else crs
        doc["metadata"] = {
            "referenceSystem": f"https://www.opengis.net/def/crs/EPSG/0/{epsg}"
        }

    path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    log.info(f"  {len(city_objects)} objects · {len(v_list):,} vertices")


# ── CityGML ───────────────────────────────────────────────────────────────────
def _write_citygml(features, path, crs=None, **_):
    log.info(f"Writing CityGML → {path}")
    srs   = crs or "urn:ogc:def:crs:EPSG::0"
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<CityModel xmlns="http://www.opengis.net/citygml/2.0"',
        '           xmlns:bldg="http://www.opengis.net/citygml/building/2.0"',
        '           xmlns:gml="http://www.opengis.net/gml"',
        '           xmlns:gen="http://www.opengis.net/citygml/generics/2.0"',
        '           gml:id="geoforge_model">',
    ]
    for feat in features:
        gml_id = f"id_{str(feat.feature_id).replace(' ', '_')}"
        if feat.layer_class == "building":
            lines += _gml_building(feat, gml_id)
        else:
            lines += _gml_generic(feat, gml_id)
    lines.append("</CityModel>")
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"  {len(features)} city objects")


def _gml_surface(feat, tri):
    pts = [feat.vertices[i] for i in tri] + [feat.vertices[tri[0]]]
    coords = " ".join(f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}" for p in pts)
    return [
        "        <gml:surfaceMember><gml:Polygon><gml:exterior><gml:LinearRing>",
        f"          <gml:posList srsDimension=\"3\">{coords}</gml:posList>",
        "        </gml:LinearRing></gml:exterior></gml:Polygon></gml:surfaceMember>",
    ]


def _gml_building(feat, gml_id):
    lines = [
        f'  <cityObjectMember><bldg:Building gml:id="{gml_id}">',
        f'    <gen:stringAttribute name="source_id"><gen:value>{feat.feature_id}</gen:value></gen:stringAttribute>',
        f'    <bldg:measuredHeight uom="m">{feat.height:.3f}</bldg:measuredHeight>',
        '    <bldg:lod1Solid><gml:Solid><gml:exterior><gml:CompositeSurface>',
    ]
    for tri in feat.faces:
        lines += _gml_surface(feat, tri)
    lines += [
        '    </gml:CompositeSurface></gml:exterior></gml:Solid></bldg:lod1Solid>',
        '  </bldg:Building></cityObjectMember>',
    ]
    return lines


def _gml_generic(feat, gml_id):
    lines = [
        f'  <cityObjectMember><gen:GenericCityObject gml:id="{gml_id}">',
        f'    <gen:stringAttribute name="source_id"><gen:value>{feat.feature_id}</gen:value></gen:stringAttribute>',
        f'    <gen:stringAttribute name="class"><gen:value>{feat.layer_class}</gen:value></gen:stringAttribute>',
        '    <gen:lod1Geometry><gml:MultiSurface>',
    ]
    for tri in feat.faces:
        lines += _gml_surface(feat, tri)
    lines += [
        '    </gml:MultiSurface></gen:lod1Geometry>',
        '  </gen:GenericCityObject></cityObjectMember>',
    ]
    return lines


# ── STL ──────────────────────────────────────────────────────────────────────
def _write_stl(features, path, **_):
    log.info(f"Writing binary STL → {path}")
    total = sum(len(f.faces) for f in features)
    with open(path, "wb") as fh:
        fh.write(b"GeoForge model".ljust(80))
        fh.write(struct.pack("<I", total))
        for feat in features:
            for tri in feat.faces:
                v0, v1, v2 = feat.vertices[tri[0]], feat.vertices[tri[1]], feat.vertices[tri[2]]
                e1, e2 = v1 - v0, v2 - v0
                n = np.cross(e1, e2)
                ln = np.linalg.norm(n)
                n  = n / ln if ln > 0 else n
                fh.write(struct.pack("<fff", *n))
                fh.write(struct.pack("<fff", *v0))
                fh.write(struct.pack("<fff", *v1))
                fh.write(struct.pack("<fff", *v2))
                fh.write(struct.pack("<H", 0))
    log.info(f"  {total:,} triangles")


# ── PostGIS SQL ───────────────────────────────────────────────────────────────
def _write_postgis(features, path, **_):
    log.info(f"Writing PostGIS SQL → {path}")
    lines = [
        "-- GeoForge PostGIS export",
        "-- Import with:  psql -d mydb -f model_postgis.sql",
        "",
        "CREATE TABLE IF NOT EXISTS geoforge_features (",
        "    id          SERIAL PRIMARY KEY,",
        "    source_id   TEXT,",
        "    layer_class TEXT,",
        "    height_top  FLOAT,",
        "    height_base FLOAT,",
        "    height      FLOAT,",
        "    geom        geometry(MultiPolygonZ, 0)",
        ");",
        "",
        "BEGIN;",
    ]
    for feat in features:
        tris = []
        for tri in feat.faces:
            pts  = [feat.vertices[i] for i in tri] + [feat.vertices[tri[0]]]
            ring = ",".join(f"{p[0]:.4f} {p[1]:.4f} {p[2]:.4f}" for p in pts)
            tris.append(f"(({ring}))")
        wkt = "MULTIPOLYGON Z(" + ",".join(tris) + ")"
        sid = str(feat.feature_id).replace("'", "''")
        lines.append(
            f"INSERT INTO geoforge_features "
            f"(source_id,layer_class,height_top,height_base,height,geom) VALUES "
            f"('{sid}','{feat.layer_class}',{feat.height_top:.3f},"
            f"{feat.height_base:.3f},{feat.height:.3f},"
            f"ST_GeomFromText('{wkt}',0));"
        )
    lines += ["COMMIT;", ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    log.info(f"  {len(features)} rows")


# ── CSV ───────────────────────────────────────────────────────────────────────
def _write_csv(features, path, **_):
    log.info(f"Writing CSV → {path}")
    fields = ["source_id", "layer_class", "height_top", "height_base", "height"]
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fields)
        w.writeheader()
        for f in features:
            w.writerow({
                "source_id":   f.feature_id,
                "layer_class": f.layer_class,
                "height_top":  round(f.height_top,  3),
                "height_base": round(f.height_base, 3),
                "height":      round(f.height,      3),
            })
    log.info(f"  {len(features)} rows")
