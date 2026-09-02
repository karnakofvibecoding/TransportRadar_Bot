
import sqlite3
from datetime import datetime

DB_NAME = "transport.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS objects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            category TEXT NOT NULL,
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
            direction REAL,
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

def add_object(user_id, category, lat, lon, direction=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("INSERT INTO objects (user_id, category) VALUES (?, ?)", (user_id, category))
    object_id = cur.lastrowid
    cur.execute("""
        INSERT INTO positions (object_id, latitude, longitude, direction)
        VALUES (?, ?, ?, ?)
    """, (object_id, lat, lon, direction))
    cur.execute("UPDATE objects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (object_id,))
    conn.commit()
    conn.close()
    return object_id

def update_object_position(object_id, lat, lon, direction):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO positions (object_id, latitude, longitude, direction)
        VALUES (?, ?, ?, ?)
    """, (object_id, lat, lon, direction))
    cur.execute("UPDATE objects SET updated_at = CURRENT_TIMESTAMP WHERE id = ?", (object_id,))
    conn.commit()
    conn.close()

def get_user_objects(user_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT o.id, o.category, MAX(p.timestamp)
        FROM objects o
        LEFT JOIN positions p ON o.id = p.object_id
        WHERE o.user_id = ?
        GROUP BY o.id
        ORDER BY o.id
    """, (user_id,))
    rows = cur.fetchall()
    conn.close()
    return rows

def get_object_last_position(object_id):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT latitude, longitude, direction, timestamp
        FROM positions
        WHERE object_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT 1
    """, (object_id,))
    row = cur.fetchone()
    conn.close()
    return row

def get_all_objects_for_map(category=None):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    if category:
        cur.execute("""
            SELECT o.id, o.category, p.latitude, p.longitude, p.direction
            FROM objects o
            JOIN positions p ON o.id = p.object_id
            WHERE o.category = ?
            AND p.id = (
                SELECT p2.id FROM positions p2
                WHERE p2.object_id = o.id
                ORDER BY p2.timestamp DESC, p2.id DESC
                LIMIT 1
            )
            ORDER BY o.id
        """, (category,))
    else:
        cur.execute("""
            SELECT o.id, o.category, p.latitude, p.longitude, p.direction
            FROM objects o
            JOIN positions p ON o.id = p.object_id
            WHERE p.id = (
                SELECT p2.id FROM positions p2
                WHERE p2.object_id = o.id
                ORDER BY p2.timestamp DESC, p2.id DESC
                LIMIT 1
            )
            ORDER BY o.id
        """)
    rows = cur.fetchall()
    conn.close()
    return rows

def get_object_history(object_id, limit=50):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT latitude, longitude, direction, timestamp
        FROM positions
        WHERE object_id = ?
        ORDER BY timestamp DESC, id DESC
        LIMIT ?
    """, (object_id, limit))
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

def get_all_photos_by_user(user_id, limit=10):
    conn = sqlite3.connect(DB_NAME)
    cur = conn.cursor()
    cur.execute("""
        SELECT p.file_path, p.timestamp, o.id, o.category
        FROM photos p
        JOIN objects o ON p.object_id = o.id
        WHERE o.user_id = ?
        ORDER BY p.timestamp DESC
        LIMIT ?
    """, (user_id, limit))
    rows = cur.fetchall()
    conn.close()
    return rows