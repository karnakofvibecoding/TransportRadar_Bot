import asyncio
import logging
import os
import json
import threading
from datetime import datetime
from typing import Optional

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton, Update
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from webapp import app  # импортируем Flask-приложение

TOKEN = os.getenv("BOT_TOKEN")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")
PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://your-app.up.railway.app")

bot = Bot(token=TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

db.init_db()

# Запуск Flask в отдельном потоке
def run_flask():
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

threading.Thread(target=run_flask, daemon=True).start()

# ---------- Middleware для регистрации пользователей ----------
class RegisterUserMiddleware(BaseMiddleware):
    async def __call__(self, handler, event: Update, data: dict):
        if event.message:
            user = event.message.from_user
            db.add_user(user.id, user.username, user.first_name)
        elif event.callback_query:
            user = event.callback_query.from_user
            db.add_user(user.id, user.username, user.first_name)
        return await handler(event, data)

dp.update.middleware(RegisterUserMiddleware())

# ---------- FSM ----------
class Registration(StatesGroup):
    waiting_for_category = State()
    waiting_for_subcategory = State()
    waiting_for_comment = State()
    waiting_for_orientation_type = State()
    waiting_for_orientation = State()
    waiting_for_photo = State()

# ---------- Вспомогательные функции ----------
def get_category_label(category: str) -> str:
    return "Бобик" if category == "bobik" else "Красный берет"

def get_subcategory_label(subcat: str) -> str:
    return "Патрульный" if subcat == "patrol" else "Гражданский"

async def broadcast_new_report(author_id: int, obj_id: int, data: dict):
    """Рассылает уведомление о новом объекте всем пользователям, кроме автора."""
    category = data.get('category')
    subcategory = data.get('subcategory')
    comment = data.get('comment')
    orientation_id = data.get('orientation_id')
    orientation_type = data.get('orientation_type')
    lat = data.get('lat')
    lon = data.get('lon')

    text = f"🚨 Новый репорт #{obj_id}!\n"
    if category == 'bobik':
        text += "Категория: Бобик\n"
        if subcategory == 'patrol':
            text += "Тип: Патрульный\n"
        elif subcategory == 'civilian':
            text += "Тип: Гражданский\n"
        if comment:
            text += f"Комментарий: {comment}\n"
    else:
        text += "Категория: Красный берет\n"
    if orientation_id:
        if orientation_type == 'to':
            text += f"Направление: к ориентиру \"{orientation_id}\"\n"
        else:
            text += f"Направление: от ориентира \"{orientation_id}\"\n"
    text += f"Координаты: {lat:.6f}, {lon:.6f}\n"
    text += f"Время: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    text += "Посмотри карту: /map"

    users = db.get_all_users()
    for user_id in users:
        if user_id != author_id:
            try:
                await bot.send_message(user_id, text)
            except Exception as e:
                logging.error(f"Failed to notify user {user_id}: {e}")

# ---------- Команды ----------
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(
        "👋 Привет! Я <b>VP-Radar23</b> — бот для отметки и мониторинга объектов на карте.\n\n"
        "С моей помощью ты можешь:\n"
        "– 📍 Добавлять объекты, выбрав точку прямо на карте или отправив свою геолокацию\n"
        "– 🚙 Указывать категорию: <b>Бобик</b> (патрульный или гражданский) или <b>Красный берет</b>\n"
        "– 🧭 Задавать направление движения относительно известных ориентиров\n"
        "– 📷 Прикреплять фотографии к объектам\n"
        "– 🗺 Просматривать все репорты на интерактивной карте\n"
        "– 🔔 Получать уведомления о новых объектах от других пользователей\n\n"
        "Основные команды:\n"
        "/add — добавить объект (выбор точки на карте)\n"
        "/map — открыть карту со всеми объектами\n"
        "/start — показать это сообщение\n\n"
        "Также ты можешь просто отправить свою геолокацию, и я начну диалог добавления объекта.",
        parse_mode="HTML"
    )

@dp.message(Command("map"))
async def cmd_map(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Открыть карту", web_app={"url": PUBLIC_URL})]
    ])
    await message.answer("Нажми, чтобы открыть интерактивную карту:", reply_markup=keyboard)

@dp.message(Command("add"))
async def cmd_add(message: Message, state: FSMContext):
    await state.clear()
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Выбрать точку на карте", web_app={"url": PUBLIC_URL + "/select"})]
    ])
    await message.answer("Выбери точку на карте:", reply_markup=keyboard)

# Обработка данных от WebApp (выбор координат)
@dp.message(F.web_app_data)
async def handle_web_app_data(message: Message, state: FSMContext):
    data = message.web_app_data.data
    try:
        coords = json.loads(data)
        lat = coords['lat']
        lon = coords['lon']
    except:
        await message.answer("Ошибка получения координат.")
        return
    await state.update_data(lat=lat, lon=lon)
    await ask_category(message, state)

