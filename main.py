
import asyncio
import logging
import io
import math
import os
from typing import Optional

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, BufferedInputFile
from aiogram.utils.keyboard import InlineKeyboardBuilder

from geopy.geocoders import Nominatim
from geopy.exc import GeocoderTimedOut, GeocoderUnavailable

import db
import mapgen

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")


bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

db.init_db()

watch_tasks = {}

geolocator = Nominatim(user_agent="transport_radar_bot")

class Registration(StatesGroup):
    waiting_for_location_or_name = State()
    waiting_for_category = State()
    waiting_for_object_choice = State()
    waiting_for_direction = State()
    waiting_for_custom_angle = State()
    waiting_for_location_name = State()
    waiting_for_photo = State()

def calculate_bearing(lat1, lon1, lat2, lon2):
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    dlon = math.radians(lon2 - lon1)
    y = math.sin(dlon) * math.cos(lat2_rad)
    x = math.cos(lat1_rad) * math.sin(lat2_rad) - math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(dlon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360) % 360

async def get_coordinates_from_name(name: str) -> Optional[tuple]:
    try:
        location = await asyncio.to_thread(geolocator.geocode, name, timeout=10)
        if location:
            return location.latitude, location.longitude
        else:
            return None
    except (GeocoderTimedOut, GeocoderUnavailable) as e:
        logging.error(f"Geocoding error: {e}")
        return None

def get_category_label(category: str) -> str:
    return "Бобик" if category == "bobik" else "Красный берет"

def get_category_emoji(category: str) -> str:
    return "🚙" if category == "bobik" else "🎯"

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "Привет! Я бот‑радар для отметки транспорта.\n"
        "Ты можешь:\n"
        "– Отправить геолокацию или название места\n"
        "– Выбрать категорию: Бобик (🚙) или Красный берет (🎯)\n"
        "– Указать направление (или я определю сам, если это обновление)\n"
        "– Прикрепить фото\n"
        "– Смотреть карту: /map\n"
        "– Фильтровать: /map bobik или /map red_beret\n"
        "– Включить автообновление: /watch\n"
        "– Посмотреть фото: /photos или /photo <id>\n\n"
        "Просто отправь геолокацию или название места, чтобы начать."
    )

@dp.message(Command("map"))
async def cmd_map(message: Message, command: Optional[str] = None):
    if command and command.args:
        category = command.args.strip().lower()
        if category in ("bobik", "red_beret"):
            await send_map(message, category)
            return
    await send_map(message, None)

@dp.message(Command("watch"))
async def cmd_watch(message: Message, state: FSMContext):
    user_id = message.from_user.id
    if user_id in watch_tasks:
        await message.answer("Автообновление уже запущено. Используй /stop_watch для остановки.")
        return
    await message.answer("Запускаю автообновление карты каждые 30 секунд.")
    task = asyncio.create_task(auto_update_map(user_id))
    watch_tasks[user_id] = task

@dp.message(Command("stop_watch"))
async def cmd_stop_watch(message: Message):
    user_id = message.from_user.id
    task = watch_tasks.pop(user_id, None)
    if task:
        task.cancel()
        await message.answer("Автообновление остановлено.")
    else:
        await message.answer("Автообновление не было запущено.")

async def auto_update_map(user_id: int):
    try:
        while True:
            await asyncio.sleep(30)
            await send_map_to_user(user_id, None)
    except asyncio.CancelledError:
        pass

async def send_map(message: Message, category: Optional[str]):
    await message.answer("Генерирую интерактивную карту, подожди...")
    html_content = mapgen.generate_interactive_map(category)
    if html_content:
        file_obj = io.BytesIO(html_content.encode('utf-8'))
        await message.answer_document(document=BufferedInputFile(file_obj.getvalue(), filename="map.html"))
    else:
        await message.answer("Нет данных для отображения.")

async def send_map_to_user(user_id: int, category: Optional[str]):
    try:
        html_content = mapgen.generate_interactive_map(category)
        if html_content:
            file_obj = io.BytesIO(html_content.encode('utf-8'))
            await bot.send_document(user_id, document=BufferedInputFile(file_obj.getvalue(), filename="map.html"))
        else:
            await bot.send_message(user_id, "Нет данных для отображения.")
    except Exception as e:
        logging.error(f"Failed to send map to user {user_id}: {e}")

