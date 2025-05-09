# main.py — бот с удобным меню и поддержкой ссылок

import asyncio
import logging
import re
import sqlite3
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.client.default import DefaultBotProperties
import requests

# Настройки
API_TOKEN = "8092555394:AAHwvVmGcJYGw3Gu_LZe4aJ0U3K1v2aHqUw"
CHECK_INTERVAL = 3600  # Проверка каждые 1 час
DB_FILE = "tracking.db"

# Логирование
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Инициализация бота
bot = Bot(token=API_TOKEN, default=DefaultBotProperties(parse_mode="HTML"))
dp = Dispatcher()

# Подключение к БД
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


# ===== КЛАВИАТУРЫ =====
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить товар")],
            [KeyboardButton(text="📋 Мои товары"), KeyboardButton(text="❌ Удалить товар")],
            [KeyboardButton(text="⚙️ Настройки")]
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )


def get_cancel_button():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )


# ===== ОБРАБОТКА ТОВАРОВ =====
def extract_product_id(text):
    # Из ссылки: https://www.wildberries.ru/catalog/12345678/detail.aspx
    if "wildberries.ru" in text:
        match = re.search(r"catalog/(\d+)", text)
        if match:
            return match.group(1)

    # Из ID: 12345678
    if text.isdigit() and len(text) >= 6:
        return text

    return None


def get_product_data(product_id):
    def parse_html_price(prod_id):
        try:
            url = f"https://www.wildberries.ru/catalog/{prod_id}/detail.aspx"
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'ru-RU,ru;q=0.9'
            }
            response = requests.get(url, headers=headers, timeout=10)

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser')
                price_tag = soup.find('h2', class_='price-history__title')
                if price_tag:
                    price_text = price_tag.get_text(strip=True)
                    # Удаляем всё, кроме цифр (и учитываем &nbsp; как пробел)
                    return int(''.join(filter(str.isdigit, price_text.replace('&nbsp;', ''))))
        except Exception as e:
            print(f"[HTML Price Error] {e}")
        return None

    try:
        # 1. Получаем базовые данные из API
        api_url = f"https://card.wb.ru/cards/detail?appType=1&curr=rub&dest=-1257786&nm={product_id}"
        api_response = requests.get(api_url, timeout=10)

        if api_response.status_code != 200:
            return None

        data = api_response.json()
        products = data.get("data", {}).get("products", [])
        if not products:
            return None

        prod = products[0]

        # 2. Парсим актуальную цену из HTML
        current_price = parse_html_price(prod['id'])

        # Если не получили цену из HTML, используем salePriceU как fallback
        if current_price is None:
            current_price = prod.get("salePriceU", 0) // 100
            print("⚠️ Используем цену из API (HTML недоступен)")

        return {
            "id": str(prod["id"]),
            "name": prod.get("name", "Без названия"),
            "brand": prod.get("brand", "Без бренда"),
            "price": current_price,  # Актуальная цена из HTML
            "old_price": prod.get("priceU", 0) // 100,  # "Старая" цена (может быть некорректной)
            "rating": prod.get("reviewRating", 0),
            "feedbacks": prod.get("feedbacks", 0),
            "image": f"https://images.wbstatic.net/big/new/{prod['id']}-1.jpg",
            "url": f"https://www.wildberries.ru/catalog/{prod['id']}/detail.aspx"
        }
    except Exception as e:
        print(f"[API Error] {e}")
        return None


# ===== КОМАНДЫ =====
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "👋 Добро пожаловать в PriceTrackerBot!\n"
        "Я помогу отслеживать изменения цен на Wildberries.",
        reply_markup=get_main_menu()
    )


@dp.message(F.text == "➕ Добавить товар")
async def add_product_start(message: types.Message):
    await message.answer(
        "Отправьте мне:\n"
        "• ID товара (например: 12345678)\n"
        "• Или ссылку на товар с Wildberries",
        reply_markup=get_cancel_button()
    )


@dp.message(F.text == "📋 Мои товары")
async def show_products(message: types.Message):
    user_id = message.from_user.id
    products = conn.execute(
        "SELECT product_id, name, last_price FROM products WHERE user_id=?",
        (user_id,)
    ).fetchall()

    if not products:
        await message.answer("У вас нет отслеживаемых товаров.", reply_markup=get_main_menu())
        return

    text = "📋 Ваши товары:\n\n"
    for idx, (pid, name, price) in enumerate(products, 1):
        text += f"{idx}. {name}\nID: {pid} - {price} ₽\n\n"

    await message.answer(text, reply_markup=get_main_menu())


