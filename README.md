# ⚙️ GeoForge

> Convert 2D map layers + LiDAR point clouds into interactive 3D city models — in your browser, for free.

![Python](https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=flat-square&logo=flask&logoColor=white)
![Three.js](https://img.shields.io/badge/Three.js-r128-black?style=flat-square&logo=threedotjs&logoColor=white)
![GeoPandas](https://img.shields.io/badge/GeoPandas-0.14-139C5A?style=flat-square)
![License](https://img.shields.io/badge/License-MIT-22c55e?style=flat-square)
![Status](https://img.shields.io/badge/Status-Active-brightgreen?style=flat-square)

---

## What is GeoForge?

GeoForge is an open-source tool that takes flat 2D building footprints, road polygons, and water bodies — combines them with LiDAR elevation data — and lifts everything into a clean, measurable 3D city model you can explore in any browser.

No Unity. No Unreal. No expensive GIS software. Just Python + a web browser.

You can type any city name and it automatically fetches real building data from OpenStreetMap, downloads free satellite elevation, and renders the 3D model in seconds. Or upload your own GeoJSON and LAS files for full control.

---

## Demo — 5 Featured Cities

Five cities are pre-built with **real, verified building heights** from public records. Click and the model appears instantly.

| City | Notable Building | Real Height |
|------|-----------------|-------------|
| 🇺🇸 New York — Midtown Manhattan | Empire State Building | 443 m |
| 🇬🇧 London — City of London | 22 Bishopsgate | 278 m |
| 🇦🇺 Melbourne — CBD | Eureka Tower | 297 m |
| 🇳🇿 Auckland — City Centre | Sky Tower | 328 m |
| 🇫🇮 Helsinki — Kamppi | Ilmarinen Tower | 88 m |

---

## Features

- **Search any location** — type a place name, GeoForge geocodes it, fetches live OSM data, downloads elevation, and builds the 3D model
- **5 instant cities** — pre-built from real public records, no internet needed after install
- **Measure tool** — click any two points in the 3D view to get the exact distance in metres
- **Layer visibility** — toggle buildings, roads, water, forests, bridges on/off independently
- **Explode view** — spread all layers vertically to inspect each one in isolation
- **Sun angle** — drag a slider to move the sun and watch shadows shift in real time
- **6 export formats** — OBJ (Blender), CityJSON (urban planning), CityGML (GIS), STL (3D printing), PostGIS SQL (databases), CSV (Excel)
- **Drag and drop** — upload your own GeoJSON polygon files + LAS/LAZ LiDAR point clouds
- **Screenshot** — one-click PNG of the current view
- **Wireframe mode** — see the triangle mesh underneath

---

## How It Works

```
You provide                        GeoForge does
─────────────────                  ──────────────────────────────────────
GeoJSON polygons      ──────────►  Read building footprints, roads, water
LAS/LAZ point cloud   ──────────►  Build KDTree spatial index
                                   Sample z_ground and z_max per polygon
                                   Extrude polygon upward by height
                                   Triangulate with earcut + Delaunay
                                   Centre geometry at world origin
                                   Export as OBJ / CityJSON / STL / etc.

OR type a city name   ──────────►  Geocode via Nominatim (free OSM)
                                   Fetch buildings + roads from Overpass API
                                   Download SRTM elevation (NASA satellite)
                                   Project to local UTM coordinates
                                   Run same pipeline above
                                   Load into Three.js viewer
```

The 8 supported layer classes each get their own geometry rule:

| Class | Geometry | Example |
|-------|----------|---------|
| `building` | Closed LOD1 solid — floor + walls + roof | Office tower |
| `road` | Draped surface following terrain | Street |
| `terrain` | Delaunay TIN from ground points | Park |
| `water` | Flat horizontal plane | River |
| `forest` | Terrain surface + canopy height offset | Tree cover |
| `bridge` | Elevated draped surface | Bridge deck |
| `wall` | Thin vertical slab | Garden wall |
| `fence` | Thin vertical slab | Fence line |

---

## Tech Stack

### Backend — Python pipeline

| Library | Version | Purpose |
|---------|---------|---------|
| `geopandas` | 0.14+ | Read GeoJSON, Shapefile, GeoPackage |
| `shapely` | 2.0+ | Polygon operations, triangulation |
| `scipy` | 1.10+ | KDTree spatial index, Delaunay meshing, interpolation |
| `numpy` | 1.24+ | Vertex arrays, coordinate math |
| `laspy` | 2.5+ | Read LAS 1.2–1.4 and LAZ point clouds |
| `pyproj` | 3.4+ | CRS projection (WGS84 → UTM) |
| `mapbox-earcut` | 1.0+ | Fast polygon triangulation |
| `requests` | 2.28+ | Overpass API, Nominatim, Open-Elevation |
| `flask` | 3.0+ | Local web server + REST API |
| `click` | 8.1+ | Command-line interface |
| `pyyaml` | 6.0+ | Config file parsing |

### Frontend — Browser viewer

| Library | Version | Purpose |
|---------|---------|---------|
| `Three.js` | r128 | WebGL 3D rendering |
| `MeshStandardMaterial` | — | PBR materials with roughness + metalness |
| `PCFSoftShadowMap` | — | Soft real-time shadows |
| `ACESFilmicToneMapping` | — | Film-quality colour grading |
| `BufferGeometry` | — | GPU-efficient triangle meshes |
| `Raycaster` | — | Mouse picking for measure tool |

### Data sources

| Source | What it provides | Cost |
|--------|-----------------|------|
| OpenStreetMap | Building footprints, roads, water, parks | Free |
| Overpass API | Real-time OSM query endpoint | Free |
| Nominatim | Place name → lat/lon geocoding | Free |
| Open-Elevation | Ground elevation at any coordinate | Free |
| OpenTopoData SRTM | NASA satellite elevation backup | Free |
| USGS 3DEP | LiDAR for US cities | Free |
| UK Environment Agency | LiDAR for England | Free |

---

## Project Structure

```
geoforge/
│
├── geoforge/                   ← Python package (the pipeline)
│   ├── config.py               ← YAML config loader + layer class validator
│   ├── lidar.py                ← LAS/LAZ reader, KDTree height sampler
│   ├── geometry.py             ← 3D mesh builder for all 8 layer classes
│   ├── exporters.py            ← OBJ / CityJSON / CityGML / STL / PostGIS / CSV writers
│   ├── pipeline.py             ← Main orchestrator for file-based runs
│   ├── osm_fetch.py            ← Overpass API client with retry logic
│   ├── dem_reader.py           ← Free elevation API client (SRTM)
│   ├── location_pipeline.py    ← Phase 3: geocode → OSM → DEM → 3D
│   ├── city_data.py            ← 5 pre-built cities with verified heights
│   ├── city_pipeline.py        ← City builder with per-city terrain profiles
│   ├── tile_system.py          ← Phase 4: tile grid + background worker
│   ├── example_gen.py          ← Synthetic demo data generator
│   └── cli.py                  ← Click CLI commands
│
├── viewer/
│   ├── server.py               ← Flask server, all REST routes
│   ├── templates/index.html    ← Complete Three.js SPA viewer (single file)
│   └── START.bat               ← Windows one-click launcher
│
├── tests/
│   └── test_geoforge.py        ← 12 unit + integration tests
│
├── app.py                      ← Hugging Face Spaces / Docker entry point
├── Dockerfile                  ← Container for cloud deployment
└── pyproject.toml              ← Package metadata + dependencies
```

---

## Installation

### Windows (recommended: conda)

```powershell
conda create -n geoforge python=3.11
conda activate geoforge
conda install -c conda-forge gdal geopandas
pip install -e .
pip install flask
```

### macOS

```bash
brew install gdal
pip install -e .
pip install flask
```

### Linux

```bash
sudo apt install gdal-bin libgdal-dev
pip install -e .
pip install flask
```

---

## Quick Start

### Option 1 — Featured city (instant, no internet needed)

```powershell
cd viewer
python server.py
# Open http://localhost:5000
# Click any city button in the sidebar
```

### Option 2 — Search any location

```powershell
cd viewer
python server.py
# Open http://localhost:5000
# Type "Shibuya Tokyo" in the search box
# Click Build 3D Model
```

### Option 3 — Your own files

```powershell
cd viewer
python server.py
# Open http://localhost:5000
# Drop your GeoJSON + LAS files into the upload zone
```

### Option 4 — CLI (no viewer)

```powershell
# Generate example data and run pipeline
python -m geoforge.cli generate-example --output my_city
python -m geoforge.cli run my_city\config.yaml

# Output files appear in my_city\output\
```

---

## Config File Format

```yaml
# config.yaml
pointcloud: data/city.las     # LAS or LAZ file
output_dir: output
crs: EPSG:32632               # Optional — embedded in CityJSON/GML

output_formats:
  - obj
  - cityjson
  - csv

layers:
  - path: data/buildings.geojson
    class: building           # building | road | water | terrain | forest | bridge | wall | fence
    id_field: id
    height_field: height_m    # optional: use attribute instead of LiDAR
    min_height: 3.0

  - path: data/roads.geojson
    class: road
    offset: 0.05              # raise slightly above terrain
```

---

## Output Files

| File | Opens in | Use for |
|------|----------|---------|
| `model.obj` | Blender, MeshLab, AutoCAD | Visualisation, rendering |
| `model.city.json` | ninja.cityjson.org, QGIS | Urban planning, analysis |
| `model.gml` | QGIS, ArcGIS, FME | GIS workflows |
| `model.stl` | Any slicer, Fusion 360 | 3D printing, CAD |
| `model_postgis.sql` | PostgreSQL + PostGIS | Spatial databases |
| `building_heights.csv` | Excel, Python, R | Data analysis |

---

## API Endpoints

The viewer server exposes a REST API so you can integrate GeoForge into other tools:

```
GET  /api/health                      → server status
GET  /api/cities                      → list 5 featured cities
POST /api/city/<key>                  → build a featured city
GET  /api/geocode?q=<place>           → geocode a place name
POST /api/build-location              → build from lat/lon + radius
POST /api/build                       → build from uploaded files
GET  /api/job/<id>                    → job status + log + outputs
GET  /api/job/<id>/file/<filename>    → download output file
GET  /api/jobs                        → list all jobs
```

---

## Running Tests

```powershell
pip install pytest
python -m pytest tests/ -v
```

12 tests covering: config loading, LiDAR sampling, building extrusion, water surfaces, OBJ export, CityJSON export, STL export, CSV export, PostGIS export, and full pipeline integration.

---

## Deployment

### Hugging Face Spaces (free)

1. Create a new Space at huggingface.co → SDK: **Docker**
2. Link to this GitHub repository
3. The Dockerfile handles everything automatically

Live URL: `https://huggingface.co/spaces/your-username/geoforge`

### Local Docker

```bash
docker build -t geoforge .
docker run -p 7860:7860 geoforge
# Open http://localhost:7860
```

---

## What I Learned Building This

If you are building something similar, here are the things that took the most debugging time:

**Coordinate systems** — UTM coordinates like `X=716036, Y=3167248` are large numbers that destroy WebGL float32 precision. You must subtract the centroid from every vertex before sending to the GPU. Always centre your geometry at world origin.

**Y-up vs Z-up** — Three.js uses Y-up (Y is vertical). GIS data uses Z-up (Z is vertical). The OBJ exporter swaps Y and Z when writing. The parser must NOT swap them again when reading — double swap = terrain appears as a vertical wall.

**CityJSON boundary nesting** — The boundary structure is `boundaries[i] = [[vi, vi, vi]]` — a surface containing one ring. `boundaries[i][0]` gives the actual triangle indices. Getting this wrong produces zero triangles.

**Overpass API rate limiting** — The free Overpass API blocks cloud server IPs. It works from home PCs but not from AWS/GCP. Always test live API calls from the actual target environment.

**LiDAR ground classification** — LAS class 2 = ground, class 6 = building. If a file has no class 2 points, fall back to using all points as ground or the interpolation will return NaN for every query.

---

## Roadmap

- [x] Phase 1 — Core CLI pipeline (8 layer classes, 6 formats, 12 tests)
- [x] Phase 2 — 3D browser viewer (Three.js, drag-drop, shadows, measure)
- [x] Phase 3 — Live OSM fetch (geocode any city, SRTM elevation)
- [x] Phase 4 — 5 featured cities (verified heights, instant load)
- [ ] Phase 5 — Real-time tile streaming (pan anywhere, background loading)
- [ ] Phase 6 — Texture mapping from aerial imagery
- [ ] Phase 7 — Time-lapse (show city growth over years)

---

## License

MIT — free to use, modify, and distribute. See [LICENSE](LICENSE).

---

<div align="center">
Built by Mohith &nbsp;·&nbsp; Give it a ⭐ if it helped you
</div>