"""
server.py — GeoForge 3D Viewer local web server.

Usage:
    cd viewer
    python server.py

Then open: http://localhost:5000
"""
from __future__ import annotations

import json
import logging
import subprocess
import sys
import threading
import traceback
import uuid
from pathlib import Path

from flask import Flask, jsonify, render_template, request, send_file

# ── Setup ─────────────────────────────────────────────────────────────────────
BASE    = Path(__file__).parent
JOBS    = BASE / "jobs"
UPLOADS = BASE / "uploads"
JOBS.mkdir(exist_ok=True)
UPLOADS.mkdir(exist_ok=True)

app = Flask(__name__, template_folder=str(BASE / "templates"))
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

jobs: dict[str, dict] = {}


# ── Find geoforge package ─────────────────────────────────────────────────────
def _find_geoforge():
    try:
        import geoforge
        return True
    except ImportError:
        pass

    candidates = [
        Path(__file__).parent.parent,
        Path(__file__).parent,
        Path(__file__).parent.parent.parent,
        Path("C:/GeoForge"),
        Path("C:/geoforge"),
        Path.home() / "GeoForge",
        Path.home() / "Desktop" / "GeoForge",
    ]
    for p in candidates:
        if (p / "geoforge" / "__init__.py").exists():
            if str(p) not in sys.path:
                sys.path.insert(0, str(p))
            try:
                import geoforge
                log.info(f"geoforge found at: {p}")
                return True
            except ImportError:
                continue

    log.warning("geoforge not found — trying pip install ...")
    result = subprocess.run(
        [sys.executable, "-m", "pip", "install", "geoforge", "-q"],
        capture_output=True, text=True,
    )
    if result.returncode == 0:
        try:
            import geoforge
            return True
        except ImportError:
            pass
    return False


# ═══════════════════════════════════════════════════════════
#  ROUTES
# ═══════════════════════════════════════════════════════════

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    ok = _find_geoforge()
    return jsonify({"status": "ok", "geoforge": ok})


# ── Phase 2: file upload pipeline ─────────────────────────────────────────────

@app.route("/api/example")
def run_example():
    job_id = _new_job("example")
    threading.Thread(target=_job_example, args=(job_id,), daemon=True).start()
    return jsonify({"job_id": job_id})


@app.route("/api/build", methods=["POST"])
def build():
    job_id   = _new_job("pipeline")
    job_dir  = JOBS / job_id
    data_dir = job_dir / "data"
    out_dir  = job_dir / "output"
    data_dir.mkdir(parents=True)
    out_dir.mkdir()

    las_file    = None
    layer_files = []

    for key, f in request.files.items():
        fname = f.filename or key
        dest  = data_dir / fname
        f.save(str(dest))
        ext = Path(fname).suffix.lower()
        if ext in (".las", ".laz"):
            las_file = fname
        elif ext in (".geojson", ".json", ".shp", ".gpkg", ".fgb"):
            layer_files.append(fname)

    try:
        layer_config = json.loads(request.form.get("layer_config", "[]"))
    except Exception:
        layer_config = []

    _log(job_id, f"Received {len(layer_files) + (1 if las_file else 0)} files")
    _log(job_id, f"LAS: {las_file}")
    _log(job_id, f"Layers: {layer_files}")

    threading.Thread(
        target=_job_pipeline,
        args=(job_id, job_dir, data_dir, out_dir, las_file, layer_files, layer_config),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


# ── Phase 3: location search ───────────────────────────────────────────────────

@app.route("/api/geocode")
def api_geocode():
    place = request.args.get("q", "").strip()
    if not place:
        return jsonify({"error": "Missing query parameter 'q'"}), 400
    try:
        if not _find_geoforge():
            raise ImportError("geoforge package not found")
        from geoforge.osm_fetch import geocode
        lat, lon = geocode(place)
        return jsonify({"lat": lat, "lon": lon, "place": place})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.route("/api/build-location", methods=["POST"])
def build_location():
    data   = request.get_json(force=True)
    place  = data.get("place", "")
    lat    = data.get("lat")
    lon    = data.get("lon")
    radius = max(100, min(int(data.get("radius", 500)), 2000))

    job_id  = _new_job("location")
    out_dir = JOBS / job_id / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    _log(job_id, f"Location: {place or f'{lat},{lon}'}")
    _log(job_id, f"Radius: {radius}m")

    threading.Thread(
        target=_job_location,
        args=(job_id, place, lat, lon, radius, out_dir),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


# ── Job status + file serving ──────────────────────────────────────────────────

@app.route("/api/jobs")
def list_jobs():
    return jsonify([
        {"job_id": jid, "status": j["status"],
         "mode": j.get("mode"), "outputs": j.get("outputs", [])}
        for jid, j in jobs.items()
    ])


@app.route("/api/job/<job_id>")
def job_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"error": "Unknown job"}), 404
    return jsonify(job)


