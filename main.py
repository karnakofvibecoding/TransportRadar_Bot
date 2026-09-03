import asyncio
import logging
import os
import threading
from datetime import datetime
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher, F, BaseMiddleware
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton, Update
)
from aiogram.utils.keyboard import InlineKeyboardBuilder

import db
from webapp import app

# ---------- Токен ----------
TOKEN = os.getenv("BOT_TOKEN")
if not TOKEN:
    raise RuntimeError("BOT_TOKEN не задан")

PUBLIC_URL = os.environ.get("PUBLIC_URL", "https://your-app.up.railway.app")
MOSCOW_TZ = ZoneInfo("Europe/Moscow")

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
    waiting_for_location_method = State()
    waiting_for_location = State()
    waiting_for_orientation_select = State()
    waiting_for_category = State()
    waiting_for_subcategory = State()
    waiting_for_comment = State()
    waiting_for_confirmation = State()
    waiting_for_photo = State()

# ---------- Клавиатура с командами ----------
def get_main_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="/add"), KeyboardButton(text="/map")],
            [KeyboardButton(text="/start")]
        ],
        resize_keyboard=True
    )

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
    lat = data.get('lat')
    lon = data.get('lon')

    moscow_time = datetime.now(MOSCOW_TZ).strftime('%Y-%m-%d %H:%M:%S')

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
        text += f"Ориентир: {orientation_id}\n"
    text += f"Координаты: {lat:.6f}, {lon:.6f}\n"
    text += f"Время: {moscow_time}\n"
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
        "– 📍 Добавлять объекты, указав местоположение (геолокацией или через ориентир)\n"
        "– 🚙 Указывать категорию: <b>Бобик</b> (патрульный или гражданский) или <b>Красный берет</b>\n"
        "– 📷 Прикреплять фотографии к объектам\n"
        "– 🗺 Просматривать все репорты на интерактивной карте\n"
        "– 🔔 Получать уведомления о новых объектах от других пользователей\n\n"
        "Основные команды:\n"
        "/add — добавить объект\n"
        "/map — открыть карту со всеми объектами\n"
        "/start — показать это сообщение\n\n"
        "Ты можешь сразу отправить свою геолокацию, и я начну диалог добавления.",
        parse_mode="HTML",
        reply_markup=get_main_keyboard()
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
    builder = InlineKeyboardBuilder()
    builder.button(text="📍 Геолокация", callback_data="loc_geo")
    builder.button(text="🏛 Ориентир", callback_data="loc_orient")
    builder.adjust(2)
    await message.answer("Как указать местоположение?", reply_markup=builder.as_markup())
    await state.set_state(Registration.waiting_for_location_method)

