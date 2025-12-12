import sqlite3
import math
import json
from fastapi import FastAPI, HTTPException, Response
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import uvicorn
import os

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
    lat: float
    lon: float

# --- Mock Data State (For Simulation) ---
# Center roughly around San Francisco as per instructions
robot_state = {
    "id": "rover-01",
    "lat": 37.41451,
    "lon": -122.42215,
    "heading": 90
}

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
        (z, x, tms_y)
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
        if tile_data[:2] == b'\x1f\x8b':
            headers["Content-Encoding"] = "gzip"

        return Response(
            content=tile_data, 
            media_type="application/x-protobuf", 
            headers=headers
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
    """Returns a static GeoJSON Polygon representing the mission area"""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {"name": "Zone Alpha", "type": "search_area"},
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [[
                        [-122.4230, 37.4150],
                        [-122.4210, 37.4150],
                        [-122.4210, 37.4135],
                        [-122.4230, 37.4135],
                        [-122.4230, 37.4150]
                    ]]
                }
            }
        ]
    }

@app.get("/api/robot")
async def get_robot():
    """Returns robot position. Simulates slight movement for testing."""
    global robot_state
    
    # Simulate movement (wobble)
    robot_state["lon"] += 0.00001
    if robot_state["lon"] > -122.420: 
        robot_state["lon"] = -122.42215 # Reset if it goes too far
        
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "properties": {
                    "id": robot_state["id"], 
                    "heading": robot_state["heading"],
                    "status": "ARMED"
                },
                "geometry": {
                    "type": "Point",
                    "coordinates": [robot_state["lon"], robot_state["lat"]]
                }
            }
        ]
    }

@app.post("/api/waypoint")
async def post_waypoint(wp: Waypoint):
    """Receives a waypoint from the UI"""
    print(f"--- COMMAND RECEIVED ---")
    print(f"Target: Lat {wp.lat}, Lon {wp.lon}")
    print(f"Action: Forwarding to MAVLink handler (Stub)")
    return {"status": "accepted", "target": wp}

# Mount static files (Frontend) - Must be last to avoid overriding API routes
app.mount("/", StaticFiles(directory="static", html=True), name="static")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)
