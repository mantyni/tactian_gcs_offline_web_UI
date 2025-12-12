import sqlite3

def create_dummy():
    conn = sqlite3.connect("osm.mbtiles")
    c = conn.cursor()
    # Create the standard MBTiles schema
    c.execute("CREATE TABLE metadata (name text, value text);")
    c.execute("CREATE TABLE tiles (zoom_level integer, tile_column integer, tile_row integer, tile_data blob);")
    c.execute("create unique index name on metadata (name);")
    c.execute("create unique index tile_index on tiles (zoom_level, tile_column, tile_row);")
    
    # Insert metadata
    c.execute("INSERT INTO metadata VALUES ('name', 'dummy-map');")
    c.execute("INSERT INTO metadata VALUES ('format', 'pbf');")
    
    conn.commit()
    conn.close()
    print("Created dummy osm.mbtiles. The map will be dark, but the app will run.")

if __name__ == "__main__":
    create_dummy()
