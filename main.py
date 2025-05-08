from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.client.default import DefaultBotProperties
import asyncio
import requests
import logging

# Настройка логгирования
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

API_TOKEN = "8092555394:AAHwvVmGcJYGw3Gu_LZe4aJ0U3K1v2aHqUw"

bot = Bot(
    token=API_TOKEN,
    default=DefaultBotProperties(parse_mode="HTML")
)
dp = Dispatcher()


async def download_image(url):
    try:
        response = requests.get(url, stream=True, timeout=10)
        if response.status_code == 200:
            return response.content
        return None
    except Exception as e:
        logger.error(f"Error downloading image: {e}")
        return None


def get_product_data(product_id):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
        'Accept': 'application/json',
    }

    try:
        # 1. Получаем данные о товаре
        product_url = f"https://card.wb.ru/cards/detail?appType=1&curr=rub&dest=-1257786&nm={product_id}"
        response = requests.get(product_url, headers=headers, timeout=10)

        if response.status_code != 200:
            logger.error(f"Ошибка запроса товара: {response.status_code}")
            return None

        data = response.json()

        # Добавляем проверку структуры ответа
        if not data or not isinstance(data.get('data'), dict):
            logger.error("Неверный формат ответа API")
            return None

        products = data.get("data", {}).get("products", [])
        if not products:
            logger.error("Товар не найден в ответе API")
            return None

        prod = products[0]

        # Добавляем проверку наличия обязательных полей
        if not all(key in prod for key in ['id', 'name', 'brand', 'salePriceU', 'priceU']):
            logger.error("Не хватает обязательных полей в данных товара")
            return None

        # Безопасное получение данных
        product_id = str(prod.get('id'))  # Преобразуем ID в строку
        name = prod.get('name', 'Название не указано')
        brand = prod.get('brand', 'Бренд не указан')

        # Формируем URL изображения
        image_url = f"https://images.wbstatic.net/big/new/{product_id}-1.jpg" if product_id else None

        return {
            "id": product_id,
            "name": name,
            "brand": brand,
            "price": prod.get("salePriceU", 0) // 100,
            "old_price": prod.get("priceU", 0) // 100,
            "rating": prod.get("reviewRating", 0),
            "feedbacks": prod.get("feedbacks", 0),
            "image": image_url,
        }

    except Exception as e:
        logger.error(f"Ошибка получения данных: {str(e)}")
        return None
    

    except Exception as e:
        logger.error(f"Ошибка получения данных: {str(e)}")
        return None

@dp.message(Command("start"))
async def start_handler(message: types.Message):
    await message.answer(
        "Привет! Я бот для отслеживания товаров с Wildberries.\n"
        "Отправь мне команду /track и ID товара, например:\n"
        "/track 12345678"
    )


@dp.message(Command("track"))
async def track_handler(message: types.Message):
    args = message.text.split()[1] if len(message.text.split()) > 1 else None
    if not args or not args.isdigit():
        await message.reply("❗ Пожалуйста, укажи ID товара: `/track 210959469`", parse_mode="Markdown")
        return

    product_id = args
    await message.reply("🔍 Ищу товар...")

    data = get_product_data(product_id)
    if not data:
        await message.reply("🚫 Не удалось найти товар.")
        return

    caption = (
        f"🛍 <b>{data['name']}</b>\n"
        f"🏷 Бренд: {data['brand']}\n"
        f"💸 Цена: <b>{data['price']} ₽</b>\n"
        f"🔻 Старая цена: {data['old_price']} ₽\n"
        f"⭐️ Рейтинг: {data['rating']} (отзывов: {data['feedbacks']})"
    )

    try:
        if data["image"]:
            # Сначала загружаем изображение локально
            image_data = await download_image(data["image"])
            if image_data:
                await bot.send_photo(
                    chat_id=message.chat.id,
                    photo=types.BufferedInputFile(image_data, filename="product.jpg"),
                    caption=caption
                )
            else:
                await message.answer(caption)
        else:
            await message.answer(caption)
    except Exception as e:
        logger.error(f"Error sending photo: {e}")
        await message.answer(caption)


async def main():
    logger.info("Бот запущен!")
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())