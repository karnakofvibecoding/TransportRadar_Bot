import sqlite3

DB_NAME = "transport.db"

# Ориентиры (замени координаты на свои)
ORIENTEERS = {
    "Академия": (48.088859, 38.980587),
    "Общага": (45.076829, 38.976031),
    "Чипок": (48.088853, 39.979937),
    "Старая территория": (45.012977, 38.963977),
    # Добавь свои ориентиры
}

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            first_name TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
            subcategory TEXT,
            comment TEXT,
            orientation_id TEXT,
            orientation_type TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS positions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id INTEGER NOT NULL,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS photos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            object_id INTEGER NOT NULL,
            file_path TEXT NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (object_id) REFERENCES objects (id) ON DELETE CASCADE
        )
    """)
    conn.commit()
    conn.close()

def add_user(user_id, username=None, first_name=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT OR IGNORE INTO users (user_id, username, first_name) VALUES (?, ?, ?)
    """, (user_id, username, first_name))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT user_id FROM users")
    rows = cur.fetchall()
    conn.close()
    return [row[0] for row in rows]

def add_object(user_id, category, subcategory=None, comment=None,
               orientation_id=None, orientation_type=None, lat=None, lon=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO objects (user_id, category, subcategory, comment, orientation_id, orientation_type)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (user_id, category, subcategory, comment, orientation_id, orientation_type))
    object_id = cur.lastrowid
    if lat is not None and lon is not None:
        cur.execute("INSERT INTO positions (object_id, latitude, longitude) VALUES (?, ?, ?)",
                    (object_id, lat, lon))
    conn.commit()
    conn.close()
    return object_id

def update_object_position(object_id, lat, lon):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO positions (object_id, latitude, longitude) VALUES (?, ?, ?)",
                (object_id, lat, lon))
    cur.execute("UPDATE objects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (object_id,))
    conn.commit()
    conn.close()

def get_object_info(object_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT * FROM objects WHERE id = ?", (object_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_last_position(object_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT latitude, longitude, timestamp FROM positions
        WHERE object_id = ?
        ORDER BY timestamp DESC, id DESC LIMIT 1
    """, (object_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_all_objects_with_last_position(category=None, subcategory=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    query = """
        SELECT o.id, o.category, o.subcategory, o.comment,
               o.orientation_id, o.orientation_type,
               p.latitude, p.longitude, p.timestamp
        FROM objects o
        LEFT JOIN positions p ON o.id = p.object_id
        WHERE p.id = (
            SELECT p2.id FROM positions p2
            WHERE p2.object_id = o.id
            ORDER BY p2.timestamp DESC, p2.id DESC LIMIT 1
        )
    """
    params = []
    if category:
        query += " AND o.category = ?"
        params.append(category)
    if subcategory:
        query += " AND o.subcategory = ?"
        params.append(subcategory)
    query += " ORDER BY o.id"
    cur.execute(query, params)
    rows = cur.fetchall()
    conn.close()
    return rows

def add_photo(object_id, file_path):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO photos (object_id, file_path) VALUES (?, ?)", (object_id, file_path))
    conn.commit()
    conn.close()

def get_photos_for_object(object_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT file_path, timestamp FROM photos WHERE object_id = ? ORDER BY timestamp DESC", (object_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_photo_count(object_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM photos WHERE object_id = ?", (object_id,))
    count = cur.fetchone()[0]
    conn.close()
    return count