"""
Scraper flow:
  1. Open FastMoss — you log in manually, then press Enter
  2. Scrape brand names + categories from pages 1 & 2
  3. For every brand → find Facebook page → scrape phone + email
  4. For every brand → find Instagram profile → scrape phone + email
  5. Save to brands.csv with columns:
     brand_name, category, fb_phone, fb_email, ig_phone, ig_email
"""

import csv
import json
import logging
import random
import re
import time
import urllib.parse

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Credentials
# ---------------------------------------------------------------------------

IG_USERNAME = "ther.ezzas"
IG_PASSWORD = "Gilang21."

FB_EMAIL    = "081806482566"
FB_PASSWORD = "Gilang21."

# ---------------------------------------------------------------------------
# Output
# ---------------------------------------------------------------------------

OUTPUT_FILE = "brands.csv"
FIELDNAMES  = ["brand_name", "category", "fb_phone", "fb_email", "ig_phone", "ig_email"]
MAX_PAGES   = 2

# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def clean_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    elif digits.startswith("8") and len(digits) >= 9:
        digits = "62" + digits
    return digits

def extract_wa_number(text: str) -> str:
    for pattern in [
        r"wa\.me/(\d{8,15})",
        r"api\.whatsapp\.com/send\?phone=(\d{8,15})",
        r"whatsapp\.com/send/?\?phone=(\d{8,15})",
    ]:
        m = re.search(pattern, text)
        if m:
            return m.group(1)
    return ""

def extract_email(text: str) -> str:
    for m in re.finditer(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,6}", text):
        email = m.group(0).lower()
        if any(x in email for x in ["sentry", "@example", "noreply", "no-reply", "wix", "squarespace"]):
            continue
        return m.group(0)
    return ""

def extract_phone(text: str) -> str:
    for pattern in [
        r"\+62[\s\-]?8[\d\s\-]{8,12}",
        r"\+62[\s\-]?\d[\d\s\-]{7,12}",
        r"62[\s]?8\d{8,11}",
        r"08[\d\s\-]{8,12}",
    ]:
        m = re.search(pattern, text)
        if m:
            cleaned = clean_phone(m.group(0))
            if 10 <= len(cleaned) <= 15:
                return cleaned
    return ""

