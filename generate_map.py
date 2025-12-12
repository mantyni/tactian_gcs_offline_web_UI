import os
import requests
import subprocess
import sys

# --- Configuration ---
# Bounding box for Moffett Field, CA (min_lon, min_lat, max_lon, max_lat)
BBOX = "-122.43,37.41,-122.41,37.42"
OSM_FILE = "mission-area.osm"
MBTILES_FILE = "osm.mbtiles"

# Tilemaker configuration files (OpenMapTiles schema)
CONFIG_URL = "https://raw.githubusercontent.com/systemed/tilemaker/master/resources/config-openmaptiles.json"
PROCESS_URL = "https://raw.githubusercontent.com/systemed/tilemaker/master/resources/process-openmaptiles.lua"

def download_file(url, filename):
    print(f"Downloading {filename}...")
    r = requests.get(url, allow_redirects=True)
    r.raise_for_status()
    with open(filename, 'wb') as f:
        f.write(r.content)

def main():
    # 1. Download raw OSM data (XML) from Overpass API
    print(f"--- Fetching map data for BBOX: {BBOX} ---")
    overpass_url = f"https://overpass-api.de/api/map?bbox={BBOX}"
    download_file(overpass_url, OSM_FILE)

    # 2. Download Tilemaker configurations
    print("--- Fetching Tilemaker configs ---")
    download_file(CONFIG_URL, "config.json")
    download_file(PROCESS_URL, "process.lua")

    # 3. Run Tilemaker via Docker
    print("--- Running Tilemaker (Docker) ---")
    # We mount the current directory to /data inside the container
    cwd = os.getcwd()
    
    # Check if docker is available
    try:
        subprocess.run(["docker", "--version"], check=True, stdout=subprocess.DEVNULL)
    except (FileNotFoundError, subprocess.CalledProcessError):
        print("Error: Docker is not found or not running. Please install Docker to generate tiles.")
        sys.exit(1)

    cmd = [
        "docker", "run", "--rm",
        "-v", f"{cwd}:/data",
        "ghcr.io/systemed/tilemaker:master",
        "--input", f"/data/{OSM_FILE}",
        "--output", f"/data/{MBTILES_FILE}",
        "--config", "/data/config.json",
        "--process", "/data/process.lua"
    ]

    try:
        subprocess.run(cmd, check=True)
        print(f"\nSUCCESS! {MBTILES_FILE} generated.")
        print("You can now restart the backend to see the map.")
    except subprocess.CalledProcessError as e:
        print(f"Error running Tilemaker: {e}")

if __name__ == "__main__":
    main()
