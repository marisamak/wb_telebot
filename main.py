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
from bs4 import BeautifulSoup

# Настройки
API_TOKEN = "8092555394:AAHwvVmGcJYGw3Gu_LZe4aJ0U3K1v2aHqUw"
CHECK_INTERVAL = 1800  # Проверка каждые 30 минут
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
    current_price INTEGER,
    last_check TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (user_id, product_id)
)
""")

conn.commit()


# КЛАВИАТУРЫ
def get_main_menu():
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="➕ Добавить товар")],
            [KeyboardButton(text="📋 Мои товары"), KeyboardButton(text="❌ Удалить товар")],
        ],
        resize_keyboard=True,
        input_field_placeholder="Выберите действие"
    )


def get_cancel_button():
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="❌ Отмена")]],
        resize_keyboard=True
    )


def get_track_keyboard(product_id):
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📌 Отслеживать этот товар", callback_data=f"track:{product_id}")]
    ])


# ОБРАБОТКА ТОВАРОВ
def extract_product_id(text):
    # Из ссылки: https://www.wildberries.ru/catalog/12345678/detail.aspx
    if "wildberries.ru" in text:
        match = re.search(r"catalog/(\d+)", text) # выражение для поиска в строке подстроки вида "catalog/число"
        if match:
            return match.group(1) # возвращает первую группу из совпадения (id товара)

    # Из ID: 12345678
    if text.isdigit() and len(text) >= 6: # проверяет, состоит ли строка только из цифр (isdigit()) и имеет ли она длину 6 или более символов, чтобы определить, является ли text ID товара
        return text

    return None


def get_product_data(product_id):
    def parse_html_price(prod_id):
        try:
            url = f"https://www.wildberries.ru/catalog/{prod_id}/detail.aspx" # Формирует URL страницы товара, подставляя
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept-Language': 'ru-RU,ru;q=0.9' # Задаёт HTTP-заголовки для имитации запроса от браузера
            }
            response = requests.get(url, headers=headers, timeout=10) # Выполняет GET-запрос к URL

            if response.status_code == 200:
                soup = BeautifulSoup(response.text, 'html.parser') # Создаёт объект BeautifulSoup для парсинга HTML-кода страницы
                price_tag = soup.find('h2', class_='price-history__title')
                if price_tag:
                    price_text = price_tag.get_text(strip=True) # Извлекает текст из тега, удаляя лишние пробелы
                    return int(''.join(filter(str.isdigit, price_text.replace('&nbsp;', ''))))
        except Exception as e: # Ловит любые ошибки
            logger.error(f"HTML price error: {e}")
        return None

    try:
        # 1. Получаем базовые данные из API
        api_url = f"https://card.wb.ru/cards/detail?appType=1&curr=rub&dest=-1257786&nm={product_id}"
        api_response = requests.get(api_url, timeout=10)

        if api_response.status_code != 200:
            return None

        data = api_response.json() # Преобразует ответ API в JSON-объект
        products = data.get("data", {}).get("products", []) # Извлекает список товаров из JSON
        if not products:
            return None

        prod = products[0]

        # 2. Парсим актуальную цену из HTML
        current_price = parse_html_price(prod['id'])
        if current_price is None:
            current_price = prod.get("salePriceU", 0) // 100
            logger.warning("Используем цену из API (HTML недоступен)")

        return {
            "id": str(prod["id"]),
            "name": prod.get("name", "Без названия"),
            "brand": prod.get("brand", "Без бренда"),
            "price": current_price,
            "old_price": prod.get("priceU", 0) // 100,
            "rating": prod.get("reviewRating", 0),
            "feedbacks": prod.get("feedbacks", 0),
            "image": f"https://images.wbstatic.net/big/new/{prod['id']}-1.jpg",
            "url": f"https://www.wildberries.ru/catalog/{prod['id']}/detail.aspx"
        }
    except Exception as e: # Ловит любые ошибки
        logger.error(f"API error: {e}")
        return None


def get_current_price(product_id): # принимает product_id (ID товара, например, "12345678") и возвращает цену товара в рублях
    try:
        url = f"https://card.wb.ru/cards/detail?appType=1&curr=rub&dest=-1257786&nm={product_id}"
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept-Language': 'ru-RU'
        } # Задаёт HTTP-заголовки
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
        data = response.json() # Преобразует ответ API в JSON-объект
        products = data.get("data", {}).get("products", []) # Извлекает список товаров из JSON
        if not products:
            logger.warning(f"⚠️ API не вернул продукт {product_id}")
            return None
        product = products[0]
        return product.get("salePriceU", 0) // 100 # Извлекает текущую цену
    except Exception as e:
        logger.error(f"[get_current_price] Ошибка получения цены для {product_id}: {e}")
        return None


# КОМАНДЫ
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "Привет! Я помогу отслеживать цены на Wildberries.",
        reply_markup=get_main_menu()
    )


@dp.message(F.text == "➕ Добавить товар")
async def add_product_start(message: types.Message):
    await message.answer(
        "Отправьте мне ID товара или ссылку на Wildberries:",
        reply_markup=get_cancel_button()
    )


@dp.message(F.text == "📋 Мои товары")
async def show_products(message: types.Message):
    user_id = message.from_user.id
    products = conn.execute(
        "SELECT product_id, name, current_price FROM products WHERE user_id=?",
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
    ).fetchall() # Выполняет SQL-запрос к базе данных

    if not products:
        await message.answer("Нет товаров для удаления.", reply_markup=get_main_menu())
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[])
    for pid, name in products: # Перебирает список товаров
        keyboard.inline_keyboard.append(
            [InlineKeyboardButton(text=f"❌ {name[:20]}...", callback_data=f"delete:{pid}")]
        )

    await message.answer("Выберите товар для удаления:", reply_markup=keyboard)


@dp.message(F.text == "❌ Отмена")
async def cancel_action(message: types.Message):
    await message.answer("Действие отменено.", reply_markup=get_main_menu())


# ОБРАБОТКА ТОВАРОВ
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

    await message.answer(
        f"Найден товар с ID: {product_id}",
        reply_markup=get_track_keyboard(product_id)
    )

    caption = (
        f"🆔 {product_id}\n"
        f"<a href='{data['url']}'>{data['name']}</a>\n"
        f"🏷 {data['brand']}\n"
        f"💸 Цена: <b>{data['price']} ₽</b>\n"
        f"⭐️ {data['rating']} (отзывов: {data['feedbacks']})"
    )

    try:
        await message.answer_photo(
            photo=data['image'],
            caption=caption
        )
    except:
        await message.answer(caption) # Если отправка фото не удалась, отправляет только текстовое сообщение без изображения


# CALLBACK ОБРАБОТЧИКИ
@dp.callback_query(F.data.startswith("track:"))
async def track_product(callback: types.CallbackQuery):
    product_id = callback.data.split(":")[1]
    user_id = callback.from_user.id
    data = get_product_data(product_id)

    if not data:
        await callback.message.answer("Ошибка: товар не найден")
        return

    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO products "
            "(user_id, product_id, name, brand, url, current_price) "
            "VALUES (?, ?, ?, ?, ?, ?)",
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

    with conn: # Открывает транзакцию с базой данных
        conn.execute(
            "DELETE FROM products WHERE user_id=? AND product_id=?",
            (user_id, product_id)
        ) # Выполняет SQL-запрос для вставки или замены записи в таблице

    await callback.message.answer(
        "Товар удален из отслеживания",
        reply_markup=get_main_menu()
    )


# ФОНОВАЯ ПРОВЕРКА ЦЕН
async def check_price_changes():
    while True:
        await asyncio.sleep(CHECK_INTERVAL) # Приостанавливает выполнение на время
        logger.info("🔍 Проверяю изменения цен...")

        # 0.041666 ≈ 1 час в формате дней для SQLite
        products = conn.execute("""
            SELECT user_id, product_id, name, url, current_price 
            FROM products
            WHERE julianday('now') - julianday(last_check) > 0.020833
            LIMIT 50
        """).fetchall() # Выполняет SQL-запрос к базе данных

        for user_id, pid, name, url, old_price in products: # Перебирает список товаров, распаковывая данные
            try:
                # Получаем ТОЛЬКО текущую цену
                new_price = get_current_price(pid)

                if new_price is None:
                    continue

                if new_price != old_price:
                    # Формируем сообщение
                    diff = new_price - old_price
                    trend = "📈" if diff > 0 else "📉"

                    text = (
                        f"{trend} <b>Изменение цены!</b>\n\n"
                        f"🛍 <a href='{url}'>{name}</a>\n"
                        f"💰 Было: <s>{old_price} ₽</s> → Стало: <b>{new_price} ₽</b>\n"
                        f"Δ {abs(diff)} ₽ ({trend} {abs(round(diff / old_price * 100, 1))}%)\n"
                        f"🆔 <code>{pid}</code>"
                    )

                    await bot.send_message(user_id, text)

                    # Обновляем цену и время проверки
                    conn.execute("""
                        UPDATE products 
                        SET current_price = ?, last_check = datetime('now')
                        WHERE product_id = ? AND user_id = ?
                    """, (new_price, pid, user_id)) # Обновляет в базе данных

            except Exception as e:
                logger.error(f"Ошибка проверки цены {pid}: {e}")

# ЗАПУСК
async def main():
    asyncio.create_task(check_price_changes())
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
