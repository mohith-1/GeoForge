"""
osm_fetch.py — Fetch real OpenStreetMap data for any location.
Uses the free Overpass API with retry logic and multiple endpoints.
"""
from __future__ import annotations

import logging
import math
import time
from typing import Dict, List, Optional, Tuple

import geopandas as gpd
import requests
from shapely.geometry import LineString, Polygon, MultiPolygon

log = logging.getLogger(__name__)

OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.openstreetmap.ru/api/interpreter",
]

HEADERS = {
    "User-Agent": "GeoForge/3.0 (open-source 3D city model; github.com/your-username/geoforge)",
    "Accept-Charset": "utf-8",
}


def fetch_city(lat: float, lon: float,
               radius_m: float = 500) -> Dict[str, gpd.GeoDataFrame]:
    bbox = _bbox(lat, lon, radius_m)
    log.info(f"Fetching OSM data around ({lat:.4f}, {lon:.4f}) radius={radius_m}m")

    # Try each endpoint up to 3 times each
    last_error = None
    for attempt in range(3):
        for endpoint in OVERPASS_ENDPOINTS:
            try:
                raw = _query(bbox, endpoint, timeout=60 + attempt * 30)
                if raw is None:
                    continue
                elements = raw.get("elements", [])
                log.info(f"  Got {len(elements)} OSM elements from {endpoint}")
                if len(elements) == 0:
                    # Empty result — area may have sparse data, return minimal set
                    log.warning("No elements returned — using terrain-only fallback")
                    return _terrain_only(bbox)
                return _parse(elements, bbox)
            except Exception as e:
                last_error = e
                log.warning(f"  {endpoint} attempt {attempt+1} failed: {e}")
                time.sleep(2)

        if attempt < 2:
            log.info(f"  Retrying in 5s… (attempt {attempt+2}/3)")
            time.sleep(5)

    raise RuntimeError(
        f"Could not reach Overpass API after 3 attempts.\n"
        f"Last error: {last_error}\n"
        f"Please check your internet connection and try again."
    )


def geocode(place: str) -> Tuple[float, float]:
    headers = {"User-Agent": "GeoForge/3.0 (open-source; github.com/your-username/geoforge)"}
    r = requests.get(
        "https://nominatim.openstreetmap.org/search",
        params={"q": place, "format": "json", "limit": 1},
        headers=headers, timeout=15,
    )
    r.raise_for_status()
    results = r.json()
    if not results:
        raise ValueError(f"Could not find '{place}'. Try a more specific name.")
    lat, lon = float(results[0]["lat"]), float(results[0]["lon"])
    log.info(f"  Geocoded '{place}' → {lat:.5f}, {lon:.5f}")
    return lat, lon


def _bbox(lat, lon, radius_m):
    dlat = radius_m / 111_320
    dlon = radius_m / (111_320 * math.cos(math.radians(lat)))
    return (lat - dlat, lon - dlon, lat + dlat, lon + dlon)


def _query(bbox: Tuple, endpoint: str, timeout: int = 60) -> Optional[dict]:
    s, w, n, e = bbox
    bb = f"{s:.6f},{w:.6f},{n:.6f},{e:.6f}"
    query = f"""[out:json][timeout:{timeout}];
(
  way["building"]({bb});
  way["highway"~"motorway|trunk|primary|secondary|tertiary|residential|service|unclassified|pedestrian|footway|path|living_street"]({bb});
  way["natural"~"water|wood|scrub|heath|grassland|beach"]({bb});
  way["waterway"~"river|stream|canal|drain"]({bb});
  way["landuse"~"forest|grass|meadow|orchard|cemetery|park|recreation_ground|residential|commercial|industrial|retail"]({bb});
  way["leisure"~"park|garden|playground|pitch|sports_centre|nature_reserve"]({bb});
  relation["building"]({bb});
  relation["natural"~"water|wood"]({bb});
);
out geom qt;
"""
    log.info(f"  Querying {endpoint} (timeout={timeout}s)…")
    r = requests.post(
        endpoint,
        data={"data": query},
        headers=HEADERS,
        timeout=timeout + 10,
    )
    log.info(f"  HTTP {r.status_code}")
    if r.status_code == 200:
        return r.json()
    elif r.status_code == 429:
        log.warning("  Rate limited — waiting 20s")
        time.sleep(20)
        return None
    else:
        log.warning(f"  Error {r.status_code}: {r.text[:100]}")
        return None


def _terrain_only(bbox):
    """Return a minimal terrain tile when OSM returns nothing."""
    s, w, n, e = bbox
    poly = Polygon([(w,s),(e,s),(e,n),(w,n),(w,s)])
    return {"terrain": gpd.GeoDataFrame(
        [{"id":"TERRAIN_BASE","geometry":poly}], crs="EPSG:4326")}


