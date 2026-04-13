import argparse
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

FASTMOSS_EMAIL    = "creative.mcnasia@gmail.com"
FASTMOSS_PASSWORD = "Mcnasia2000"

IG_USERNAME = "ther.ezzas"
IG_PASSWORD = "Gilang21."

FB_EMAIL    = "081806482566"
FB_PASSWORD = "Gilang21."

# ---------------------------------------------------------------------------
# CSV columns
# ---------------------------------------------------------------------------

FIELDNAMES = ["brand_name", "category",
              "ig_phone", "ig_email",
              "fb_phone", "fb_email"]

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
        if any(x in email for x in ["sentry", "@example", "noreply", "no-reply"]):
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
    """Search DuckDuckGo then Bing, return first URL containing domain."""
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

def login_fastmoss(page):
    try:
        log.info("Logging in to FastMoss...")
        page.wait_for_timeout(1500)

        masuk_btn = page.query_selector("div.bg-vi:has-text('Masuk'), div.text-white:has-text('Masuk')")
        if masuk_btn:
            masuk_btn.click()
            log.info("Clicked Masuk button")
            page.wait_for_timeout(2000)
        else:
            log.warning("Could not find Masuk button")
            return

        page.wait_for_selector("input[type='email']", timeout=5000)
        page.fill("input[type='email']", FASTMOSS_EMAIL)
        log.info("Filled email")

        page.fill("input[type='password']", FASTMOSS_PASSWORD)
        log.info("Filled password")

        page.wait_for_timeout(500)

        for sel in ["button[type='submit']", "button:has-text('Login')", "button:has-text('Masuk')"]:
            try:
                btn = page.wait_for_selector(sel, timeout=3000)
                if btn:
                    btn.click()
                    log.info(f"Clicked submit ({sel})")
                    break
            except Exception:
                pass

        page.wait_for_timeout(4000)
        log.info("FastMoss login completed")
    except Exception as e:
        log.warning(f"FastMoss login failed: {e}")


def _ig_click_login_btn(page):
    """Click the Instagram login button (div[role='button'], not a real button)."""
    for sel in [
        "div[role='button'][aria-label='Log In']",
        "div[role='button'][aria-label='Masuk']",
        "button[type='submit']",
    ]:
        try:
            btn = page.wait_for_selector(sel, timeout=3000)
            if btn:
                btn.click()
                log.info(f"Clicked IG login button ({sel})")
                return True
        except Exception:
            pass
    return False


def login_instagram(page):
    try:
        log.info("Logging in to Instagram...")
        page.wait_for_load_state("domcontentloaded", timeout=10000)

        if "accounts/login" not in page.url and "challenge" not in page.url:
            log.info("Already logged in to Instagram")
            return

        page.wait_for_selector("input[name='username']", timeout=8000)
        page.fill("input[name='username']", IG_USERNAME)
        log.info("Filled IG username")

        page.wait_for_selector("input[name='password']", timeout=5000)
        page.fill("input[name='password']", IG_PASSWORD)
        log.info("Filled IG password")

        page.wait_for_timeout(500)

        if not _ig_click_login_btn(page):
            log.warning("Could not find IG login button")
            return

        page.wait_for_timeout(5000)

        for prompt in ["button:has-text('Not Now')", "button:has-text('Nanti Saja')"]:
            try:
                page.click(prompt, timeout=4000)
                page.wait_for_timeout(1000)
            except Exception:
                pass

        log.info("Instagram login completed")
    except Exception as e:
        log.warning(f"Instagram login failed: {e}")


def login_facebook(page):
    try:
        log.info("Logging in to Facebook...")
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        if "login" not in page.url and "checkpoint" not in page.url:
            log.info("Already logged in to Facebook")
            return

        page.wait_for_selector("input#email", timeout=8000)
        page.fill("input#email", FB_EMAIL)
        log.info("Filled FB email/phone")

        page.wait_for_selector("input#pass", timeout=5000)
        page.fill("input#pass", FB_PASSWORD)
        log.info("Filled FB password")

        page.wait_for_timeout(500)

        for sel in ["button[name='login']", "button[type='submit']", "input[type='submit']"]:
            try:
                btn = page.wait_for_selector(sel, timeout=3000)
                if btn:
                    btn.click()
                    log.info(f"Clicked FB login button ({sel})")
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

        log.info("Facebook login completed")
    except Exception as e:
        log.warning(f"Facebook login failed: {e}")


# ---------------------------------------------------------------------------
# Instagram scraper
# ---------------------------------------------------------------------------

