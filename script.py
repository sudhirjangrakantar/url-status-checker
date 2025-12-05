#!/usr/bin/env python3
import os
import time
import requests
import pandas as pd
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta
from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.common.exceptions import WebDriverException, TimeoutException
from selenium.webdriver.support.ui import WebDriverWait

# ================= CONFIGURATION ==================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# INPUT
INPUT_FILE = os.path.join(BASE_DIR, "links.xlsx")
SHEET_NAME = "Links"
COLUMN_NAME = "URL"

# --- DYNAMIC OUTPUT FILENAME ---
IST = timezone(timedelta(hours=5, minutes=30))
current_time_str = datetime.now(IST).strftime("%Y-%m-%d_%H-%M")
OUTPUT_FILE = os.path.join(BASE_DIR, f"Result_{current_time_str}.xlsx")
# ------------------------------------

HTTP_TIMEOUT = 10         # slightly higher to tolerate remote delays
SELENIUM_TIMEOUT = 30
# Use env var HEADLESS="true" or "false" to override (good for GitHub Actions)
HEADLESS = os.getenv("HEADLESS", "true").lower() in ("1", "true", "yes")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:130.0) Gecko/20100101 Firefox/130.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.google.com/",
    "Connection": "keep-alive"
}

CF_SIGNS = [
    "checking your browser", "please stand by", "verify you are human",
    "security check", "attention required", "cf-browser-verification", "cloudflare"
]

BAD_TITLES = [
    "404 Not Found", "Access to the website is blocked"
]
# ==================================================

def load_urls():
    if not os.path.exists(INPUT_FILE):
        print(f"CRITICAL ERROR: Input file not found at: {INPUT_FILE}")
        return []
    try:
        df = pd.read_excel(INPUT_FILE, sheet_name=SHEET_NAME, engine='openpyxl')
        return df[COLUMN_NAME].dropna().astype(str).tolist()
    except Exception as e:
        print(f"Error reading Excel file: {e}")
        return []

def http_check(url):
    try:
        r = requests.get(url, headers=HEADERS, timeout=HTTP_TIMEOUT, allow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")
        title = soup.title.text.strip() if soup.title else ""
        return r.status_code, title
    except Exception as e:
        # debug output
        print(f"  - HTTP request failed: {e}")
        return None, ""

def need_selenium(status, title):
    if status is None or status >= 400: 
        return True
    if not title:
        return True
    if any(x in title.lower() for x in CF_SIGNS):
        return True
    return False

def setup_driver():
    opts = Options()
    if HEADLESS:
        opts.add_argument("--headless")

    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--window-size=1920,1080")

    opts.set_preference("dom.webdriver.enabled", False)
    opts.set_preference("useAutomationExtension", False)

    # IMPORTANT: For GitHub Actions
    opts.binary_location = "/usr/bin/firefox-esr"

    driver = webdriver.Firefox(options=opts)
    driver.set_page_load_timeout(SELENIUM_TIMEOUT)
    driver.implicitly_wait(3)
    return driver


def selenium_check(driver, url):
    try:
        driver.get(url)
        # short pause to let JS start executing (helps headless)
        time.sleep(1.5)
    except WebDriverException as e:
        return "Inactive", f"Selenium error: {str(e)[:200]}"

    # Wait only until title is available (same behavior as your original script)
    try:
        WebDriverWait(driver, 10).until(lambda d: d.title and d.title.strip())
    except TimeoutException:
        # MATCHES ORIGINAL: return explicit No title found
        return "Active", "No title found"

    title = driver.title.strip() if driver.title else ""
    page = driver.page_source.lower() if driver.page_source else ""

    # Quick Cloudflare check
    if any(x in page for x in CF_SIGNS) and not title:
        print("  - Security challenge immediately → skipping")
        return "Active", title or "Blocked by Cloudflare"

    return "Active", title

def is_bad_title(title: str) -> bool:
    if not title: 
        return False
    title_lower = title.lower()
    return any(bad.lower() in title_lower for bad in BAD_TITLES)

def save_results(results):
    if not results:
        print("No results to save.")
        return
    df = pd.DataFrame(results)
    df.to_excel(OUTPUT_FILE, index=False, engine='openpyxl')
    print(f"✓ Success! Saved to {OUTPUT_FILE}")

def main():
    print("--- Starting URL Checker ---")
    urls = load_urls()
    if not urls:
        print("No URLs loaded. Exiting.")
        return

    driver = setup_driver()
    results = []
    total = len(urls)

    for i, url in enumerate(urls, start=1):
        print(f"[{i}/{total}] Checking: {url}")
        start_time = time.time()
        IST = timezone(timedelta(hours=5, minutes=30))
        timestamp = datetime.now(IST).isoformat(timespec="seconds")

        http_code, title = http_check(url)

        if need_selenium(http_code, title):
            status, title = selenium_check(driver, url)
        else:
            status = "Active"

        if is_bad_title(title):
            print(f"  ! Detected Blocked Title: '{title}' -> Marking Inactive")
            status = "Inactive"

        duration = round(time.time() - start_time, 2)

        print(f"  → {status} | HTTP: {http_code} | Title: {title[:80]} | Time: {duration}s")
        
        results.append({
            "URL": url,
            "STATUS": status,
            "HTTP_CODE": http_code,
            "TITLE": title,
            "CHECKED_AT_IST": timestamp,
            "TIME_SEC": duration
        })

    save_results(results)
    driver.quit()
    print("--- Done ---")

if __name__ == "__main__":
    main()
