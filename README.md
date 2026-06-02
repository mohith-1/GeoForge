<div align="center">

# ⚙️ GeoForge

### Convert 2D map layers + LiDAR into clean 3D city models

[![Python 3.9+](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![License: MIT](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)](LICENSE)
[![Tests](https://img.shields.io/badge/Tests-12%20passing-22c55e?style=flat-square)]()
[![Phase](https://img.shields.io/badge/Phase-1%20of%204-blue?style=flat-square)]()

<br/>

> GeoForge takes your 2D polygon layers (buildings, roads, water, terrain, forests, bridges, walls, fences) and a LiDAR point cloud, then automatically lifts each polygon into 3D using real measured heights — outputting clean meshes in OBJ, CityJSON, CityGML, STL, PostGIS SQL, and CSV.

</div>

---

## How it works

```
GeoJSON / Shapefile          LAS / LAZ point cloud
(polygon layers)          +  (LiDAR height data)
        │                           │
        └──────────┬────────────────┘
                   ▼
         GeoForge pipeline
                   │
         ┌─────────┴──────────┐
         │  Sample heights    │  KDTree spatial index
         │  per polygon       │  → z_ground, z_max, z_mean
         └─────────┬──────────┘
                   ▼
         ┌─────────┴──────────┐
         │  Build 3D geometry │  building  → LOD1 solid box
         │  by class          │  road      → draped surface
         │                    │  water     → flat plane
         │                    │  terrain   → Delaunay TIN
         │                    │  forest    → terrain + canopy
         │                    │  bridge    → elevated surface
         │                    │  wall/fence→ vertical slab
         └─────────┬──────────┘
                   ▼
         OBJ · CityJSON · CityGML · STL · PostGIS · CSV
```

Original polygon IDs are preserved in every output format.

---

## Tech stack

| Library | Purpose |
|---------|---------|
| `geopandas` + `fiona` | Read GeoJSON, Shapefile, GeoPackage |
| `laspy[lazrs]` | Read LAS 1.2–1.4 and LAZ point clouds |
| `scipy KDTree` | Fast spatial point lookup |
| `scipy LinearNDInterpolator` | Ground elevation interpolation |
| `shapely 2.0` | Polygon operations and containment |
| `mapbox-earcut` | Fast polygon triangulation |
| `scipy Delaunay` | Terrain surface meshing |
| `click` | Command-line interface |
| `pyyaml` | Config file parsing |

---

## Installation

### Windows (conda recommended)
```powershell
conda create -n geoforge python=3.11
conda activate geoforge
conda install -c conda-forge gdal geopandas
pip install -e .
```

### macOS
```bash
brew install gdal
pip install -e .
```

### Linux
```bash
sudo apt install gdal-bin libgdal-dev
pip install -e .
```

---

## Quick start

```bash
# Generate a built-in example project with synthetic data
geoforge generate-example --output my_project

# Run the pipeline
geoforge run my_project/config.yaml

# See what was created
ls my_project/output/
```

---

## Usage

```bash
# Basic run
geoforge run config.yaml

# Override output directory
geoforge run config.yaml --output /tmp/city

# Override formats
geoforge run config.yaml --formats obj cityjson csv

# Debug logging
geoforge run config.yaml --verbose
```

If `geoforge` is not on your PATH, use:
```bash
python -m geoforge.cli run config.yaml
```

---

## Config file

```yaml
pointcloud: data/pointcloud.las   # LAS or LAZ file
output_dir: output
crs: EPSG:32632                   # optional — embedded in CityJSON/GML

lidar_ground_classes:   [2]       # LAS class 2 = ground
lidar_building_classes: [6]       # LAS class 6 = building

grid_resolution:    1.0           # metres, for terrain interpolation
simplify_tolerance: 0.1           # metres, 0 = off
z_offset:           0.0           # global Z shift

output_formats:
  - obj
  - cityjson
  - citygml
  - stl
  - postgis
  - csv

layers:
  - path: data/buildings.geojson
    class: building               # building|road|water|terrain|forest|bridge|wall|fence
    id_field: id                  # attribute used as feature ID in output
    height_field: height_m        # optional: use this attribute instead of LiDAR
    min_height: 3.0               # minimum extrusion in metres
    offset: 0.0                   # constant Z offset

  - path: data/roads.geojson
    class: road
    id_field: id
    offset: 0.05
```

---

## Output files

| File | Description |
|------|-------------|
| `model.obj` | Wavefront OBJ — open in Blender, MeshLab |
| `model.city.json` | CityJSON 2.0 — open at ninja.cityjson.org |
| `model.gml` | CityGML 2.0 — load in QGIS, FME |
| `model.stl` | Binary STL — 3D printing ready |
| `model_postgis.sql` | PostgreSQL INSERT statements |
| `building_heights.csv` | Height summary with source IDs |

---

## Run tests

```bash
pip install pytest
pytest tests/ -v
```

---

## Roadmap

- [x] Phase 1 — Core CLI pipeline (this release)
- [ ] Phase 2 — Local 3D browser viewer (Three.js)
- [ ] Phase 3 — Live OpenStreetMap fetch by location
- [ ] Phase 4 — Real-time tile streaming (pan anywhere on Earth)

---

## License

MIT — see [LICENSE](LICENSE).

---

<div align="center">
Built by <a href="https://github.com/your-username">Mohith</a> · Give it a ⭐ if it helped you
</div>
