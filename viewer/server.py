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
app.config["MAX_CONTENT_LENGTH"] = 2 * 1024 * 1024 * 1024  # 2 GB

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger(__name__)

# In-memory job store
jobs: dict[str, dict] = {}


# ── Ensure geoforge is importable ─────────────────────────────────────────────
def _find_geoforge():
    """
    Search for the geoforge package in common locations.
    Works whether geoforge is pip-installed or sitting next to viewer/.
    """
    try:
        import geoforge
        return True
    except ImportError:
        pass

    candidates = [
        Path(__file__).parent.parent,           # C:\GeoForge  (viewer is C:\GeoForge\viewer)
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

    # Last resort: pip install
    log.warning("geoforge not found — trying pip install …")
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


# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/health")
def health():
    ok = _find_geoforge()
    return jsonify({"status": "ok", "geoforge": ok})


@app.route("/api/example")
def run_example():
    """Generate synthetic example data and run the pipeline."""
    job_id = _new_job("example")
    t = threading.Thread(target=_job_example, args=(job_id,), daemon=True)
    t.start()
    return jsonify({"job_id": job_id})


@app.route("/api/build", methods=["POST"])
def build():
    """
    Accept uploaded files and run the GeoForge pipeline.
    Expects multipart/form-data with:
      - One or more GeoJSON / Shapefile files
      - One LAS or LAZ point cloud
      - layer_config: JSON string mapping filename -> class
    """
    job_id  = _new_job("pipeline")
    job_dir = JOBS / job_id
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

    t = threading.Thread(
        target=_job_pipeline,
        args=(job_id, job_dir, data_dir, out_dir, las_file, layer_files, layer_config),
        daemon=True,
    )
    t.start()
    return jsonify({"job_id": job_id})


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


# ── Job runners ───────────────────────────────────────────────────────────────
def _new_job(mode: str) -> str:
    jid = str(uuid.uuid4())[:8]
    job_dir = JOBS / jid
    job_dir.mkdir(exist_ok=True)
    jobs[jid] = {"status": "queued", "log": [], "outputs": [], "error": None, "mode": mode}
    return jid


def _log(job_id: str, msg: str):
    log.info(f"[{job_id}] {msg}")
    jobs[job_id]["log"].append(msg)


def _finish(job_id: str, out_dir: Path):
    """Collect output files and mark job done."""
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


def _job_example(job_id: str):
    jobs[job_id]["status"] = "running"
    try:
        if not _find_geoforge():
            raise ImportError("geoforge package not found")
        from geoforge.example_gen import generate
        from geoforge.config import load_config
        from geoforge.pipeline import run

        job_dir = JOBS / job_id
        _log(job_id, "Generating synthetic example data …")
        generate(job_dir)

        cfg = load_config(job_dir / "config.yaml")
        cfg.output_dir     = str(job_dir / "output")
        cfg.output_formats = ["obj", "cityjson", "citygml", "stl", "postgis", "csv"]

        _log(job_id, "Running pipeline …")
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

        # Build layer config
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
            "pointcloud":    str(data_dir / las_file),
            "output_dir":    str(out_dir),
            "output_formats": ["obj", "cityjson", "citygml", "stl", "postgis", "csv"],
            "layers":        layers,
        }
        cfg_path = job_dir / "config.yaml"
        cfg_path.write_text(yaml.dump(cfg_data))

        _log(job_id, "Building config …")
        cfg = load_config(cfg_path)

        _log(job_id, f"Running pipeline on {len(layers)} layers …")
        feats = run(cfg)
        _log(job_id, f"Pipeline complete — {len(feats)} features built")
        _finish(job_id, out_dir)

    except Exception as e:
        jobs[job_id]["status"] = "error"
        jobs[job_id]["error"]  = str(e)
        _log(job_id, f"ERROR: {e}")
        log.error(traceback.format_exc())


# ── Helpers ───────────────────────────────────────────────────────────────────
def _fmt(ext: str) -> str:
    return {".obj": "obj", ".json": "cityjson", ".gml": "citygml",
            ".stl": "stl", ".csv": "csv", ".sql": "postgis"}.get(ext, "unknown")


def _guess_class(name: str) -> str:
    n = name.lower()
    for kw, cls in [
        ("build", "building"), ("road", "road"), ("street", "road"),
        ("water", "water"), ("river", "water"), ("lake", "water"),
        ("forest", "forest"), ("tree", "forest"), ("park", "terrain"),
        ("bridge", "bridge"), ("wall", "wall"), ("fence", "fence"),
        ("terrain", "terrain"), ("ground", "terrain"), ("dem", "terrain"),
    ]:
        if kw in n:
            return cls
    return "terrain"


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print()
    print("=" * 52)
    print("  GeoForge 3D Viewer")
    print("  Open in browser → http://localhost:5000")
    print("=" * 52)
    print()
    app.run(host="0.0.0.0", port=5000, debug=False, threaded=True)