# ---------- Обработка выбора способа ----------
@dp.callback_query(F.data == "loc_geo", Registration.waiting_for_location_method)
async def choose_loc_geo(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("Отправь свою геолокацию (кнопка 📎 -> Локация).")
    await state.set_state(Registration.waiting_for_location)

@dp.callback_query(F.data == "loc_orient", Registration.waiting_for_location_method)
async def choose_loc_orient(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    builder = InlineKeyboardBuilder()
    for name in db.ORIENTEERS.keys():
        builder.button(text=name, callback_data=f"orient_{name}")
    builder.adjust(1)
    await callback.message.answer("Выбери ориентир:", reply_markup=builder.as_markup())
    await state.set_state(Registration.waiting_for_orientation_select)

# ---------- Обработка геолокации (если прислана без команды) ----------
@dp.message(F.location)
async def handle_location_any(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    await state.update_data(lat=lat, lon=lon)
    await ask_category(message, state)

# ---------- Обработка геолокации в состоянии ожидания ----------
@dp.message(F.location, Registration.waiting_for_location)
async def handle_location_in_state(message: Message, state: FSMContext):
    lat = message.location.latitude
    lon = message.location.longitude
    await state.update_data(lat=lat, lon=lon)
    await ask_category(message, state)

# ---------- Обработка выбора ориентира ----------
@dp.callback_query(F.data.startswith("orient_"), Registration.waiting_for_orientation_select)
async def choose_orientation(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    name = callback.data.split("_", 1)[1]
    if name not in db.ORIENTEERS:
        await callback.message.answer("Такого ориентира нет.")
        return
    lat, lon = db.ORIENTEERS[name]
    await state.update_data(lat=lat, lon=lon, orientation_id=name)
    await callback.message.answer(f"Выбран ориентир: {name}")
    await ask_category(callback.message, state)

# ---------- Диалог: категория ----------
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
    if await state.get_state() != Registration.waiting_for_category.state:
        return
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
        await show_confirmation(callback.message, state)

@dp.callback_query(F.data.startswith("subcat_"))
async def choose_subcategory(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if await state.get_state() != Registration.waiting_for_subcategory.state:
        return
    subcat = callback.data.split("_")[1]  # patrol или civilian
    await state.update_data(subcategory=subcat)
    await callback.message.edit_text(f"Тип: {get_subcategory_label(subcat)}")
    if subcat == "civilian":
        await callback.message.answer("Оставь комментарий с описанием (или отправь '-', чтобы пропустить):")
        await state.set_state(Registration.waiting_for_comment)
    else:
        await show_confirmation(callback.message, state)

@dp.message(Registration.waiting_for_comment)
async def receive_comment(message: Message, state: FSMContext):
    if message.text == "-":
        await state.update_data(comment=None)
    else:
        await state.update_data(comment=message.text)
    await show_confirmation(message, state)

# ---------- Подтверждение ----------
async def show_confirmation(message: Message, state: FSMContext):
    data = await state.get_data()
    lat = data.get('lat')
    lon = data.get('lon')
    category = data.get('category')
    subcategory = data.get('subcategory')
    comment = data.get('comment')
    orientation_id = data.get('orientation_id')

    text = "📋 <b>Проверь данные репорта:</b>\n\n"
    if category == 'bobik':
        text += f"Категория: Бобик\n"
        if subcategory == 'patrol':
            text += "Тип: Патрульный\n"
        elif subcategory == 'civilian':
            text += "Тип: Гражданский\n"
        if comment:
            text += f"Комментарий: {comment}\n"
    else:
        text += "Категория: Красный берет\n"
    if orientation_id:
        text += f"Ориентир: {orientation_id}\n"
    text += f"Координаты: {lat:.6f}, {lon:.6f}"

    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Подтвердить", callback_data="confirm_yes")
    builder.button(text="❌ Отмена", callback_data="confirm_no")
    builder.adjust(2)
    await message.answer(text, parse_mode="HTML", reply_markup=builder.as_markup())
    await state.set_state(Registration.waiting_for_confirmation)

@dp.callback_query(F.data == "confirm_yes")
async def confirm_yes(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    if await state.get_state() != Registration.waiting_for_confirmation.state:
        return
    data = await state.get_data()
    await save_object(callback.message, state, data)

@dp.callback_query(F.data == "confirm_no")
async def confirm_no(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_text("Добавление отменено.")
    await state.clear()

# ---------- Сохранение объекта ----------
async def save_object(message: Message, state: FSMContext, data: dict):
    lat = data['lat']
    lon = data['lon']
    category = data['category']
    subcategory = data.get('subcategory')
    comment = data.get('comment')
    orientation_id = data.get('orientation_id')

    obj_id = db.add_object(
        user_id=message.from_user.id,
        category=category,
        subcategory=subcategory,
        comment=comment,
        orientation_id=orientation_id,
        orientation_type=None,
        lat=lat,
        lon=lon
    )
    logging.info(f"Объект #{obj_id} создан")
    await message.answer(f"✅ Объект #{obj_id} создан!")

    # Рассылка уведомления
    asyncio.create_task(broadcast_new_report(message.from_user.id, obj_id, data))

    builder = InlineKeyboardBuilder()
    builder.button(text="📷 Прикрепить фото", callback_data=f"photo_{obj_id}")
    builder.button(text="Пропустить", callback_data="photo_skip")
    await message.answer("Хочешь прикрепить фото?", reply_markup=builder.as_markup())
    await state.clear()
    await state.update_data(last_obj_id=obj_id)

# ---------- Фото ----------
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