@dp.message(F.location)
async def handle_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    await state.update_data(lat=lat, lon=lon)
    await ask_category(message, state)

@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    current_state = await state.get_state()
    if current_state == Registration.waiting_for_location_name.state:
        name = message.text.strip()
        coords = await get_coordinates_from_name(name)
        if coords:
            lat, lon = coords
            await state.update_data(lat=lat, lon=lon)
            await ask_category(message, state)
        else:
            await message.answer("Не удалось найти координаты по этому названию. Попробуй другое.")
        return

    if current_state == Registration.waiting_for_custom_angle.state:
        try:
            angle = int(message.text)
            if 0 <= angle <= 360:
                data = await state.get_data()
                await save_position(message, state, data, angle)
            else:
                await message.answer("Угол должен быть от 0 до 360.")
        except ValueError:
            await message.answer("Пожалуйста, отправь число.")
        return

    if message.text.startswith('/'):
        return

    await message.answer(
        "Я ожидаю геолокацию или название места.\n"
        "Нажми 📎 -> Локация, или напиши текстом название (например, 'Москва, Красная площадь')."
    )
    await state.set_state(Registration.waiting_for_location_name)

async def ask_category(message: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="🚙 Бобик", callback_data="cat_bobik")
    builder.button(text="🎯 Красный берет", callback_data="cat_red_beret")
    builder.adjust(2)
    await message.answer("Выбери категорию:", reply_markup=builder.as_markup())
    await state.set_state(Registration.waiting_for_category)

@dp.callback_query(F.data.startswith("cat_"))
async def choose_category(callback: CallbackQuery, state: FSMContext):
    category = callback.data.split("_", 1)[1]
    await state.update_data(category=category)
    await callback.message.edit_text(f"Категория: {get_category_emoji(category)} {get_category_label(category)}")

    user_id = callback.from_user.id
    objects = db.get_user_objects(user_id)
    if objects:
        builder = InlineKeyboardBuilder()
        builder.button(text="➕ Новый объект", callback_data="obj_new")
        for obj in objects:
            obj_id, obj_cat, _ = obj
            builder.button(
                text=f"Обновить #{obj_id} ({get_category_emoji(obj_cat)} {get_category_label(obj_cat)})",
                callback_data=f"obj_{obj_id}"
            )
        builder.adjust(1)
        await callback.message.answer("Это новый объект или обновление существующего?", reply_markup=builder.as_markup())
        await state.set_state(Registration.waiting_for_object_choice)
    else:
        await create_new_object(callback.message, state)

@dp.callback_query(F.data == "obj_new")
async def new_object(callback: CallbackQuery, state: FSMContext):
    await create_new_object(callback.message, state)

@dp.callback_query(F.data.startswith("obj_"))
async def choose_existing_object(callback: CallbackQuery, state: FSMContext):
    object_id = int(callback.data.split("_")[1])
    await state.update_data(object_id=object_id)
    last_pos = db.get_object_last_position(object_id)
    if last_pos:
        data = await state.get_data()
        lat = data['lat']
        lon = data['lon']
        old_lat, old_lon, _, _ = last_pos
        if abs(lat - old_lat) > 0.0001 or abs(lon - old_lon) > 0.0001:
            bearing = calculate_bearing(old_lat, old_lon, lat, lon)
            await callback.message.answer(f"Направление определено автоматически: {bearing:.0f}°")
            await save_position(callback.message, state, data, bearing)
            return
        else:
            await callback.message.answer("Координаты не изменились. Обновление не требуется.")
            await state.clear()
            return
    else:
        await ask_direction(callback.message, state)

async def create_new_object(message: Message, state: FSMContext):
    data = await state.get_data()
    lat = data['lat']
    lon = data['lon']
    category = data['category']
    await ask_direction(message, state)