@dp.message(F.text == "❌ Удалить товар")
async def delete_product_start(message: types.Message):
    user_id = message.from_user.id
    products = conn.execute(
        "SELECT product_id, name FROM products WHERE user_id=?",
        (user_id,)
    ).fetchall()

    if not products:
        await message.answer("Нет товаров для удаления.", reply_markup=get_main_menu())
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for pid, name in products:
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(text=f"❌ {name[:20]}...", callback_data=f"delete:{pid}")]
        )

    await message.answer("Выберите товар для удаления:", reply_markup=keyboard)


@dp.message(F.text == "❌ Отмена")
async def cancel_action(message: types.Message):
    await message.answer("Действие отменено.", reply_markup=get_main_menu())


# ===== ОБРАБОТКА ТОВАРОВ =====
@dp.message(F.text)
async def handle_product_input(message: types.Message):
    product_id = extract_product_id(message.text)
    if not product_id:
        await message.answer("Неверный формат. Отправьте ID или ссылку на товар.")
        return

    data = get_product_data(product_id)
    if not data:
        await message.answer("Не удалось получить информацию о товаре.", reply_markup=get_main_menu())
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Добавить к отслеживанию", callback_data=f"track:{product_id}")]
    ])

    caption = (
        f"🛍 <b>{data['name']}</b>\n"
        f"🏷 Бренд: {data['brand']}\n"
        f"💸 Цена: <b>{data['price']} ₽</b>\n"
        f"🔻 Старая цена: {data['old_price']} ₽\n"
        f"⭐️ Рейтинг: {data['rating']} (отзывов: {data['feedbacks']})"
    )

    try:
        await message.answer_photo(photo=data['image'], caption=caption, reply_markup=keyboard)
    except:
        await message.answer(caption, reply_markup=keyboard)


# ===== CALLBACK ОБРАБОТЧИКИ =====
@dp.callback_query(F.data.startswith("track:"))
async def track_product(callback: types.CallbackQuery):
    product_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    data = get_product_data(product_id)

    if not data:
        await callback.message.answer("Ошибка: товар не найден.")
        return

    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO products VALUES (?, ?, ?, ?, ?, ?)",
            (user_id, product_id, data['name'], data['brand'], data['url'], data['price'])
        )

    await callback.message.answer(
        f"✅ Товар {data['name']} добавлен к отслеживанию!",
        reply_markup=get_main_menu()
    )


@dp.callback_query(F.data.startswith("delete:"))
async def delete_product(callback: types.CallbackQuery):
    product_id = callback.data.split(":")[1]
    user_id = callback.from_user.id

    with conn:
        conn.execute(
            "DELETE FROM products WHERE user_id=? AND product_id=?",
            (user_id, product_id)
        )

    await callback.message.answer(
        "Товар удален из отслеживания.",
        reply_markup=get_main_menu()
    )


# ===== ФОНОВАЯ ПРОВЕРКА ЦЕН =====
async def check_price_changes():
    while True:
        await asyncio.sleep(CHECK_INTERVAL)
        logger.info("🔍 Проверяю изменения цен...")

        products = conn.execute(
            "SELECT user_id, product_id, name, last_price, url FROM products"
        ).fetchall()

        for user_id, pid, name, old_price, url in products:
            data = get_product_data(pid)
            if not data or 'price' not in data:
                continue

            new_price = data['price']
            if new_price < old_price:
                diff = old_price - new_price
                percent = round((diff / old_price) * 100, 2)

                text = (
                    f"📉 <b>Цена снизилась!</b>\n\n"
                    f"🛍 <a href='{url}'>{name}</a>\n"
                    f"💰 Было: <s>{old_price} ₽</s> → Стало: <b>{new_price} ₽</b>\n"
                    f"🔻 Снижение: {diff} ₽ ({percent}%)\n\n"
                    f"<i>ID товара: {pid}</i>"
                )

                try:
                    await bot.send_message(user_id, text)
                    with conn:
                        conn.execute(
                            "UPDATE products SET last_price=? WHERE user_id=? AND product_id=?",
                            (new_price, user_id, pid)
                        )
                except Exception as e:
                    logger.error(f"Ошибка отправки уведомления: {e}")


# ===== ЗАПУСК =====
async def main():
    asyncio.create_task(check_price_changes())
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())