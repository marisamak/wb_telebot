# main.py — обновлённый бот с отслеживанием цен по настоящей цене (HTML) и управлением через кнопки

import asyncio
import logging
import requests
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery
from bs4 import BeautifulSoup
from datetime import datetime

API_TOKEN = "8092555394:AAHwvVmGcJYGw3Gu_LZe4aJ0U3K1v2aHqUw"
CHECK_INTERVAL = 3600
DB_FILE = "tracking.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

from aiogram.client.default import DefaultBotProperties

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)

dp = Dispatcher()

# === База данных ===
conn = sqlite3.connect(DB_FILE)
c = conn.cursor()
c.execute("""
CREATE TABLE IF NOT EXISTS products (
    user_id INTEGER,
    product_id TEXT,
    name TEXT,
    brand TEXT,
    url TEXT,
    last_price INTEGER,
    PRIMARY KEY (user_id, product_id)
)
""")
conn.commit()

# === Получение настоящей цены ===
def get_real_current_price(product_id):
    # ⚠️ Fallback к API, пока сайт блокирует HTML
    data = get_product_data(product_id)
    if data:
        return data.get("price")
    return None

# === Получение информации о товаре ===
def get_product_data(product_id):
    url = f"https://card.wb.ru/cards/detail?appType=1&curr=rub&dest=-1257786&nm={product_id}"
    try:
        r = requests.get(url, timeout=10)
        print(f"[WB API] Status: {r.status_code}")
        print(f"[WB API] JSON (cut): {r.text[:500]}")  # первые 500 символов

        data = r.json().get("data", {}).get("products", [])
        if not data:
            print("❌ products[] пустой!")
            return None

        prod = data[0]
        print(f"✅ Найден товар: {prod.get('name')}")

        return {
            "id": str(prod["id"]),
            "name": prod.get("name", "Без названия"),
            "brand": prod.get("brand", "Без бренда"),
            "price": prod.get("salePriceU", 0) // 100,
            "old_price": prod.get("priceU", 0) // 100,
            "rating": prod.get("reviewRating", 0),
            "feedbacks": prod.get("feedbacks", 0),
            "image": f"https://images.wbstatic.net/big/new/{prod['id']}-1.jpg",
            "url": f"https://www.wildberries.ru/catalog/{prod['id']}/detail.aspx"
        }

    except Exception as e:
        print(f"❌ Ошибка в get_product_data: {e}")
        return None


# === Клавиатура выбора действий ===
def get_main_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить товар", callback_data="add")],
        [InlineKeyboardButton(text="📋 Мои товары", callback_data="list")]
    ])

# === Кнопка трекинга после ввода ID ===
def get_track_keyboard(product_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Отслеживать этот товар", callback_data=f"track:{product_id}")]
    ])

# === Старт ===
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer("Привет! Я помогу отслеживать настоящие цены на Wildberries.", reply_markup=get_main_keyboard())

# === Обработка кнопки "Добавить товар" ===
@dp.callback_query(F.data == "add")
async def add_product_prompt(callback: CallbackQuery):
    await callback.message.answer("✏️ Введи ID товара, который нужно отслеживать:")

# === Обработка ввода ID вручную ===
@dp.message(F.text.regexp("^\\d{6,}$"))
async def user_entered_id(message: types.Message):
    product_id = message.text.strip()
    await message.answer(f"Найден товар с ID: {product_id}", reply_markup=get_track_keyboard(product_id))

# === Обработка кнопки отслеживания ===
@dp.callback_query(F.data.startswith("track:"))
async def track_product(callback: CallbackQuery):
    product_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    data = get_product_data(product_id)
    price = get_real_current_price(product_id)

    if not data or price is None:
        await callback.message.answer("Не удалось получить информацию о товаре.")
        return

    url = f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx"

    with conn:
        conn.execute("""
        INSERT OR REPLACE INTO products (user_id, product_id, name, brand, url, last_price)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, product_id, data['name'], data['brand'], url, price))

    caption = (
        f"🆔 {product_id}\n"
        f"<a href='{url}'>{data['name']}</a>\n"
        f"🏷 {data['brand']}\n"
        f"💸 Цена: <b>{price} ₽</b>\n"
        f"⭐️ {data['rating']} (отзывов: {data['feedbacks']})"
    )

    try:
        await bot.send_photo(chat_id=user_id, photo=data['image'], caption=caption)
    except:
        await bot.send_message(chat_id=user_id, text=caption)

# === Показать список товаров ===
@dp.callback_query(F.data == "list")
async def show_list(callback: CallbackQuery):
    user_id = callback.from_user.id
    rows = conn.execute("SELECT product_id, name, last_price FROM products WHERE user_id=?", (user_id,)).fetchall()
    if not rows:
        await callback.message.answer("Список пуст. Добавь товар через кнопку.")
    else:
        text = "📋 Отслеживаемые товары:\n"
        for pid, name, price in rows:
            text += f"🆔 {pid} — {name} — {price} ₽\n"
        await callback.message.answer(text)

# === Фоновая проверка цен ===
async def check_price_changes():
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        logger.info("⏳ Проверка цен...")
        rows = conn.execute("SELECT user_id, product_id, last_price, name, brand, url FROM products").fetchall()
        for user_id, pid, old_price, name, brand, url in rows:
            new_price = get_real_current_price(pid)
            if new_price is not None and new_price < old_price:
                diff = old_price - new_price
                data = get_product_data(pid)
                caption = (
                    f"📉 <b>Цена снизилась!</b>\n"
                    f"<a href='{url}'>{name}</a> (ID {pid})\n"
                    f"💸 Была: <s>{old_price} ₽</s> → Стала: <b>{new_price} ₽</b>\n"
                    f"💰 Экономия: {diff} ₽\n"
                    f"⭐️ {data['rating']} (отзывов: {data['feedbacks']})\n"
                    f"🏷 {brand}"
                )
                try:
                    await bot.send_message(user_id, caption)
                except:
                    pass
                with conn:
                    conn.execute("UPDATE products SET last_price=? WHERE product_id=? AND user_id=?", (new_price, pid, user_id))

# === Запуск ===
async def main():
    asyncio.create_task(check_price_changes())
    logger.info("Бот запущен!")
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())
