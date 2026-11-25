import asyncio
import logging
import os
import aiosqlite
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from flask import Flask
from threading import Thread

# --- НАСТРОЙКИ ---
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))  # По умолчанию 0, если не задано
SHOP_NAME = "SloNik_ShoP"

logging.basicConfig(level=logging.INFO)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# --- ФЕЙКОВЫЙ ВЕБ-СЕРВЕР ДЛЯ RENDER ---
# (Чтобы Render не убивал бота, так как он ищет открытый порт)
app = Flask(__name__)

@app.route('/')
def home():
    return f"Bot {SHOP_NAME} is running!"

def run_flask():
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

# --- БАЗА ДАННЫХ ---
async def init_db():
    async with aiosqlite.connect("shop.db") as db:
        await db.execute("""CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            balance REAL DEFAULT 0.0
        )""")
        await db.execute("""CREATE TABLE IF NOT EXISTS deals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            seller_id INTEGER,
            buyer_id INTEGER,
            item_desc TEXT,
            status TEXT DEFAULT 'pending'
        )""")
        await db.commit()

# --- СОСТОЯНИЯ (FSM) ---
class AdminStates(StatesGroup):
    waiting_for_buyer = State()
    waiting_for_desc = State()
    waiting_for_user_to_add_balance = State()
    waiting_for_amount = State()

# --- КЛАВИАТУРЫ ---
def main_menu():
    kb = [
        [KeyboardButton(text="🛒 Купить / Выбрать игру")],
        [KeyboardButton(text="💳 Мой баланс"), KeyboardButton(text="🆘 Поддержка")]
    ]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

def admin_menu():
    kb = [[KeyboardButton(text="👑 Админ-панель")]]
    return ReplyKeyboardMarkup(keyboard=kb, resize_keyboard=True)

# --- ХЕНДЛЕРЫ (ПОЛЬЗОВАТЕЛИ) ---
@dp.message(Command("start"))
async def cmd_start(message: types.Message):
    async with aiosqlite.connect("shop.db") as db:
        await db.execute("INSERT OR IGNORE INTO users (user_id) VALUES (?)", (message.from_user.id,))
        await db.commit()
    
    if message.from_user.id == ADMIN_ID:
        await message.answer(f"👑 Привет, Админ!\nПанель управления **{SHOP_NAME}** готова.", reply_markup=admin_menu(), parse_mode="Markdown")
    else:
        await message.answer(f"👋 Добро пожаловать в **{SHOP_NAME}**!\n\nЗдесь вы можете купить игровые аккаунты и валюту.", reply_markup=main_menu(), parse_mode="Markdown")

@dp.message(F.text == "💳 Мой баланс")
async def show_balance(message: types.Message):
    async with aiosqlite.connect("shop.db") as db:
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (message.from_user.id,)) as cursor:
            row = await cursor.fetchone()
            balance = row[0] if row else 0.0
    await message.answer(f"💳 Ваш баланс в **{SHOP_NAME}**: `{balance}` руб.\n\nДля пополнения напишите в поддержку.", parse_mode="Markdown")

@dp.message(F.text == "🆘 Поддержка")
async def support(message: types.Message):
    await message.answer(f"🆘 Связь с администратором **{SHOP_NAME}**: @ваш_никнейм", parse_mode="Markdown")

@dp.message(F.text == "🛒 Купить / Выбрать игру")
async def buy_menu(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="🎮 Игра 1 (Валюта)", callback_data="buy_game_1"))
    builder.row(InlineKeyboardButton(text="🎮 Игра 2 (Аккаунт)", callback_data="buy_game_2"))
    await message.answer(f"🛒 Выберите категорию в **{SHOP_NAME}**:", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data.startswith("buy_"))
async def process_buy(callback: types.CallbackQuery):
    game = callback.data.split("_")[2]
    await callback.message.answer(f"Вы выбрали игру {game}. Создаю сделку...")
    await callback.answer()

# --- ХЕНДЛЕРЫ (АДМИН) ---
@dp.message(F.text == "👑 Админ-панель", F.from_user.id == ADMIN_ID)
async def admin_panel(message: types.Message):
    builder = InlineKeyboardBuilder()
    builder.row(InlineKeyboardButton(text="Создать сделку", callback_data="admin_create_deal"))
    builder.row(InlineKeyboardButton(text="Выдать баланс", callback_data="admin_add_balance"))
    await message.answer(f"👑 Админ-панель **{SHOP_NAME}**:", reply_markup=builder.as_markup(), parse_mode="Markdown")

@dp.callback_query(F.data == "admin_create_deal")
async def admin_deal_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_buyer)
    await callback.message.answer("Введите ID или @юзернейм покупателя:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_buyer)
async def admin_deal_buyer(message: types.Message, state: FSMContext):
    await state.update_data(buyer=message.text)
    await state.set_state(AdminStates.waiting_for_desc)
    await message.answer("Введите описание товара:")

@dp.message(AdminStates.waiting_for_desc)
async def admin_deal_desc(message: types.Message, state: FSMContext):
    data = await state.get_data()
    buyer = data['buyer']
    desc = message.text
    
    async with aiosqlite.connect("shop.db") as db:
        await db.execute("INSERT INTO deals (buyer_id, item_desc) VALUES (?, ?)", (buyer, desc))
        await db.commit()
    
    await message.answer(f"✅ Сделка создана!\nПокупатель: {buyer}\nТовар: {desc}")
    await state.clear()

@dp.callback_query(F.data == "admin_add_balance")
async def admin_balance_start(callback: types.CallbackQuery, state: FSMContext):
    await state.set_state(AdminStates.waiting_for_user_to_add_balance)
    await callback.message.answer("Введите ID пользователя, которому начислить баланс:")
    await callback.answer()

@dp.message(AdminStates.waiting_for_user_to_add_balance)
async def admin_balance_user(message: types.Message, state: FSMContext):
    await state.update_data(target_user=message.text)
    await state.set_state(AdminStates.waiting_for_amount)
    await message.answer("Введите сумму:")

@dp.message(AdminStates.waiting_for_amount)
async def admin_balance_amount(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = data['target_user']
    try:
        amount = float(message.text)
        async with aiosqlite.connect("shop.db") as db:
            await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
            await db.commit()
        await message.answer(f"✅ Пользователю {user_id} начислено {amount} руб.")
        try:
            await bot.send_message(user_id, f"Ваш баланс в {SHOP_NAME} пополнен на {amount} руб.")
        except:
            pass
    except ValueError:
        await message.answer("Ошибка. Введите число.")
    await state.clear()

# --- ЗАПУСК ---
async def main():
    await init_db()
    # Запускаем фейковый веб-сервер в фоне, чтобы Render думал, что это веб-приложение
    Thread(target=run_flask, daemon=True).start()
    
    print(f"Бот {SHOP_NAME} запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