async def ask_direction(message: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    directions = [
        ("Север (0°)", "dir_0"),
        ("Северо-восток (45°)", "dir_45"),
        ("Восток (90°)", "dir_90"),
        ("Юго-восток (135°)", "dir_135"),
        ("Юг (180°)", "dir_180"),
        ("Юго-запад (225°)", "dir_225"),
        ("Запад (270°)", "dir_270"),
        ("Северо-запад (315°)", "dir_315"),
    ]
    for label, data in directions:
        builder.button(text=label, callback_data=data)
    builder.button(text="Ввести угол вручную", callback_data="dir_custom")
    builder.adjust(2)
    await message.answer("Выбери направление движения:", reply_markup=builder.as_markup())
    await state.set_state(Registration.waiting_for_direction)

@dp.callback_query(F.data.startswith("dir_"))
async def choose_direction(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    if data == "dir_custom":
        await callback.message.answer("Отправь угол в градусах (0–360, где 0 – север):")
        await state.set_state(Registration.waiting_for_custom_angle)
        return
    angle = int(data.split("_")[1])
    data_dict = await state.get_data()
    await save_position(callback.message, state, data_dict, angle)

async def save_position(message: Message, state: FSMContext, data: dict, direction: float):
    lat = data['lat']
    lon = data['lon']
    category = data['category']

    if 'object_id' in data:
        object_id = data['object_id']
        db.update_object_position(object_id, lat, lon, direction)
        await message.answer(f"✅ Позиция объекта #{object_id} обновлена.")
    else:
        object_id = db.add_object(message.from_user.id, category, lat, lon, direction)
        await message.answer(f"✅ Новый объект #{object_id} ({get_category_label(category)}) создан.")

    builder = InlineKeyboardBuilder()
    builder.button(text="📷 Да, прикрепить фото", callback_data="photo_yes")
    builder.button(text="⏭ Пропустить", callback_data="photo_no")
    await message.answer("Хотите прикрепить фото к этому объекту?", reply_markup=builder.as_markup())
    await state.set_state(Registration.waiting_for_photo)

@dp.callback_query(F.data == "photo_yes", Registration.waiting_for_photo)
async def photo_yes(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Отправьте фото (можно с подписью).")

@dp.callback_query(F.data == "photo_no", Registration.waiting_for_photo)
async def photo_no(callback: CallbackQuery, state: FSMContext):
    await callback.message.edit_text("Фото не прикреплено.")
    await state.clear()

@dp.message(F.photo, Registration.waiting_for_photo)
async def receive_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    object_id = data.get('object_id')
    if not object_id:
        await message.answer("Ошибка: не найден ID объекта.")
        await state.clear()
        return

    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    downloaded = await bot.download_file(file_info.file_path)

    os.makedirs("photos", exist_ok=True)
    filename = f"photos/object_{object_id}_{int(message.date.timestamp())}.jpg"
    with open(filename, "wb") as f:
        f.write(downloaded.read())

    db.add_photo(object_id, filename)

    await message.answer("✅ Фото сохранено!")
    await state.clear()

@dp.message(Command("photos"))
async def cmd_photos(message: Message):
    user_id = message.from_user.id
    photos = db.get_all_photos_by_user(user_id, limit=10)
    if not photos:
        await message.answer("У вас пока нет фотографий.")
        return
    for file_path, timestamp, obj_id, category in photos:
        caption = f"Объект #{obj_id} ({get_category_label(category)})\nВремя: {timestamp}"
        with open(file_path, "rb") as f:
            await message.answer_photo(photo=BufferedInputFile(f.read(), filename=os.path.basename(file_path)), caption=caption)

@dp.message(Command("photo"))
async def cmd_photo(message: Message):
    try:
        object_id = int(message.text.split()[1])
    except (IndexError, ValueError):
        await message.answer("Использование: /photo <object_id>")
        return
    photos = db.get_photos_for_object(object_id)
    if not photos:
        await message.answer(f"У объекта #{object_id} нет фотографий.")
        return
    for file_path, timestamp in photos:
        with open(file_path, "rb") as f:
            await message.answer_photo(photo=BufferedInputFile(f.read(), filename=os.path.basename(file_path)), caption=f"Объект #{object_id}\nВремя: {timestamp}")

async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())