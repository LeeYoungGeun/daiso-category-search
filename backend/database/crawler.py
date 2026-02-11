"""
Daiso Mall Product Crawler
Crawls products from daisomall.co.kr ranking page
"""
import os
import sys
import time
import random
import requests
import ctypes
from urllib.parse import urljoin

from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager

from database import init_database, insert_product, get_product_count, product_exists

TARGET_URL = "https://www.daisomall.co.kr/ds/rank/C105"
TARGET_COUNT = 504
IMAGES_DIR = os.path.join(os.path.dirname(__file__), 'images')

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/119.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
]

def prevent_sleep():
    if sys.platform == 'win32':
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000002)
        print("💡 Sleep prevention enabled")

def allow_sleep():
    if sys.platform == 'win32':
        ctypes.windll.kernel32.SetThreadExecutionState(0x80000000)

def random_delay(min_sec=2, max_sec=5):
    time.sleep(random.uniform(min_sec, max_sec))

def create_driver():
    options = Options()
    options.add_argument('--headless=new')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--window-size=1920,1080')
    options.add_argument(f'--user-agent={random.choice(USER_AGENTS)}')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_experimental_option('excludeSwitches', ['enable-automation'])
    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
    return driver

def download_image(url: str, filename: str) -> str:
    os.makedirs(IMAGES_DIR, exist_ok=True)
    filepath = os.path.join(IMAGES_DIR, filename)
    if os.path.exists(filepath):
        return filepath
    try:
        response = requests.get(url, headers={'User-Agent': random.choice(USER_AGENTS)}, timeout=30)
        if response.status_code == 200:
            with open(filepath, 'wb') as f:
                f.write(response.content)
            return filepath
    except Exception as e:
        print(f"⚠️ Image download failed: {e}")
    return None

def scroll_slowly(driver, scroll_amount=500):
    current = driver.execute_script("return window.pageYOffset;")
    target = current + scroll_amount
    for i in range(10):
        driver.execute_script(f"window.scrollTo(0, {current + (target - current) * (i + 1) / 10});")
        time.sleep(random.uniform(0.05, 0.15))

def crawl_products():
    print("=" * 50)
    print("🚀 Daiso Mall Crawler")
    print(f"🎯 Target: {TARGET_COUNT} products")
    print("=" * 50)
    
    init_database()
    os.makedirs(IMAGES_DIR, exist_ok=True)
    prevent_sleep()
    
    attempt = 0
    while get_product_count() < TARGET_COUNT:
        attempt += 1
        print(f"\n📍 Attempt #{attempt} | Current: {get_product_count()}/{TARGET_COUNT}")
        
        driver = None
        try:
            driver = create_driver()
            driver.get(TARGET_URL)
            random_delay(3, 5)
            
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".card__inner"))
            )
            
            # Scroll to load all
            last_count = 0
            scroll_attempts = 0
            while scroll_attempts < 50:
                scroll_slowly(driver, random.randint(400, 800))
                random_delay(1, 2)
                items = driver.find_elements(By.CSS_SELECTOR, ".card__inner")
                if len(items) >= TARGET_COUNT or (len(items) == last_count and scroll_attempts > 10):
                    break
                scroll_attempts = 0 if len(items) != last_count else scroll_attempts + 1
                last_count = len(items)
            
            # Extract via JavaScript
            products_data = driver.execute_script("""
                const products = [];
                document.querySelectorAll('.card__inner').forEach((card, index) => {
                    let container = card.parentElement;
                    while (container && !container.querySelector('.rank')) container = container.parentElement;
                    const rank = container?.querySelector('.rank .num')?.innerText || (index + 1).toString();
                    const name = card.querySelector('.product-title')?.innerText.trim() || '';
                    const priceEl = Array.from(card.querySelectorAll('.detail-link div')).find(el => el.innerText.includes('원'));
                    const price = priceEl?.innerText.trim().replace(/\\n/g, '') || '';
                    const image = card.querySelector('img')?.src || '';
                    if (name) products.push({rank, name, price, image});
                });
                return products;
            """)
            
            for p in products_data:
                name = p.get('name', '').strip()
                if not name or product_exists(name):
                    continue
                rank = int(p.get('rank', 0)) if p.get('rank', '').isdigit() else 0
                price = int(''.join(filter(str.isdigit, p.get('price', '').replace(',', ''))) or 0)
                image_url = p.get('image', '')
                safe_name = "".join(c for c in name[:20] if c.isalnum() or c in ' _-').strip()
                image_name = f"{rank:03d}_{safe_name}.jpg"
                image_path = download_image(image_url, image_name) if image_url else None
                if insert_product(rank, name, price, image_url, image_name, image_path):
                    print(f"   ✅ [{rank}] {name[:35]}...")
                    
        except Exception as e:
            print(f"❌ Error: {e}")
            random_delay(10, 30)
        finally:
            if driver:
                driver.quit()
        
        if get_product_count() < TARGET_COUNT:
            time.sleep(random.randint(30, 60))
    
    allow_sleep()
    print(f"\n🎉 COMPLETE! {get_product_count()} products")

if __name__ == "__main__":
    try:
        crawl_products()
    except KeyboardInterrupt:
        allow_sleep()