def search_first_url(page, query: str, domain: str) -> str:
    """Search DuckDuckGo then Bing, return first result URL containing domain."""
    engines = [
        ("duckduckgo", f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&ia=web"),
        ("bing",       f"https://www.bing.com/search?q={urllib.parse.quote(query)}"),
    ]
    for engine_name, url in engines:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(random.uniform(1500, 2500))
            for link in page.query_selector_all("a[href]"):
                href = link.get_attribute("href") or ""
                if domain in href.lower() and engine_name not in href.lower():
                    # Unwrap DuckDuckGo redirect
                    if "duckduckgo.com/l/" in href:
                        m = re.search(r"uddg=([^&]+)", href)
                        if m:
                            href = urllib.parse.unquote(m.group(1))
                    if domain in href.lower():
                        return href
        except Exception as e:
            log.warning(f"  [{engine_name}] search error: {e}")
    return ""


# ---------------------------------------------------------------------------
# Login helpers
# ---------------------------------------------------------------------------

def _ig_click_login_btn(page):
    for sel in [
        "div[role='button'][aria-label='Log In']",
        "div[role='button'][aria-label='Masuk']",
        "button[type='submit']",
    ]:
        try:
            btn = page.wait_for_selector(sel, timeout=3000)
            if btn:
                btn.click()
                log.info(f"  Clicked IG login button ({sel})")
                return True
        except Exception:
            pass
    return False


def login_instagram(page):
    """Login to Instagram. Call after navigating to the login page."""
    try:
        page.wait_for_selector("input[name='username']", timeout=8000)
        page.fill("input[name='username']", IG_USERNAME)
        page.wait_for_selector("input[name='password']", timeout=5000)
        page.fill("input[name='password']", IG_PASSWORD)
        page.wait_for_timeout(500)
        if not _ig_click_login_btn(page):
            log.warning("  Could not find IG login button")
            return
        page.wait_for_timeout(5000)
        # Dismiss prompts
        for prompt in ["button:has-text('Not Now')", "button:has-text('Nanti Saja')"]:
            try:
                page.click(prompt, timeout=3000)
                page.wait_for_timeout(800)
            except Exception:
                pass
        log.info("  Instagram login done")
    except Exception as e:
        log.warning(f"  Instagram login failed: {e}")


def login_facebook(page):
    """Login to Facebook. Call after navigating to the login page."""
    try:
        page.wait_for_selector("input#email", timeout=8000)
        page.fill("input#email", FB_EMAIL)
        page.wait_for_selector("input#pass", timeout=5000)
        page.fill("input#pass", FB_PASSWORD)
        page.wait_for_timeout(500)
        for sel in ["button[name='login']", "button[type='submit']", "input[type='submit']"]:
            try:
                btn = page.wait_for_selector(sel, timeout=3000)
                if btn:
                    btn.click()
                    log.info(f"  Clicked FB login button ({sel})")
                    break
            except Exception:
                pass
        page.wait_for_timeout(5000)
        for prompt in ["button:has-text('Not Now')", "button:has-text('Nanti')", "[aria-label='Close']"]:
            try:
                page.click(prompt, timeout=2000)
                page.wait_for_timeout(800)
            except Exception:
                pass
        log.info("  Facebook login done")
    except Exception as e:
        log.warning(f"  Facebook login failed: {e}")


# ---------------------------------------------------------------------------
# Phase 1 — Scrape brand list from FastMoss (pages 1 & 2)
# ---------------------------------------------------------------------------

def scrape_fastmoss(page) -> list[dict]:
    brands = []
    current_page = 1

    while current_page <= MAX_PAGES:
        log.info(f"  FastMoss page {current_page}...")
        try:
            page.wait_for_selector("tbody.ant-table-tbody tr.ant-table-row", timeout=15000)
        except Exception:
            log.warning("  Table not found, stopping.")
            break

        rows = page.query_selector_all("tbody.ant-table-tbody tr.ant-table-row")
        log.info(f"  Found {len(rows)} rows")

        for row in rows:
            name_el = row.query_selector("h3.content.truncate")
            brand_name = name_el.inner_text().strip() if name_el else ""

            cat_el = row.query_selector("div.custom-tag-container span.text-ellipsis")
            category = cat_el.inner_text().strip() if cat_el else ""

            if brand_name:
                brands.append({"brand_name": brand_name, "category": category})
                log.info(f"    {brand_name} | {category}")

        if current_page >= MAX_PAGES:
            break

        next_btn = page.query_selector("li.ant-pagination-next:not([aria-disabled='true']) button")
        if not next_btn:
            log.info("  No more pages.")
            break

        next_btn.click()
        try:
            page.wait_for_selector("tbody.ant-table-tbody tr.ant-table-row", timeout=15000)
        except Exception:
            log.warning("  Next page failed to load.")
            break

        current_page += 1

    log.info(f"  Total brands scraped: {len(brands)}")
    return brands


# ---------------------------------------------------------------------------
# Phase 2 — Facebook contact scraper
# ---------------------------------------------------------------------------

def scrape_facebook(page, brand_name: str) -> dict:
    result = {"fb_phone": "", "fb_email": ""}

    # Find the brand's Facebook page
    fb_url = search_first_url(page, f"{brand_name} site:facebook.com", "facebook.com")
    if not fb_url:
        fb_url = search_first_url(page, f"{brand_name} facebook indonesia", "facebook.com")
    if not fb_url:
        log.info(f"    [FB] No page found for: {brand_name}")
        return result

    fb_url = re.split(r"\?", fb_url)[0].rstrip("/")

    # Skip non-brand URLs
    if any(x in fb_url for x in ["/groups/", "/video", "/posts/", "/photos/", "/people/", "/events/"]):
        log.info(f"    [FB] Skipping non-page URL: {fb_url}")
        return result

    log.info(f"    [FB] {fb_url}")

    try:
        page.goto(fb_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(random.uniform(2500, 4000))
    except Exception as e:
        log.warning(f"    [FB] Failed to load: {e}")
        return result

    # Login wall check
    if "login" in page.url or "checkpoint" in page.url:
        log.warning("    [FB] Login wall — re-logging in")
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(1500)
        login_facebook(page)
        try:
            page.goto(fb_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
        except Exception:
            return result

    # Visit /about tab for contact details
    try:
        page.goto(fb_url.rstrip("/") + "/about", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2500)
    except Exception:
        pass

    # mailto: links
    for link in page.query_selector_all("a[href^='mailto:']"):
        em = (link.get_attribute("href") or "").replace("mailto:", "").split("?")[0].strip()
        if em and not result["fb_email"]:
            result["fb_email"] = em

    # tel: links
    for link in page.query_selector_all("a[href^='tel:']"):
        ph = (link.get_attribute("href") or "").replace("tel:", "").strip()
        if ph and not result["fb_phone"]:
            result["fb_phone"] = clean_phone(ph)

    # wa.me links → use as phone if no phone yet
    for link in page.query_selector_all("a[href*='wa.me'], a[href*='whatsapp']"):
        href = link.get_attribute("href") or ""
        wa = extract_wa_number(href)
        if wa and not result["fb_phone"]:
            result["fb_phone"] = wa

    # Regex fallback on full page text
    full_text = page.inner_text("body")
    if not result["fb_email"]:
        result["fb_email"] = extract_email(full_text)
    if not result["fb_phone"]:
        wa = extract_wa_number(full_text)
        result["fb_phone"] = wa or extract_phone(full_text)

    log.info(f"    [FB] phone={result['fb_phone'] or '-'}  email={result['fb_email'] or '-'}")
    return result


# ---------------------------------------------------------------------------
# Phase 3 — Instagram contact scraper
# ---------------------------------------------------------------------------

def scrape_instagram(page, brand_name: str) -> dict:
    result = {"ig_phone": "", "ig_email": ""}

    # Find the brand's Instagram profile
    ig_url = search_first_url(page, f"{brand_name} site:instagram.com", "instagram.com")
    if not ig_url:
        ig_url = search_first_url(page, f"{brand_name} instagram indonesia", "instagram.com")
    if not ig_url:
        log.info(f"    [IG] No profile found for: {brand_name}")
        return result

    ig_url = re.split(r"\?", ig_url)[0].rstrip("/")
    log.info(f"    [IG] {ig_url}")

    try:
        page.goto(ig_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(random.uniform(3000, 4500))
        page.evaluate("window.scrollBy(0, 300)")
        page.wait_for_timeout(1000)
    except Exception as e:
        log.warning(f"    [IG] Failed to load profile: {e}")
        return result

    # Login wall check
    if "accounts/login" in page.url or "challenge" in page.url:
        log.warning("    [IG] Login wall — re-logging in")
        try:
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=10000)
            login_instagram(page)
            page.goto(ig_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
        except Exception as e:
            log.error(f"    [IG] Re-login failed: {e}")
            return result

    if "Page Not Found" in (page.title() or "") or "/404" in page.url:
        log.warning("    [IG] Profile not found")
        return result

    # Click Contact / Kontak button to open modal
    for selector in [
        "a[role='link']:has-text('Contact')", "a[role='link']:has-text('Kontak')",
        "button:has-text('Contact')", "button:has-text('Kontak')",
    ]:
        try:
            btn = page.query_selector(selector)
            if btn:
                btn.click()
                page.wait_for_timeout(2000)
                break
        except Exception:
            pass

    # mailto: and tel: links (appear after modal opens)
    for link in page.query_selector_all("a[href^='mailto:']"):
        em = (link.get_attribute("href") or "").replace("mailto:", "").split("?")[0].strip()
        if em and not result["ig_email"]:
            result["ig_email"] = em

    for link in page.query_selector_all("a[href^='tel:']"):
        ph = (link.get_attribute("href") or "").replace("tel:", "").strip()
        if ph and not result["ig_phone"]:
            result["ig_phone"] = clean_phone(ph)

    # wa.me links
    for link in page.query_selector_all("a[href*='wa.me'], a[href*='whatsapp']"):
        href = link.get_attribute("href") or ""
        wa = extract_wa_number(href)
        if wa and not result["ig_phone"]:
            result["ig_phone"] = wa

    # Regex fallback on full page text
    full_text = page.inner_text("body")
    if not result["ig_email"]:
        result["ig_email"] = extract_email(full_text)
    if not result["ig_phone"]:
        wa = extract_wa_number(full_text)
        result["ig_phone"] = wa or extract_phone(full_text)

    log.info(f"    [IG] phone={result['ig_phone'] or '-'}  email={result['ig_email'] or '-'}")
    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            )
        )

        # ── Step 1: FastMoss — manual login ──────────────────────────────
        fastmoss_page = context.new_page()
        log.info("Opening FastMoss — please log in manually...")
        fastmoss_page.goto("https://www.fastmoss.com/id/shop-marketing/search?region=ID")
        input("\n>>> Log in to FastMoss in the browser, then press Enter here to start scraping...\n")

        log.info("=== Phase 1: Scraping brand list from FastMoss ===")
        brands = scrape_fastmoss(fastmoss_page)
        fastmoss_page.close()

        if not brands:
            log.error("No brands found. Exiting.")
            browser.close()
            return

        log.info(f"Got {len(brands)} brands. Starting contact scraping...")

        # ── Step 2: Facebook — login once, scrape all brands ─────────────
        log.info("\n=== Phase 2: Facebook contact scraping ===")
        fb_page = context.new_page()
        fb_page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=15000)
        fb_page.wait_for_timeout(1500)
        login_facebook(fb_page)

        fb_results = {}
        for i, brand in enumerate(brands):
            name = brand["brand_name"]
            log.info(f"  [{i+1}/{len(brands)}] {name}")
            fb_results[name] = scrape_facebook(fb_page, name)
            time.sleep(random.uniform(2.5, 4.5))

        fb_page.close()

        # ── Step 3: Instagram — login once, scrape all brands ────────────
        log.info("\n=== Phase 3: Instagram contact scraping ===")
        ig_page = context.new_page()
        ig_page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=15000)
        login_instagram(ig_page)

        ig_results = {}
        for i, brand in enumerate(brands):
            name = brand["brand_name"]
            log.info(f"  [{i+1}/{len(brands)}] {name}")
            ig_results[name] = scrape_instagram(ig_page, name)
            time.sleep(random.uniform(2.5, 4.5))

        ig_page.close()
        browser.close()

        # ── Step 4: Write CSV ─────────────────────────────────────────────
        with open(OUTPUT_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
            writer.writeheader()
            for brand in brands:
                name = brand["brand_name"]
                fb = fb_results.get(name, {})
                ig = ig_results.get(name, {})
                writer.writerow({
                    "brand_name": name,
                    "category":   brand["category"],
                    "fb_phone":   fb.get("fb_phone", ""),
                    "fb_email":   fb.get("fb_email", ""),
                    "ig_phone":   ig.get("ig_phone", ""),
                    "ig_email":   ig.get("ig_email", ""),
                })

        log.info(f"\nDone. {len(brands)} brands saved to {OUTPUT_FILE}")


if __name__ == "__main__":
    main()
