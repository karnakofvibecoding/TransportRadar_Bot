import os
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo
from flask import Flask, jsonify, render_template_string, request, send_from_directory
import db

app = Flask(__name__)

PHOTOS_DIR = "/data/photos"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

# ---------- HTML для просмотра карты (Яндекс.Карты) ----------
MAP_HTML = """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Карта</title>
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <script src="https://api-maps.yandex.ru/2.1/?apikey={{ api_key }}&lang=ru_RU" type="text/javascript"></script>
    <style>
        body { margin:0; }
        #map { height: 100vh; width: 100%; }
        .balloon-content img { max-width:200px; max-height:200px; border-radius:8px; margin-top:5px; }
    </style>
</head>
<body>
    <div id="map"></div>
    <script>
        ymaps.ready(function () {
            var map = new ymaps.Map('map', {
                center: [45.035470, 38.975313],
                zoom: 12,
                controls: ['zoomControl', 'searchControl', 'typeSelector', 'fullscreenControl']
            });

            fetch('/api/objects')
                .then(response => response.json())
                .then(data => {
                    data.objects.forEach(obj => {
                        var coords = [obj.lat, obj.lon];
                        var color = (obj.category === 'bobik') ? '#FF8C00' : '#FF0000';
                        if (obj.category === 'bobik' && obj.subcategory === 'patrol') color = '#FF4500';

                        var placemark = new ymaps.Placemark(coords, {
                            balloonContent: buildBalloonContent(obj)
                        }, {
                            preset: 'islands#circleIcon',
                            iconColor: color,
                            iconStrokeColor: '#ffffff',
                            iconStrokeWidth: 2
                        });

                        map.geoObjects.add(placemark);
                    });
                })
                .catch(err => console.error(err));
        });

        function buildBalloonContent(obj) {
            var html = '<b>#' + obj.id + '</b><br>';
            if (obj.category === 'bobik') {
                html += 'Бобик (' + (obj.subcategory === 'patrol' ? 'Патрульный' : 'Гражданский') + ')<br>';
                if (obj.comment) html += 'Комментарий: ' + obj.comment + '<br>';
            } else {
                html += 'Красный берет<br>';
            }
            if (obj.orientation_id) {
                if (obj.orientation_type && obj.orientation_type === 'to') {
                    html += 'Направление: к "' + obj.orientation_id + '"<br>';
                } else if (obj.orientation_type && obj.orientation_type === 'from') {
                    html += 'Направление: от "' + obj.orientation_id + '"<br>';
                } else {
                    html += 'Ориентир: ' + obj.orientation_id + '<br>';
                }
            }
            html += 'Время: ' + obj.timestamp;
            if (obj.photos && obj.photos.length > 0) {
                html += '<div style="display:flex; flex-wrap:wrap; gap:5px; margin-top:5px;">';
                obj.photos.forEach(url => {
                    html += '<img src="' + url + '" style="width:80px;height:80px;object-fit:cover;border-radius:6px;">';
                });
                html += '</div>';
            }
            return html;
        }
    </script>
</body>
</html>
"""

@app.route('/')
def index():
    api_key = os.environ.get('YANDEX_MAPS_API_KEY', '')
    if not api_key:
        return "Ошибка: не задан YANDEX_MAPS_API_KEY", 500
    return render_template_string(MAP_HTML, api_key=api_key)

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
        # Конвертируем время в московское
        try:
            dt = datetime.strptime(timestamp, '%Y-%m-%d %H:%M:%S')
            dt_utc = dt.replace(tzinfo=timezone.utc)
            dt_msk = dt_utc.astimezone(MOSCOW_TZ)
            timestamp_msk = dt_msk.strftime('%Y-%m-%d %H:%M:%S')
        except:
            timestamp_msk = timestamp  # если не удалось, оставляем как есть

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
            'timestamp': timestamp_msk,
            'photos': photo_urls
        })
    return jsonify({'objects': objects})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)