# Обработка геолокации (если пользователь отправил обычную)
@dp.message(F.location)
async def handle_location(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    await state.update_data(lat=lat, lon=lon)
    await ask_category(message, state)

# ---------- Диалог ----------
async def ask_category(message: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="🚙 Бобик", callback_data="cat_bobik")
    builder.button(text="🎯 Красный берет", callback_data="cat_red_beret")
    builder.adjust(2)
    await message.answer("Выбери категорию:", reply_markup=builder.as_markup())
    await state.set_state(Registration.waiting_for_category)

@dp.callback_query(F.data.startswith("cat_"))
async def choose_category(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    category = callback.data.split("_")[1]
    await state.update_data(category=category)
    await callback.message.edit_text(f"Категория: {get_category_label(category)}")
    if category == "bobik":
        builder = InlineKeyboardBuilder()
        builder.button(text="👮 Патрульный", callback_data="subcat_patrol")
        builder.button(text="👤 Гражданский", callback_data="subcat_civilian")
        builder.adjust(2)
        await callback.message.answer("Выбери тип Бобика:", reply_markup=builder.as_markup())
        await state.set_state(Registration.waiting_for_subcategory)
    else:
        await ask_orientation_type(callback.message, state)

@dp.callback_query(F.data.startswith("subcat_"))
async def choose_subcategory(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    subcat = callback.data.split("_")[1]  # patrol или civilian
    await state.update_data(subcategory=subcat)
    await callback.message.edit_text(f"Тип: {get_subcategory_label(subcat)}")
    if subcat == "civilian":
        await callback.message.answer("Оставь комментарий с описанием (или отправь '-', чтобы пропустить):")
        await state.set_state(Registration.waiting_for_comment)
    else:
        await ask_orientation_type(callback.message, state)

@dp.message(Registration.waiting_for_comment)
async def receive_comment(message: Message, state: FSMContext):
    if message.text == "-":
        await state.update_data(comment=None)
    else:
        await state.update_data(comment=message.text)
    await ask_orientation_type(message, state)

async def ask_orientation_type(message: Message, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="К ориентиру", callback_data="orient_to")
    builder.button(text="От ориентира", callback_data="orient_from")
    builder.button(text="Не указывать", callback_data="orient_none")
    builder.adjust(2)
    await message.answer("Укажи направление относительно ориентира:", reply_markup=builder.as_markup())
    await state.set_state(Registration.waiting_for_orientation_type)

@dp.callback_query(F.data.startswith("orient_"))
async def choose_orientation_type(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    action = callback.data.split("_", 1)[1]  # to, from, none
    if action == "none":
        await state.update_data(orientation_id=None, orientation_type=None)
        await save_object(callback.message, state)
        return
    await state.update_data(orientation_type=action)
    builder = InlineKeyboardBuilder()
    for name in db.ORIENTEERS.keys():
        builder.button(text=name, callback_data=f"orient_name_{name}")
    builder.adjust(1)
    await callback.message.answer("Выбери ориентир:", reply_markup=builder.as_markup())
    await state.set_state(Registration.waiting_for_orientation)

@dp.callback_query(F.data.startswith("orient_name_"))
async def choose_orientation(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    name = callback.data.split("_", 2)[2]  # после orient_name_
    await state.update_data(orientation_id=name)
    await save_object(callback.message, state)

async def save_object(message: Message, state: FSMContext):
    data = await state.get_data()
    lat = data['lat']
    lon = data['lon']
    category = data['category']
    subcategory = data.get('subcategory')
    comment = data.get('comment')
    orientation_id = data.get('orientation_id')
    orientation_type = data.get('orientation_type')

    obj_id = db.add_object(
        user_id=message.from_user.id,
        category=category,
        subcategory=subcategory,
        comment=comment,
        orientation_id=orientation_id,
        orientation_type=orientation_type,
        lat=lat,
        lon=lon
    )
    await message.answer(f"✅ Объект #{obj_id} создан!")

    # Рассылка уведомления всем (кроме автора) в фоне
    asyncio.create_task(broadcast_new_report(message.from_user.id, obj_id, data))

    builder = InlineKeyboardBuilder()
    builder.button(text="📷 Прикрепить фото", callback_data=f"photo_{obj_id}")
    builder.button(text="Пропустить", callback_data="photo_skip")
    await message.answer("Хочешь прикрепить фото?", reply_markup=builder.as_markup())
    await state.clear()
    await state.update_data(last_obj_id=obj_id)

@dp.callback_query(F.data.startswith("photo_"))
async def photo_request(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if callback.data == "photo_skip":
        await callback.message.edit_text("Фото не добавлено.")
        await state.clear()
        return
    obj_id = int(callback.data.split("_")[1])
    await state.update_data(photo_object_id=obj_id)
    await callback.message.edit_text("Отправь фото.")
    await state.set_state(Registration.waiting_for_photo)

@dp.message(F.photo, Registration.waiting_for_photo)
async def receive_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    obj_id = data['photo_object_id']
    photo = message.photo[-1]
    file_info = await bot.get_file(photo.file_id)
    downloaded = await bot.download_file(file_info.file_path)
    # Убедимся, что папка существует
    os.makedirs("/data/photos", exist_ok=True)
    filename = f"/data/photos/object_{obj_id}_{message.date.timestamp()}.jpg"
    with open(filename, "wb") as f:
        f.write(downloaded.read())
    db.add_photo(obj_id, filename)
    await message.answer("Фото сохранено!")
    await state.clear()

# ---------- Запуск ----------
async def main():
    logging.basicConfig(level=logging.INFO)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())