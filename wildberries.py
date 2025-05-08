import requests
import time
import random

HEADERS = {"User-Agent": "Mozilla/5.0"}
PROXIES = []  # передаётся из main

def get_proxy():
    return {"http": random.choice(PROXIES), "https": random.choice(PROXIES)} if PROXIES else None

def fetch_product_data(product_id, retries=3):
    url = f"https://card.wb.ru/cards/detail?appType=1&curr=rub&dest=-1257786&spp=0&nm={product_id}"

    for i in range(retries):
        try:
            r = requests.get(url, headers=HEADERS, proxies=get_proxy(), timeout=5)
            if r.status_code == 200:
                json_data = r.json()
                products = json_data.get("data", {}).get("products", [])
                if not products:
                    raise ValueError("❌ Товар не найден")
                return parse_product(products[0])
        except Exception as e:
            print(f"⚠️ Ошибка: {e}. Повтор {i + 1}/{retries}")
            time.sleep(1)
    raise ConnectionError("Не удалось получить данные после повторов")

def parse_product(prod):
    product_id = prod["id"]
    image = f"https://images.wbstatic.net/big/new/{product_id}-1.jpg"

    return {
        "id": product_id,
        "name": prod.get("name"),
        "price": prod.get("salePriceU", 0) // 100,
        "old_price": prod.get("priceU", 0) // 100,
        "rating": prod.get("reviewRating"),
        "feedbacks": prod.get("feedbacks"),
        "brand": prod.get("brand"),
        "image": image
    }
