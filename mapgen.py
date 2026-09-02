
import math
import base64
import os
from datetime import datetime
from db import get_all_objects_for_map, get_photos_for_object, get_object_last_position, get_object_history

def image_to_base64(file_path):
    if not os.path.exists(file_path):
        return None
    with open(file_path, "rb") as f:
        data = f.read()
    b64 = base64.b64encode(data).decode("utf-8")
    ext = os.path.splitext(file_path)[1].lower()
    mime = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
    return f"data:{mime};base64,{b64}"

def generate_interactive_map(category=None):
    objects = get_all_objects_for_map(category)
    if not objects:
        return None

    all_lats = [o[2] for o in objects]
    all_lons = [o[3] for o in objects]
    avg_lat = sum(all_lats) / len(all_lats)
    avg_lon = sum(all_lons) / len(all_lons)

    lat_span = max(all_lats) - min(all_lats)
    lon_span = max(all_lons) - min(all_lons)
    max_span = max(lat_span, lon_span)
    if max_span < 0.01:
        zoom = 15
    elif max_span < 0.05:
        zoom = 13
    elif max_span < 0.1:
        zoom = 12
    else:
        zoom = 10

    markers_js = []
    for obj_id, cat, lat, lon, direction in objects:
        photos = get_photos_for_object(obj_id)
        photo_html = ""
        if photos:
            latest_photo_path = photos[0][0]
            b64 = image_to_base64(latest_photo_path)
            if b64:
                photo_html = f'<img src="{b64}" style="max-width:200px; max-height:200px; border-radius:8px; margin-top:5px;">'

        last_pos = get_object_last_position(obj_id)
        timestamp = last_pos[3] if last_pos else ""

        emoji = "🚙" if cat == "bobik" else "🎯"
        cat_label = "Бобик" if cat == "bobik" else "Красный берет"

        popup_html = f"""
        <div style="font-family: sans-serif; font-size:14px;">
            <strong>{emoji} {cat_label} #{obj_id}</strong><br>
            <em>Обновлено:</em> {timestamp}<br>
            <em>Направление:</em> {direction if direction is not None else 'не указано'}°
            {photo_html}
        </div>
        """

        marker_color = "orange" if cat == "bobik" else "red"
        icon_js = f"""
        L.marker([{lat}, {lon}], {{
            icon: L.divIcon({{
                className: '',
                html: '<div style="background-color:{marker_color}; width:14px; height:14px; border-radius:50%; border:2px solid white; box-shadow: 0 0 4px rgba(0,0,0,0.5);"></div>',
                iconSize: [18, 18],
                iconAnchor: [9, 9]
            }})
        }}).addTo(map).bindPopup(`{popup_html}`);
        """
        markers_js.append(icon_js)

    html = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Карта объектов</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <style>
        body {{ margin:0; padding:0; }}
        #map {{ position:absolute; top:0; bottom:0; width:100%; }}
    </style>
</head>
<body>
    <div id="map"></div>
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <script>
        var map = L.map('map').setView([{avg_lat}, {avg_lon}], {zoom});
        L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
            maxZoom: 19,
            attribution: '© OpenStreetMap'
        }}).addTo(map);
        // Маркеры
        {''.join(markers_js)}
    </script>
</body>
</html>
"""
    return html