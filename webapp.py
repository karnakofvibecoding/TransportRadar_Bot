import os
from flask import Flask, jsonify, render_template_string, request, send_from_directory
import db

app = Flask(__name__)

PHOTOS_DIR = "/data/photos"  # путь к фото (volume) или "photos" для локального

MAP_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Карта</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body { margin:0; }
        #map { height: 100vh; width: 100%; }
        .leaflet-popup-content img { max-width:200px; max-height:200px; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([45.035470, 38.975313], 12);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap'
        }).addTo(map);

        fetch('/api/objects')
            .then(response => response.json())
            .then(data => {
                data.objects.forEach(obj => {
                    var color = (obj.category === 'bobik') ? 'orange' : 'red';
                    if (obj.category === 'bobik' && obj.subcategory === 'patrol') color = 'darkorange';
                    var markerHtml = '<div style="background:' + color + '; width:14px; height:14px; border-radius:50%; border:2px solid white; box-shadow:0 0 4px rgba(0,0,0,0.5);"></div>';
                    var marker = L.marker([obj.lat, obj.lon], {
                        icon: L.divIcon({ html: markerHtml, className: '', iconSize: [18,18], iconAnchor: [9,9] })
                    }).addTo(map);
                    var popup = '<b>#' + obj.id + '</b><br>';
                    if (obj.category === 'bobik') {
                        popup += 'Бобик (' + (obj.subcategory === 'patrol' ? 'Патрульный' : 'Гражданский') + ')<br>';
                        if (obj.comment) popup += 'Комментарий: ' + obj.comment + '<br>';
                    } else {
                        popup += 'Красный берет<br>';
                    }
                    if (obj.orientation_id) {
                        popup += 'Направление: ' + (obj.orientation_type === 'to' ? 'к' : 'от') + ' "' + obj.orientation_id + '"<br>';
                    }
                    popup += 'Время: ' + obj.timestamp;
                    if (obj.photos && obj.photos.length > 0) {
                        popup += '<br><div style="display:flex; flex-wrap:wrap; gap:5px; margin-top:5px;">';
                        obj.photos.forEach(url => {
                            popup += '<img src="' + url + '" style="width:80px;height:80px;object-fit:cover;border-radius:6px;">';
                        });
                        popup += '</div>';
                    }
                    marker.bindPopup(popup);
                });
            })
            .catch(err => console.error(err));
    </script>
</body>
</html>
"""

SELECT_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Выбор точки</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://telegram.org/js/telegram-web-app.js"></script>
    <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
    <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
    <style>
        body { margin:0; }
        #map { height: 100vh; width: 100%; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        var map = L.map('map').setView([45.035470, 38.975313], 13);
        L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
            maxZoom: 19,
            attribution: '© OpenStreetMap'
        }).addTo(map);

        map.on('click', function(e) {
            var lat = e.latlng.lat;
            var lon = e.latlng.lng;
            Telegram.WebApp.sendData(JSON.stringify({lat: lat, lon: lon}));
            Telegram.WebApp.close();
        });
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    return render_template_string(MAP_HTML)

@app.route('/select')
def select():
    return render_template_string(SELECT_HTML)

@app.route('/photos/<path:filename>')
def serve_photo(filename):
    return send_from_directory(PHOTOS_DIR, filename)

@app.route('/api/objects')
def api_objects():
    category = request.args.get('category')
    subcategory = request.args.get('subcategory')
    rows = db.get_all_objects_with_last_position(category, subcategory)
    objects = []
    for row in rows:
        obj_id, cat, subcat, comment, orient_id, orient_type, lat, lon, timestamp = row
        photo_files = db.get_photos_for_object(obj_id)
        photo_urls = [f"/photos/{os.path.basename(fp)}" for fp, _ in photo_files]
        objects.append({
            'id': obj_id,
            'category': cat,
            'subcategory': subcat,
            'comment': comment,
            'orientation_id': orient_id,
            'orientation_type': orient_type,
            'lat': lat,
            'lon': lon,
            'timestamp': timestamp,
            'photos': photo_urls
        })
    return jsonify({'objects': objects})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)