@app.route("/api/job/<job_id>/file/<path:filename>")
def serve_file(job_id, filename):
    job_dir = JOBS / job_id
    for search in [job_dir / "output", job_dir]:
        target = search / filename
        if target.exists():
            return send_file(str(target), as_attachment=False)
    return jsonify({"error": "Not found"}), 404


# ═══════════════════════════════════════════════════════════
#  JOB RUNNERS
# ═══════════════════════════════════════════════════════════

def _new_job(mode: str) -> str:
    jid     = str(uuid.uuid4())[:8]
    (JOBS / jid).mkdir(exist_ok=True)
    jobs[jid] = {"status": "queued", "log": [], "outputs": [], "error": None, "mode": mode}
    return jid


def _log(job_id: str, msg: str):
    log.info(f"[{job_id}] {msg}")
    jobs[job_id]["log"].append(msg)


def _finish(job_id: str, out_dir: Path):
    outputs = []
    for f in sorted(out_dir.iterdir()):
        ext = f.suffix.lower()
        if ext in (".obj", ".json", ".gml", ".stl", ".csv", ".sql"):
            outputs.append({
                "name": f.name,
                "type": _fmt(ext),
                "url":  f"/api/job/{job_id}/file/{f.name}",
                "size": f.stat().st_size,
            })
    jobs[job_id]["outputs"] = outputs
    jobs[job_id]["status"]  = "done"
    _log(job_id, f"✓ Done — {len(outputs)} output files ready")


def _job_example(job_id):
    jobs[job_id]["status"] = "running"
    try:
        if not _find_geoforge():
            raise ImportError("geoforge package not found")
        from geoforge.example_gen import generate
        from geoforge.config import load_config
        from geoforge.pipeline import run

        job_dir = JOBS / job_id
        _log(job_id, "Generating synthetic example data ...")
        generate(job_dir)

        cfg = load_config(job_dir / "config.yaml")
        cfg.output_dir     = str(job_dir / "output")
        cfg.output_formats = ["obj", "cityjson", "citygml", "stl", "postgis", "csv"]

        _log(job_id, "Running pipeline ...")
        feats = run(cfg)
        _log(job_id, f"Pipeline complete — {len(feats)} features built")
        _finish(job_id, job_dir / "output")
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        _log(job_id, f"ERROR: {e}")
        log.error(traceback.format_exc())


def _job_pipeline(job_id, job_dir, data_dir, out_dir, las_file, layer_files, layer_config):
    jobs[job_id]["status"] = "running"
    try:
        if not _find_geoforge():
            raise ImportError("geoforge package not found")
        if not las_file:
            raise ValueError("No LAS/LAZ point cloud was uploaded.")

        import yaml
        from geoforge.config import load_config
        from geoforge.pipeline import run

        lc_map = {item["filename"]: item for item in layer_config}
        layers = []
        for fname in layer_files:
            entry = lc_map.get(fname, {})
            layers.append({
                "path":     str(data_dir / fname),
                "class":    entry.get("class") or _guess_class(fname),
                "id_field": entry.get("id_field", "id"),
            })

        cfg_data = {
            "pointcloud":     str(data_dir / las_file),
            "output_dir":     str(out_dir),
            "output_formats": ["obj", "cityjson", "citygml", "stl", "postgis", "csv"],
            "layers":         layers,
        }
        cfg_path = job_dir / "config.yaml"
        cfg_path.write_text(yaml.dump(cfg_data))

        _log(job_id, "Building config ...")
        cfg = load_config(cfg_path)
        _log(job_id, f"Running pipeline on {len(layers)} layers ...")
        feats = run(cfg)
        _log(job_id, f"Pipeline complete — {len(feats)} features built")
        _finish(job_id, out_dir)
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        _log(job_id, f"ERROR: {e}")
        log.error(traceback.format_exc())


def _job_location(job_id, place, lat, lon, radius, out_dir):
    jobs[job_id]["status"] = "running"
    try:
        if not _find_geoforge():
            raise ImportError("geoforge package not found")
        from geoforge.location_pipeline import build_from_location

        location_str = place if place else f"{lat},{lon}"

        features, _ = build_from_location(
            place    = location_str,
            radius_m = radius,
            out_dir  = out_dir,
            log_cb   = lambda msg: _log(job_id, msg),
        )

        _log(job_id, f"Pipeline complete — {len(features)} features")
        _finish(job_id, out_dir)
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        _log(job_id, f"ERROR: {e}")
        log.error(traceback.format_exc())




# ═══════════════════════════════════════════════════════════
#  FEATURED CITIES — instant 3D models
# ═══════════════════════════════════════════════════════════

@app.route("/api/cities")
def list_cities():
    if not _find_geoforge():
        return jsonify({"error": "geoforge not found"}), 500
    from geoforge.city_data import CITIES
    return jsonify([
        {"key": k, "name": v["name"], "lat": v["lat"], "lon": v["lon"],
         "description": v["description"]}
        for k, v in CITIES.items()
    ])


