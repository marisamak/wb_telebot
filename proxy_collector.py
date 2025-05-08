import requests
from bs4 import BeautifulSoup
import time


def get_working_proxies(limit=5):
    print("⚠️ Прокси отключены — используется прямое соединение.")
    return []  # Возвращаем пустой список