def _parse(elements: List[dict], bbox: Tuple) -> Dict[str, gpd.GeoDataFrame]:
    rows = {"building":[],"road":[],"water":[],"forest":[],"terrain":[],"bridge":[]}

    for el in elements:
        tags = el.get("tags", {})
        geom = _to_geom(el)
        if geom is None or geom.is_empty:
            continue
        fid  = str(el.get("id",""))
        base = {"id": fid, "name": tags.get("name",""), "osm_id": fid}

        if "building" in tags or "building:part" in tags:
            if not isinstance(geom, (Polygon, MultiPolygon)):
                continue
            rows["building"].append({**base, "geometry": geom,
                                      "building_height": _height(tags),
                                      "building_type": tags.get("building","yes")})

        elif "highway" in tags:
            hw = tags["highway"]
            if hw in ("motorway","trunk","primary","secondary","tertiary",
                      "residential","service","unclassified","pedestrian",
                      "footway","path","living_street","cycleway"):
                if isinstance(geom, LineString):
                    geom = geom.buffer(_road_buf(hw))
                if isinstance(geom, (Polygon, MultiPolygon)):
                    rows["road"].append({**base, "geometry": geom, "road_type": hw})

        elif (tags.get("natural") in ("water","beach") or
              tags.get("waterway") in ("river","stream","canal","drain")):
            if isinstance(geom, LineString):
                geom = geom.buffer(_water_buf(tags))
            if isinstance(geom, (Polygon, MultiPolygon)):
                rows["water"].append({**base, "geometry": geom})

        elif (tags.get("natural") in ("wood","scrub","heath","grassland") or
              tags.get("landuse") in ("forest","orchard","meadow")):
            if isinstance(geom, (Polygon, MultiPolygon)):
                rows["forest"].append({**base, "geometry": geom})

        elif (tags.get("leisure") in ("park","garden","playground","pitch","sports_centre","nature_reserve") or
              tags.get("landuse") in ("park","recreation_ground","cemetery","grass","residential","commercial")):
            if isinstance(geom, (Polygon, MultiPolygon)):
                rows["terrain"].append({**base, "geometry": geom})

    # Always add terrain base tile
    s, w, n, e = bbox
    rows["terrain"].append({"id":"TERRAIN_BASE","name":"","osm_id":"",
                             "geometry": Polygon([(w,s),(e,s),(e,n),(w,n),(w,s)])})

    CRS = "EPSG:4326"
    result = {}
    for cls, data in rows.items():
        if data:
            result[cls] = gpd.GeoDataFrame(data, crs=CRS)
            log.info(f"  {cls}: {len(data)} features")
    return result


def _to_geom(el):
    try:
        if el.get("type") == "way":
            pts = el.get("geometry", [])
            if not pts: return None
            coords = [(p["lon"], p["lat"]) for p in pts]
            if len(coords) < 2: return None
            if coords[0] == coords[-1] and len(coords) >= 4:
                try: return Polygon(coords)
                except: return LineString(coords)
            return LineString(coords)
        elif el.get("type") == "relation":
            outer, inner = [], []
            for m in el.get("members", []):
                if m.get("type") != "way": continue
                pts = m.get("geometry", [])
                if not pts: continue
                coords = [(p["lon"], p["lat"]) for p in pts]
                if len(coords) < 3: continue
                if m.get("role") == "inner": inner.append(coords)
                else: outer.append(coords)
            polys = []
            for o in outer:
                try: polys.append(Polygon(o, inner))
                except:
                    try: polys.append(Polygon(o))
                    except: pass
            if not polys: return None
            return polys[0] if len(polys) == 1 else MultiPolygon(polys)
    except Exception as e:
        log.debug(f"Geometry error: {e}")
    return None


def _height(tags):
    for k in ("height","building:height"):
        if k in tags:
            try: return float(tags[k].replace("m","").strip())
            except: pass
    if "building:levels" in tags:
        try: return float(tags["building:levels"]) * 3.2
        except: pass
    return {"skyscraper":80,"apartments":20,"office":25,"commercial":10,
            "retail":6,"industrial":8,"warehouse":7,"hotel":30,"hospital":15,
            "school":8,"church":15,"house":7,"detached":6,"terrace":8,
            "residential":10,"yes":10}.get(tags.get("building","yes"), 10.0)


def _road_buf(hw):
    return {"motorway":8,"trunk":7,"primary":6,"secondary":5,"tertiary":4,
            "residential":3,"service":2.5,"unclassified":3,"pedestrian":2,
            "footway":1,"path":0.8,"living_street":2.5}.get(hw,3) / 111_320


def _water_buf(tags):
    return {"river":15,"canal":8,"stream":3,"drain":2}.get(
        tags.get("waterway","stream"), 4) / 111_320