@app.route("/api/city/<city_key>", methods=["POST"])
def build_city_route(city_key):
    if not _find_geoforge():
        return jsonify({"error": "geoforge not found"}), 500
    from geoforge.city_data import CITIES
    if city_key not in CITIES:
        return jsonify({"error": f"Unknown city: {city_key}"}), 400

    job_id  = _new_job("city")
    out_dir = JOBS / job_id / "output"
    out_dir.mkdir(parents=True, exist_ok=True)

    threading.Thread(
        target=_job_city,
        args=(job_id, city_key, out_dir),
        daemon=True,
    ).start()
    return jsonify({"job_id": job_id})


def _job_city(job_id, city_key, out_dir):
    jobs[job_id]["status"] = "running"
    try:
        if not _find_geoforge():
            raise ImportError("geoforge not found")
        from geoforge.city_pipeline import build_city

        features, _ = build_city(
            city_key=city_key,
            out_dir=out_dir,
            log_cb=lambda msg: _log(job_id, msg),
        )
        _log(job_id, f"Pipeline complete — {len(features)} features")
        _finish(job_id, out_dir)
    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        _log(job_id, f"ERROR: {e}")
        log.error(traceback.format_exc())

# ═══════════════════════════════════════════════════════════
#  HELPERS
# ═══════════════════════════════════════════════════════════

def _fmt(ext: str) -> str:
    return {".obj":"obj",".json":"cityjson",".gml":"citygml",
            ".stl":"stl",".csv":"csv",".sql":"postgis"}.get(ext,"unknown")


def _guess_class(name: str) -> str:
    n = name.lower()
    for kw, cls in [
        ("build","building"),("road","road"),("street","road"),
        ("water","water"),("river","water"),("lake","water"),
        ("forest","forest"),("tree","forest"),("park","terrain"),
        ("bridge","bridge"),("wall","wall"),("fence","fence"),
        ("terrain","terrain"),("ground","terrain"),
    ]:
        if kw in n:
            return cls
    return "terrain"




# ═══════════════════════════════════════════════════════════
#  PHASE 4 — Tile streaming
# ═══════════════════════════════════════════════════════════
_tile_manager = None
_tile_manager_lock = threading.Lock()

def _get_tile_manager():
    global _tile_manager
    with _tile_manager_lock:
        if _tile_manager is None:
            if not _find_geoforge():
                return None
            from geoforge.tile_system import TileManager
            cache_dir = BASE / "tile_cache"
            _tile_manager = TileManager(cache_dir)
    return _tile_manager


@app.route("/api/tiles/update", methods=["POST"])
def tiles_update():
    """
    Called by the viewer when the camera moves.
    Body: { lat, lon, zoom, known_tiles: [...] }
    Returns newly ready tiles.
    """
    data  = request.get_json(force=True)
    lat   = float(data.get("lat", 0))
    lon   = float(data.get("lon", 0))
    zoom  = int(data.get("zoom", 2))
    known = data.get("known_tiles", [])

    tm = _get_tile_manager()
    if tm is None:
        return jsonify({"error": "geoforge not found"}), 500

    tm.set_camera(lat, lon, zoom)
    ready = tm.get_ready_tiles(known)
    return jsonify({
        "ready": ready,
        "status": tm.get_status(),
    })


@app.route("/api/tiles/status")
def tiles_status():
    tm = _get_tile_manager()
    if tm is None:
        return jsonify({"error": "tile manager not ready"}), 500
    return jsonify(tm.get_status())


@app.route("/api/tiles/clear", methods=["POST"])
def tiles_clear():
    global _tile_manager
    with _tile_manager_lock:
        if _tile_manager is not None:
            _tile_manager.clear_cache()
    return jsonify({"ok": True})


@app.route("/api/tiles/start", methods=["POST"])
def tiles_start():
    """
    Start tile streaming from a location.
    Body: { place, lat, lon, zoom, radius }
    """
    data   = request.get_json(force=True)
    place  = data.get("place", "")
    lat    = data.get("lat")
    lon    = data.get("lon")
    zoom   = int(data.get("zoom", 2))

    if not lat or not lon:
        if not place:
            return jsonify({"error": "Provide place or lat/lon"}), 400
        try:
            if not _find_geoforge():
                raise ImportError("geoforge not found")
            from geoforge.osm_fetch import geocode
            lat, lon = geocode(place)
        except Exception as e:
            return jsonify({"error": str(e)}), 400

    tm = _get_tile_manager()
    if tm is None:
        return jsonify({"error": "geoforge not found"}), 500

    tm.set_camera(lat, lon, zoom)
    return jsonify({"lat": lat, "lon": lon, "zoom": zoom, "ok": True})

# ═══════════════════════════════════════════════════════════
#  ENTRY POINT
# ═══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print()
    print("=" * 52)
    print("  GeoForge 3D Viewer — Phase 3")
    print("  Open in browser -> http://localhost:5000")
    print("=" * 52)
    print()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
