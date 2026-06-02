"""
config.py — Load and validate the GeoForge YAML config file.

Every pipeline run starts here. This module reads your config.yaml,
checks that every layer class is valid, applies sensible defaults,
and hands a clean Config object to the rest of the pipeline.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


# ── Supported layer classes ────────────────────────────────────────────────
LAYER_CLASSES = {
    "building", "water", "road", "terrain",
    "forest", "bridge", "wall", "fence",
}

# ── Default behaviour per class ────────────────────────────────────────────
CLASS_DEFAULTS: Dict[str, Dict[str, Any]] = {
    "building": {"height_source": "lidar_max",    "base_source": "lidar_ground", "min_height": 3.0,  "offset": 0.0},
    "water":    {"height_source": "lidar_min",    "base_source": "lidar_min",    "min_height": 0.0,  "offset": 0.0},
    "road":     {"height_source": "lidar_ground", "base_source": "lidar_ground", "min_height": 0.0,  "offset": 0.05},
    "terrain":  {"height_source": "lidar_ground", "base_source": "lidar_ground", "min_height": 0.0,  "offset": 0.0},
    "forest":   {"height_source": "lidar_max",    "base_source": "lidar_ground", "min_height": 5.0,  "offset": 0.0},
    "bridge":   {"height_source": "lidar_max",    "base_source": "lidar_ground", "min_height": 0.0,  "offset": 0.2},
    "wall":     {"height_source": "lidar_max",    "base_source": "lidar_ground", "min_height": 1.0,  "offset": 0.0},
    "fence":    {"height_source": "lidar_max",    "base_source": "lidar_ground", "min_height": 0.5,  "offset": 0.0},
}


@dataclass
class LayerConfig:
    """One entry from the 'layers:' list in config.yaml."""
    path:          str
    layer_class:   str
    id_field:      str            = "id"
    height_field:  Optional[str]  = None   # use this attribute instead of LiDAR
    height_source: str            = "lidar_max"
    base_source:   str            = "lidar_ground"
    min_height:    float          = 0.0
    offset:        float          = 0.0


@dataclass
class Config:
    """Full validated configuration for one GeoForge pipeline run."""
    pointcloud:             str
    output_dir:             str
    layers:                 List[LayerConfig]
    crs:                    Optional[str]   = None
    output_formats:         List[str]       = field(default_factory=lambda: ["obj", "cityjson", "csv"])
    lidar_ground_classes:   List[int]       = field(default_factory=lambda: [2])
    lidar_building_classes: List[int]       = field(default_factory=lambda: [6])
    grid_resolution:        float           = 1.0
    simplify_tolerance:     float           = 0.0
    z_offset:               float           = 0.0
    base_dir:               Path            = field(default_factory=Path.cwd)

    def resolve(self, p: str) -> str:
        """Turn a relative path into an absolute path based on config file location."""
        return p if os.path.isabs(p) else str(self.base_dir / p)


def load_config(path: str | Path) -> Config:
    """Read a YAML config file and return a validated Config object."""
    path = Path(path)
    with open(path) as fh:
        raw = yaml.safe_load(fh)

    base_dir = path.parent.resolve()
    layers   = []

    for entry in raw.get("layers", []):
        cls = entry.get("class", "terrain").lower()
        if cls not in LAYER_CLASSES:
            raise ValueError(
                f"Unknown layer class '{cls}'.\n"
                f"Valid classes: {sorted(LAYER_CLASSES)}"
            )
        d = CLASS_DEFAULTS[cls]
        layers.append(LayerConfig(
            path          = entry["path"],
            layer_class   = cls,
            id_field      = entry.get("id_field",      "id"),
            height_field  = entry.get("height_field",  None),
            height_source = entry.get("height_source", d["height_source"]),
            base_source   = entry.get("base_source",   d["base_source"]),
            min_height    = float(entry.get("min_height", d["min_height"])),
            offset        = float(entry.get("offset",     d["offset"])),
        ))

    return Config(
        pointcloud             = raw["pointcloud"],
        output_dir             = raw.get("output_dir", "output"),
        layers                 = layers,
        crs                    = raw.get("crs"),
        output_formats         = [f.lower() for f in raw.get("output_formats", ["obj", "cityjson", "csv"])],
        lidar_ground_classes   = raw.get("lidar_ground_classes",   [2]),
        lidar_building_classes = raw.get("lidar_building_classes", [6]),
        grid_resolution        = float(raw.get("grid_resolution",    1.0)),
        simplify_tolerance     = float(raw.get("simplify_tolerance", 0.0)),
        z_offset               = float(raw.get("z_offset",           0.0)),
        base_dir               = base_dir,
    )
