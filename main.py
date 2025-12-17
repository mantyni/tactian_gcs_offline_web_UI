import json
import math
import os
import sqlite3

import uvicorn
from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List

app = FastAPI()

# Allow CORS for development flexibility
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Configuration ---
MBTILES_PATH = "osm.mbtiles"


# --- Data Models ---
class Waypoint(BaseModel):
    lon: float
    lat: float


# --- Mock Data State (For Simulation) ---
# Center roughly around San Francisco as per instructions
robot_state = {"id": "rover-01", "lat": 37.41451, "lon": -122.42215, "heading": 90}
app.state.mission_waypoints = []
target_idx = -1


# --- Helper: Map Tile Logic ---
def get_tile_data(z, x, y):
    """
    Reads a tile from the SQLite MBTiles file.
    Converts XYZ (Google/OSM) Y-coordinate to TMS (Tile Map Service) Y-coordinate.
    """
    if not os.path.exists(MBTILES_PATH):
        print(f"Error: {MBTILES_PATH} not found.")
        return None

    # XYZ -> TMS conversion
    tms_y = (1 << z) - 1 - y

    conn = sqlite3.connect(MBTILES_PATH)
    cursor = conn.cursor()

    # Query following the standard MBTiles schema
    cursor.execute(
        "SELECT tile_data FROM tiles WHERE zoom_level=? AND tile_column=? AND tile_row=?",
        (z, x, tms_y),
    )
    result = cursor.fetchone()
    conn.close()

    return result[0] if result else None


# --- API Endpoints ---


@app.get("/tiles/{z}/{x}/{y}.pbf")
async def tile_server(z: int, x: int, y: int):
    """Serves vector tiles from local SQLite database, handling Gzip compression"""
    tile_data = get_tile_data(z, x, y)

    if tile_data:
        headers = {}
        # Check for GZIP magic bytes (0x1f 0x8b)
        # If the tile starts with these bytes, it is compressed.
        if tile_data[:2] == b"\x1f\x8b":
            headers["Content-Encoding"] = "gzip"

        return Response(
            content=tile_data, media_type="application/x-protobuf", headers=headers
        )
    else:
        return Response(status_code=204)


@app.get("/style.json")
async def get_style():
    """Returns the map style, dynamically injecting the host URL"""
    try:
        with open("static/style.json", "r") as f:
            style = json.load(f)
            # Ensure the tile source points to this server
            # Note: In a real deploy, swap localhost for the actual IP or hostname
            style["sources"]["openmaptiles"]["tiles"] = [
                "http://localhost:8000/tiles/{z}/{x}/{y}.pbf"
            ]
            return style
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail="style.json not found")


@app.get("/api/mission")
async def get_mission():
    print(f"--- MISSION REQUEST RECEIVED ---")
    """Returns a static GeoJSON Polygon representing the mission area"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Zone Alpha", "type": "search_area"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [
                            [mission_waypoint[0], mission_waypoint[1]]
                            for mission_waypoint in app.state.mission_waypoints
                        ]
                    ],
                },
            }
        ],
    }


def move_towards(current, target, step):
    dx = target[1] - current[1]
    dy = target[0] - current[0]
    dist = math.hypot(dx, dy)

    if dist <= step:
        return target

    return (current[0] + dy / dist * step, current[1] + dx / dist * step)


def is_robot_at_waypoint(robot_state, waypoint):
    return math.hypot(robot_state["lon"] - waypoint[0], robot_state["lat"] - waypoint[1]) < 0.00001


@app.get("/api/robot")
async def get_robot():
    """Returns robot position. Simulates slight movement for testing."""
    global robot_state
    global target_idx
    mission_waypoints = app.state.mission_waypoints

    # get the closest waypoint to start with.
    if target_idx == -1:
        target_idx = find_closest_point(Waypoint(lat=robot_state["lat"], lon=robot_state["lon"]), mission_waypoints)

    if target_idx == -1:
        # Simulate movement (wobble)
        robot_state["lon"] += 0.00001
        if robot_state["lon"] > -122.420:
            robot_state["lon"] = -122.42215
    else:
        # then follow the waypoints.
        if is_robot_at_waypoint(robot_state, mission_waypoints[target_idx]):
            target_idx = (target_idx + 1) % len(mission_waypoints)
        target_waypoint = mission_waypoints[target_idx]
        robot_state["lon"], robot_state["lat"] = move_towards((robot_state["lon"], robot_state["lat"]), target_waypoint, 0.00001)

    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": robot_state["id"],
                    "heading": robot_state["heading"],
                    "status": "ARMED",
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [robot_state["lon"], robot_state["lat"]],
                },
            }
        ],
    }


def haversine_distance(pointA: Waypoint, pointB):
    """
    Calculate the great-circle distance between two points on Earth (in meters).
    """
    R = 6371000  # Earth radius in meters

    phi1 = math.radians(pointA.lat)
    phi2 = math.radians(pointB[1])
    d_phi = math.radians(pointB[1] - pointA.lat)
    d_lambda = math.radians(pointB[0] - pointA.lon)

    a = (
        math.sin(d_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c



def find_closest_point(current_point: Waypoint, points: list):
    closest = None
    min_distance = float("inf")
    idx = -1
    for pointIdx in range(len(points)):
        point = points[pointIdx]

        distance = haversine_distance(current_point, point)
        if distance < min_distance:
            min_distance = distance
            closest = point
            idx = pointIdx
    return idx

@app.post("/api/waypoint")
async def post_waypoint(wp: Waypoint):
    """Receives a waypoint from the UI"""
    print(f"--- COMMAND RECEIVED ---")
    print(f"Target: Lat {wp.lat}, Lon {wp.lon}")
    print(f"Action: Forwarding to MAVLink handler (Stub)")
    return {"status": "accepted", "target": wp}


@app.post("/api/mission_start")
async def post_mission_start(wps: dict):
    """Receives mission from the UI"""
    app.state.mission_waypoints = wps["waypoints"]
    # straight line to the next waypoint
    return {"status": "accepted", "target": wps["waypoints"][0]}


# Mount static files (Frontend) - Must be last to avoid overriding API routes
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
