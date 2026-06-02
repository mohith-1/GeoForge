<div align="center">

<img src="https://img.shields.io/badge/⚙️-GeoForge-58a6ff?style=for-the-badge&labelColor=0d1117" alt="GeoForge">

# GeoForge — 3D City Viewer

**Convert 2D map data + LiDAR into interactive 3D city models. In your browser. For free.**

[![Live Demo](https://img.shields.io/badge/🚀_Live_Demo-Hugging_Face-FFD21E?style=for-the-badge&logo=huggingface&logoColor=black)](https://huggingface.co/spaces/Moe32/Geoforge)
[![GitHub](https://img.shields.io/badge/GitHub-mohith--1%2FGeoForge-181717?style=for-the-badge&logo=github)](https://github.com/mohith-1/GeoForge)
[![License: MIT](https://img.shields.io/badge/License-MIT-22c55e?style=for-the-badge)](LICENSE)

[![Python](https://img.shields.io/badge/Python-3.9+-3776AB?style=flat-square&logo=python&logoColor=white)](https://python.org)
[![Flask](https://img.shields.io/badge/Flask-3.0-000000?style=flat-square&logo=flask&logoColor=white)](https://flask.palletsprojects.com)
[![Three.js](https://img.shields.io/badge/Three.js-r128-black?style=flat-square&logo=threedotjs)](https://threejs.org)
[![GeoPandas](https://img.shields.io/badge/GeoPandas-0.14-139C5A?style=flat-square)](https://geopandas.org)
[![Docker](https://img.shields.io/badge/Docker-ready-2496ED?style=flat-square&logo=docker&logoColor=white)](Dockerfile)

</div>

---

## 🎬 What is GeoForge?

GeoForge is an open-source tool that takes flat 2D building footprints and road polygons, combines them with LiDAR elevation data, and lifts everything into a clean interactive 3D city model you can explore in any browser.

No Unity. No Unreal. No expensive GIS software. Just Python and a web browser.

**Type any city name** → GeoForge fetches live OpenStreetMap data, downloads free satellite elevation, and renders the 3D model in seconds. Or upload your own GeoJSON and LAS/LAZ files for full control.

---

## 🏙️ Featured Cities

Five cities pre-built with **real verified building heights** from public records. Click once — model appears instantly.

| &nbsp; | City | District | Tallest Building | Height |
|--------|------|----------|-----------------|--------|
| 🇺🇸 | **New York City** | Midtown Manhattan | Empire State Building | 443 m |
| 🇬🇧 | **London** | City of London | 22 Bishopsgate | 278 m |
| 🇦🇺 | **Melbourne** | CBD | Eureka Tower | 297 m |
| 🇳🇿 | **Auckland** | City Centre | Sky Tower | 328 m |
| 🇫🇮 | **Helsinki** | Kamppi | Ilmarinen Tower | 88 m |

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| 🏗️ **5 Featured Cities** | Real heights from public records — instant load, no internet needed |
| 🌍 **Search Any Location** | Type any city name — fetches live OpenStreetMap data automatically |
| 📏 **Measure Tool** | Click two points in the 3D view — get exact distance in metres |
| 🎨 **Layer Colours** | Buildings, roads, water, forests all visually distinct |
| 💡 **Dynamic Shadows** | Drag sun angle slider — shadows update in real time |
| 💥 **Explode View** | Separate all layers vertically to inspect each one |
| 📷 **Screenshot** | One-click PNG export of the current view |
| 🔭 **Wireframe Mode** | See the triangle mesh underneath every model |
| 📦 **6 Export Formats** | OBJ · CityJSON · CityGML · STL · PostGIS SQL · CSV |
| 🖱️ **Drag & Drop** | Upload your own GeoJSON + LAS/LAZ files |
| 🔄 **Job History** | Previous builds auto-restore on page reload |

---

## 🗺️ How It Works

```
Input                          GeoForge Pipeline                    Output
─────────────────────          ──────────────────────────────────   ──────────────
GeoJSON polygons      ──────►  Read building footprints             model.obj
LAS/LAZ point cloud   ──────►  Build KDTree spatial index           model.city.json
                               Sample z_ground + z_max per polygon  model.gml
                               Extrude polygon upward by height     model.stl
                               Triangulate (earcut + Delaunay)      model_postgis.sql
                               Centre geometry at world origin      building_heights.csv
                               Export to all 6 formats

OR type a city name   ──────►  Geocode via Nominatim (free OSM)
                               Fetch buildings + roads from Overpass API
                               Download SRTM elevation (NASA)
                               Project to local UTM coordinates
                               Run same pipeline above
                               Load into Three.js viewer
```

### 8 Supported Layer Classes

| Class | Geometry Built | Looks Like |
|-------|---------------|------------|
| `building` | Closed solid box — floor + 4 walls + roof | City towers |
| `road` | Surface draped onto terrain | Street grid |
| `terrain` | Delaunay TIN from ground points | Ground surface |
| `water` | Flat horizontal plane | River / harbour |
| `forest` | Terrain + canopy height offset | Tree cover |
| `bridge` | Elevated draped surface | Bridge deck |
| `wall` | Thin vertical slab | Garden wall |
| `fence` | Thin vertical slab | Fence line |

---

## 🛠️ Tech Stack

### 🐍 Python Backend

| Library | Purpose |
|---------|---------|
| ![GeoPandas](https://img.shields.io/badge/geopandas-0.14-139C5A?style=flat-square) | Read GeoJSON, Shapefile, GeoPackage |
| ![Shapely](https://img.shields.io/badge/shapely-2.0-blue?style=flat-square) | Polygon operations, triangulation |
| ![SciPy](https://img.shields.io/badge/scipy-1.10-8CAAE6?style=flat-square) | KDTree spatial index, Delaunay meshing |
| ![NumPy](https://img.shields.io/badge/numpy-1.24-013243?style=flat-square&logo=numpy) | Vertex arrays, coordinate math |
| ![laspy](https://img.shields.io/badge/laspy-2.5-green?style=flat-square) | Read LAS 1.2–1.4 and LAZ point clouds |
| ![PyProj](https://img.shields.io/badge/pyproj-3.4-blue?style=flat-square) | CRS projection — WGS84 → UTM |
| ![Flask](https://img.shields.io/badge/flask-3.0-000000?style=flat-square&logo=flask&logoColor=white) | REST API + local web server |
| ![Requests](https://img.shields.io/badge/requests-2.28-red?style=flat-square) | Overpass API, Nominatim, Open-Elevation |

### 🌐 Browser Frontend

| Technology | Purpose |
|-----------|---------|
| ![Three.js](https://img.shields.io/badge/Three.js-r128-black?style=flat-square&logo=threedotjs) | WebGL 3D rendering engine |
| `MeshStandardMaterial` | PBR materials — roughness + metalness per layer |
| `PCFSoftShadowMap` | Soft real-time shadow casting |
| `ACESFilmicToneMapping` | Film-quality colour grading |
| `BufferGeometry` | GPU-efficient triangle mesh storage |
| `Raycaster` | Mouse picking for the measure tool |

### 🌍 Data Sources — All Free

| Source | Provides | Cost |
|--------|---------|------|
| OpenStreetMap | Building footprints, roads, water, parks | Free |
| Overpass API | Real-time OSM query endpoint | Free |
| Nominatim | Place name → lat/lon geocoding | Free |
| Open-Elevation | Ground elevation at any coordinate | Free |
| OpenTopoData SRTM | NASA satellite elevation backup | Free |

---

## 📁 Project Structure

```
geoforge/
│
├── geoforge/                    ← Python package — the 3D pipeline
│   ├── config.py                ← YAML config loader + layer class validator
│   ├── lidar.py                 ← LAS/LAZ reader, KDTree height sampler
│   ├── geometry.py              ← 3D mesh builder for all 8 layer classes
│   ├── exporters.py             ← OBJ / CityJSON / CityGML / STL / PostGIS / CSV
│   ├── pipeline.py              ← Orchestrator for file-based runs
│   ├── osm_fetch.py             ← Overpass API client with retry logic
│   ├── dem_reader.py            ← Free elevation API client (SRTM)
│   ├── location_pipeline.py     ← Geocode → OSM → DEM → 3D
│   ├── city_data.py             ← 5 pre-built cities with verified heights
│   ├── city_pipeline.py         ← City builder with per-city terrain profiles
│   ├── example_gen.py           ← Synthetic demo data generator
│   └── cli.py                   ← Click CLI commands
│
├── viewer/
│   ├── server.py                ← Flask server + all REST API routes
│   ├── templates/index.html     ← Complete Three.js viewer (single file SPA)
│   └── START.bat                ← Windows one-click launcher
│
├── tests/
│   └── test_geoforge.py         ← 12 unit + integration tests
│
├── app.py                       ← Hugging Face Spaces / Docker entry point
├── Dockerfile                   ← Container for cloud deployment
└── pyproject.toml               ← Package metadata + dependencies
```

---

## 🚀 Quick Start

### Option 1 — Try the live demo
👉 **[huggingface.co/spaces/Moe32/Geoforge](https://huggingface.co/spaces/Moe32/Geoforge)**

No installation. Opens in browser. Click any city button.

---

### Option 2 — Run locally

**Windows**
```powershell
git clone https://github.com/mohith-1/GeoForge.git
cd GeoForge
pip install -e .
pip install flask
cd viewer
python server.py
# Open http://localhost:5000
```

**macOS**
```bash
brew install gdal
git clone https://github.com/mohith-1/GeoForge.git
cd GeoForge && pip install -e . && pip install flask
cd viewer && python server.py
```

**Linux**
```bash
sudo apt install gdal-bin libgdal-dev
git clone https://github.com/mohith-1/GeoForge.git
cd GeoForge && pip install -e . && pip install flask
cd viewer && python server.py
```

---

### Option 3 — Docker

```bash
docker build -t geoforge .
docker run -p 7860:7860 geoforge
# Open http://localhost:7860
```

---

### Option 4 — CLI only (no browser)

```bash
# Generate example project with synthetic data
python -m geoforge.cli generate-example --output my_city

# Run the pipeline
python -m geoforge.cli run my_city/config.yaml

# Output files appear in my_city/output/
```

---

## ⚙️ Config File

```yaml
# config.yaml
pointcloud: data/city.las       # LAS or LAZ file
output_dir: output
crs: EPSG:32632                 # Optional — embedded in CityJSON/GML

output_formats:
  - obj
  - cityjson
  - stl
  - csv

layers:
  - path: data/buildings.geojson
    class: building             # building|road|water|terrain|forest|bridge|wall|fence
    id_field: id
    height_field: height_m      # optional: use this attribute instead of LiDAR
    min_height: 3.0             # minimum extrusion in metres

  - path: data/roads.geojson
    class: road
    offset: 0.05                # raise slightly above terrain
```

---

## 📡 REST API

The viewer server exposes a full REST API:

```
GET  /api/cities                      List 5 featured cities
POST /api/city/<key>                  Build a featured city
GET  /api/geocode?q=<place>           Geocode a place name
POST /api/build-location              Build from lat/lon + radius
POST /api/build                       Build from uploaded files
GET  /api/job/<id>                    Job status + log + outputs
GET  /api/job/<id>/file/<filename>    Download output file
GET  /api/jobs                        List all past jobs
GET  /api/health                      Server health check
```

---

## 🧪 Tests

```bash
pip install pytest
python -m pytest tests/ -v
```

12 tests — config loading, LiDAR sampling, building extrusion, water surfaces, all 5 export formats, and full pipeline integration.

---

## 💡 Key Technical Learnings

Things that took the most debugging time — useful if you are building something similar:

**1. Float32 precision at large coordinates**
UTM coordinates like `X=716036, Y=3167248` destroy WebGL float32 precision. You must subtract the centroid from every vertex before uploading to the GPU. Always centre geometry at world origin.

**2. Y-up vs Z-up coordinate systems**
Three.js uses Y-up (Y is vertical). GIS data uses Z-up (Z is elevation). The OBJ exporter swaps Y and Z when writing. The parser must not swap them again — double swap makes flat terrain appear as a vertical wall.

**3. CityJSON boundary nesting**
The boundary structure is `boundaries[i] = [[vi, vi, vi]]` — a surface containing one ring. Getting this wrong produces zero triangles with no error.

**4. Overpass API and cloud IPs**
The free Overpass API blocks cloud server IP addresses. It works from home broadband but not from AWS or GCP. Always test live API calls from the actual target machine.

**5. LiDAR classification fallback**
LAS class 2 = ground, class 6 = buildings. If a file has no class 2 points, fall back to using all points as ground or every polygon gets NaN elevation.

---

## 🗺️ Roadmap

- [x] Phase 1 — Core CLI pipeline (8 layer classes, 6 formats, 12 tests)
- [x] Phase 2 — 3D browser viewer (Three.js, drag-drop, shadows, measure)
- [x] Phase 3 — Live OSM fetch (geocode any city, SRTM elevation)
- [x] Phase 4 — 5 featured cities (verified heights, instant load)
- [ ] Phase 5 — Real-time tile streaming (pan anywhere, background loading)
- [ ] Phase 6 — Texture mapping from aerial imagery
- [ ] Phase 7 — City growth time-lapse

---

## 📄 License

MIT — free to use, modify, and distribute. See [LICENSE](LICENSE).

---

<div align="center">

Built by **Mohith** &nbsp;·&nbsp; Give it a ⭐ if it helped you

**[🚀 Live Demo](https://huggingface.co/spaces/Moe32/Geoforge)** &nbsp;·&nbsp; **[📦 GitHub](https://github.com/mohith-1/GeoForge)**

</div>