def scrape_instagram(page, brand_name: str) -> dict:
    result = {"ig_phone": "", "ig_email": ""}

    ig_url = search_first_url(page, f"{brand_name} site:instagram.com", "instagram.com")
    if not ig_url:
        ig_url = search_first_url(page, f"{brand_name} instagram indonesia", "instagram.com")
    if not ig_url:
        log.info("    [IG] No profile found")
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

    # Login wall — re-login and retry
    if "accounts/login" in page.url or "challenge" in page.url:
        log.warning("    [IG] Login wall — re-logging in")
        try:
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=10000)
            page.wait_for_selector("input[name='username']", timeout=8000)
            page.fill("input[name='username']", IG_USERNAME)
            page.wait_for_selector("input[name='password']", timeout=5000)
            page.fill("input[name='password']", IG_PASSWORD)
            page.wait_for_timeout(500)
            _ig_click_login_btn(page)
            page.wait_for_timeout(4000)
            for prompt in ["button:has-text('Not Now')", "button:has-text('Nanti Saja')"]:
                try:
                    page.click(prompt, timeout=2000)
                except Exception:
                    pass
            page.goto(ig_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
        except Exception as e:
            log.error(f"    [IG] Re-login failed: {e}")
            return result

    if "Page Not Found" in (page.title() or "") or "/404" in page.url:
        log.warning("    [IG] Profile not found")
        return result

    # Click Contact button to open modal
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

    # mailto: and tel: links (most reliable after modal opens)
    for link in page.query_selector_all("a[href^='mailto:']"):
        em = (link.get_attribute("href") or "").replace("mailto:", "").strip()
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

    log.info(f"    [IG] phone={result['ig_phone'] or '-'} email={result['ig_email'] or '-'}")
    return result


# ---------------------------------------------------------------------------
# Facebook scraper
# ---------------------------------------------------------------------------

def scrape_facebook(page, brand_name: str) -> dict:
    result = {"fb_phone": "", "fb_email": ""}

    fb_url = search_first_url(page, f"{brand_name} site:facebook.com", "facebook.com")
    if not fb_url:
        fb_url = search_first_url(page, f"{brand_name} facebook indonesia", "facebook.com")
    if not fb_url:
        log.info("    [FB] No page found")
        return result

    fb_url = re.split(r"\?", fb_url)[0].rstrip("/")
    if any(x in fb_url for x in ["/groups/", "/video", "/posts/", "/photos/", "/people/"]):
        log.info(f"    [FB] Skipping non-page URL: {fb_url}")
        return result

    log.info(f"    [FB] {fb_url}")

    try:
        page.goto(fb_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(random.uniform(3000, 4500))
    except Exception as e:
        log.warning(f"    [FB] Failed to load page: {e}")
        return result

    # Login wall — re-login and retry
    if "login" in page.url or "checkpoint" in page.url:
        log.warning("    [FB] Login wall — re-logging in")
        login_facebook(page)
        try:
            page.goto(fb_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)
        except Exception:
            return result

    # Visit /about tab
    try:
        about_url = fb_url.rstrip("/") + "/about"
        page.goto(about_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2500)
    except Exception:
        pass

    # mailto: links
    for link in page.query_selector_all("a[href^='mailto:']"):
        em = (link.get_attribute("href") or "").replace("mailto:", "").strip()
        if em and not result["fb_email"]:
            result["fb_email"] = em

    # tel: links
    for link in page.query_selector_all("a[href^='tel:']"):
        ph = (link.get_attribute("href") or "").replace("tel:", "").strip()
        if ph and not result["fb_phone"]:
            result["fb_phone"] = clean_phone(ph)

    # wa.me links
    for link in page.query_selector_all("a[href*='wa.me'], a[href*='whatsapp']"):
        href = link.get_attribute("href") or ""
        wa = extract_wa_number(href)
        if wa and not result["fb_phone"]:
            result["fb_phone"] = wa

    # Regex fallback
    full_text = page.inner_text("body")
    if not result["fb_email"]:
        result["fb_email"] = extract_email(full_text)
    if not result["fb_phone"]:
        wa = extract_wa_number(full_text)
        result["fb_phone"] = wa or extract_phone(full_text)

    log.info(f"    [FB] phone={result['fb_phone'] or '-'} email={result['fb_email'] or '-'}")
    return result


# ---------------------------------------------------------------------------
# Checkpoint helpers
# ---------------------------------------------------------------------------

def save_checkpoint(path: str, current_page: int, seen_brands: set):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_page": current_page, "seen_brands": list(seen_brands)}, f)

def load_checkpoint(path: str) -> tuple[int, set]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        page_num = data.get("last_page", 1)
        seen = set(data.get("seen_brands", []))
        log.info(f"Resuming from page {page_num}, {len(seen)} brands already done")
        return page_num, seen
    except FileNotFoundError:
        return 1, set()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scrape(max_pages: int | None = None, output_file: str = "brands.csv", checkpoint_file: str = "checkpoint.json"):
    current_page, seen_brands = load_checkpoint(checkpoint_file)
    file_mode = "a" if current_page > 1 else "w"

    with open(output_file, file_mode, newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        if file_mode == "w":
            writer.writeheader()
        csvfile.flush()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                )
            )

            # --- Phase 1: FastMoss login ---
            list_page = context.new_page()
            log.info("Opening FastMoss...")
            list_page.goto("https://www.fastmoss.com/id/shop-marketing/search?region=ID")
            login_fastmoss(list_page)

            # --- Instagram login (dedicated tab, then close) ---
            ig_page = context.new_page()
            ig_page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=15000)
            login_instagram(ig_page)
            ig_page.close()

            # --- Facebook login (dedicated tab, then close) ---
            fb_page = context.new_page()
            login_facebook(fb_page)
            fb_page.close()

            # --- Scraping tab for IG + FB searches ---
            scrape_page = context.new_page()

            list_page.bring_to_front()

            if current_page > 1:
                log.info(f"Navigating to checkpoint page {current_page}...")
                list_page.goto(
                    f"https://www.fastmoss.com/id/shop-marketing/search?region=ID&page={current_page}"
                )

            while True:
                if max_pages and current_page > max_pages:
                    log.info(f"Reached max page limit ({max_pages})")
                    break

                log.info(f"\n=== Page {current_page} ===")

                try:
                    list_page.wait_for_selector("tbody.ant-table-tbody tr.ant-table-row", timeout=15000)
                except Exception:
                    log.warning("Table not found — stopping.")
                    break

                rows = list_page.query_selector_all("tbody.ant-table-tbody tr.ant-table-row")
                log.info(f"Found {len(rows)} rows")

                for i, row in enumerate(rows):
                    name_el = row.query_selector("h3.content.truncate")
                    brand_name = name_el.inner_text().strip() if name_el else ""

                    cat_el = row.query_selector("div.custom-tag-container span.text-ellipsis")
                    category = cat_el.inner_text().strip() if cat_el else ""

                    if not brand_name or brand_name in seen_brands:
                        continue
                    seen_brands.add(brand_name)

                    log.info(f"\n[{i+1}/{len(rows)}] {brand_name} | {category}")

                    ig_data = scrape_instagram(scrape_page, brand_name)
                    time.sleep(random.uniform(2.0, 4.0))
                    fb_data = scrape_facebook(scrape_page, brand_name)

                    writer.writerow({
                        "brand_name": brand_name,
                        "category":   category,
                        "ig_phone":   ig_data.get("ig_phone", ""),
                        "ig_email":   ig_data.get("ig_email", ""),
                        "fb_phone":   fb_data.get("fb_phone", ""),
                        "fb_email":   fb_data.get("fb_email", ""),
                    })
                    csvfile.flush()

                    log.info(
                        f"  => IG phone={ig_data.get('ig_phone') or '-'} email={ig_data.get('ig_email') or '-'} | "
                        f"FB phone={fb_data.get('fb_phone') or '-'} email={fb_data.get('fb_email') or '-'}"
                    )

                    list_page.bring_to_front()
                    time.sleep(random.uniform(2.0, 4.0))

                next_btn = list_page.query_selector("li.ant-pagination-next:not([aria-disabled='true']) button")
                if not next_btn:
                    log.info("No more pages.")
                    break

                next_btn.click()
                try:
                    list_page.wait_for_selector("tbody.ant-table-tbody tr.ant-table-row", timeout=15000)
                except Exception:
                    log.warning("Next page failed to load — stopping.")
                    break

                current_page += 1
                save_checkpoint(checkpoint_file, current_page, seen_brands)

            browser.close()

    log.info(f"\nDone. {len(seen_brands)} brands saved to {output_file}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FastMoss → IG + FB contact scraper")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--output", type=str, default="brands.csv")
    parser.add_argument("--checkpoint", type=str, default="checkpoint.json")
    args = parser.parse_args()

    scrape(max_pages=args.max_pages, output_file=args.output, checkpoint_file=args.checkpoint)
