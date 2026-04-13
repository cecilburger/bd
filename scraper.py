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
        r"whatsapp\.com/send\?.*?phone=(\d{8,15})",
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

def extract_linktree_url(text: str) -> str:
    m = re.search(r"linktr\.ee/([\w.\-_]+)", text)
    return f"https://linktr.ee/{m.group(1)}" if m else ""

def search_first_url(page, query: str, domain: str) -> str:
    """Try DuckDuckGo then Bing, return first URL containing domain."""
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
# Linktree — contact info only, nothing else
# ---------------------------------------------------------------------------

def scrape_linktree(context, linktree_url: str) -> dict:
    result = {"whatsapp": "", "email": ""}
    page = context.new_page()
    try:
        log.info(f"    [LT] {linktree_url}")
        page.goto(linktree_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        body_text = page.inner_text("body")
        if "private" in body_text.lower() or "locked" in body_text.lower():
            log.warning("    [LT] Private/locked, skipping")
            return result

        for link in page.query_selector_all("a[href]"):
            href = link.get_attribute("href") or ""

            if not result["whatsapp"]:
                wa = extract_wa_number(href)
                if wa:
                    result["whatsapp"] = wa
                    log.info(f"    [LT] WhatsApp: {wa}")

            if not result["email"] and href.startswith("mailto:"):
                em = href.replace("mailto:", "").split("?")[0].strip()
                if em:
                    result["email"] = em
                    log.info(f"    [LT] Email: {em}")

            if result["whatsapp"] and result["email"]:
                break

        if not result["whatsapp"]:
            wa = extract_wa_number(body_text)
            if wa:
                result["whatsapp"] = wa

        if not result["email"]:
            result["email"] = extract_email(body_text)

        log.info(f"    [LT] email={result['email'] or '-'} wa={result['whatsapp'] or '-'}")

    except Exception as e:
        log.warning(f"    [LT] Error: {e}")
    finally:
        page.close()
    return result


# ---------------------------------------------------------------------------
# Layer 1 — Instagram
# ---------------------------------------------------------------------------

def scrape_instagram(context, brand_name: str) -> dict:
    result = {"email": "", "phone": "", "whatsapp": ""}
    page = context.new_page()
    try:
        ig_url = search_first_url(page, f"{brand_name} site:instagram.com", "instagram.com")
        if not ig_url:
            ig_url = search_first_url(page, f"{brand_name} instagram indonesia", "instagram.com")
        if not ig_url:
            log.info(f"    [IG] No profile found")
            return result

        ig_url = re.split(r"\?", ig_url)[0].rstrip("/")
        log.info(f"    [IG] {ig_url}")

        page.goto(ig_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(random.uniform(3000, 4500))
        page.evaluate("window.scrollBy(0, 300)")
        page.wait_for_timeout(1000)

        if "accounts/login" in page.url or "challenge" in page.url:
            log.warning("    [IG] Login wall detected — attempting automatic re-login")
            try:
                page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=10000)

                page.wait_for_selector("input[name='username']", timeout=8000)
                page.fill("input[name='username']", "ther.ezzas")
                page.wait_for_selector("input[name='password']", timeout=5000)
                page.fill("input[name='password']", "Gilang21.")
                page.wait_for_timeout(500)

                # Click the actual IG login button
                clicked = False
                for sel in [
                    "div[role='button'][aria-label='Log In']",
                    "div[role='button'][aria-label='Masuk']",
                    "button[type='submit']",
                ]:
                    try:
                        btn = page.wait_for_selector(sel, timeout=3000)
                        if btn:
                            btn.click()
                            clicked = True
                            break
                    except Exception:
                        pass

                if not clicked:
                    log.error("    [IG] Could not find login button during re-login")
                    return result

                page.wait_for_timeout(4000)

                for prompt in ["button:has-text('Not Now')", "button:has-text('Nanti Saja')"]:
                    try:
                        page.click(prompt, timeout=2000)
                        page.wait_for_timeout(1000)
                    except Exception:
                        pass

                page.goto(ig_url, wait_until="domcontentloaded", timeout=20000)
                page.wait_for_timeout(3000)
                log.info("    [IG] Automatic re-login successful")
            except Exception as e:
                log.error(f"    [IG] Automatic re-login failed: {e}")
                return result

        if "Page Not Found" in (page.title() or "") or "/404" in page.url:
            log.warning("    [IG] Profile not found")
            return result

        # Click Contact / Kontak button (business profiles show email/phone in modal)
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

        # mailto: and tel: links (most reliable, appear after modal opens)
        for link in page.query_selector_all("a[href^='mailto:']"):
            em = (link.get_attribute("href") or "").replace("mailto:", "").strip()
            if em and not result["email"]:
                result["email"] = em

        for link in page.query_selector_all("a[href^='tel:']"):
            ph = (link.get_attribute("href") or "").replace("tel:", "").strip()
            if ph and not result["phone"]:
                result["phone"] = clean_phone(ph)

        # wa.me href links
        for link in page.query_selector_all("a[href*='wa.me'], a[href*='whatsapp']"):
            href = link.get_attribute("href") or ""
            wa = extract_wa_number(href)
            if wa and not result["whatsapp"]:
                result["whatsapp"] = wa
                if not result["phone"]:
                    result["phone"] = wa

        # Full page text fallback
        full_text = page.inner_text("body")

        if not result["whatsapp"]:
            wa = extract_wa_number(full_text)
            if wa:
                result["whatsapp"] = wa
                if not result["phone"]:
                    result["phone"] = wa

        if not result["email"]:
            result["email"] = extract_email(full_text)
        if not result["phone"]:
            result["phone"] = extract_phone(full_text)

        # Check bio for Linktree (common for Indonesian brands)
        linktree_url = extract_linktree_url(full_text)
        if not linktree_url:
            # Bio link may be a linktree behind an instagram redirect
            for link in page.query_selector_all("header a[href], a[href*='l.instagram.com']"):
                href = link.get_attribute("href") or ""
                if "linktr.ee" in href or "linktree" in href:
                    m = re.search(r"linktr\.ee/([\w.\-_]+)", urllib.parse.unquote(href))
                    if m:
                        linktree_url = f"https://linktr.ee/{m.group(1)}"
                    break

        if linktree_url and (not result["email"] or not result["whatsapp"]):
            lt = scrape_linktree(context, linktree_url)
            if not result["whatsapp"] and lt.get("whatsapp"):
                result["whatsapp"] = lt["whatsapp"]
                if not result["phone"]:
                    result["phone"] = lt["whatsapp"]
            if not result["email"] and lt.get("email"):
                result["email"] = lt["email"]

        log.info(f"    [IG] email={result['email'] or '-'} phone={result['phone'] or '-'} wa={result['whatsapp'] or '-'}")

    except Exception as e:
        log.warning(f"    [IG] Error: {e}")
    finally:
        page.close()
    return result


# ---------------------------------------------------------------------------
# Layer 2 — TikTok
# ---------------------------------------------------------------------------

def scrape_tiktok(context, brand_name: str) -> dict:
    result = {"email": "", "phone": "", "whatsapp": ""}
    page = context.new_page()
    try:
        tt_url = search_first_url(page, f"{brand_name} site:tiktok.com", "tiktok.com")
        if not tt_url:
            tt_url = search_first_url(page, f"{brand_name} tiktok indonesia", "tiktok.com")
        if not tt_url:
            log.info(f"    [TT] No profile found")
            return result

        tt_url = re.split(r"\?", tt_url)[0].rstrip("/")
        if "/video/" in tt_url:
            tt_url = "/".join(tt_url.split("/video/")[0].split("/")[:4])

        log.info(f"    [TT] {tt_url}")
        page.goto(tt_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(random.uniform(3000, 4000))

        for link in page.query_selector_all("a[href*='wa.me'], a[href*='whatsapp']"):
            href = link.get_attribute("href") or ""
            wa = extract_wa_number(href)
            if wa and not result["whatsapp"]:
                result["whatsapp"] = wa
                if not result["phone"]:
                    result["phone"] = wa

        full_text = page.inner_text("body")

        if not result["whatsapp"]:
            wa = extract_wa_number(full_text)
            if wa:
                result["whatsapp"] = wa
                if not result["phone"]:
                    result["phone"] = wa

        if not result["email"]:
            result["email"] = extract_email(full_text)
        if not result["phone"]:
            result["phone"] = extract_phone(full_text)

        linktree_url = extract_linktree_url(full_text)
        if linktree_url and (not result["email"] or not result["whatsapp"]):
            lt = scrape_linktree(context, linktree_url)
            if not result["whatsapp"] and lt.get("whatsapp"):
                result["whatsapp"] = lt["whatsapp"]
                if not result["phone"]:
                    result["phone"] = lt["whatsapp"]
            if not result["email"] and lt.get("email"):
                result["email"] = lt["email"]

        log.info(f"    [TT] email={result['email'] or '-'} phone={result['phone'] or '-'} wa={result['whatsapp'] or '-'}")

    except Exception as e:
        log.warning(f"    [TT] Error: {e}")
    finally:
        page.close()
    return result


# ---------------------------------------------------------------------------
# Layer 3 — Tokopedia store page
# ---------------------------------------------------------------------------

def scrape_tokopedia(context, brand_name: str) -> dict:
    result = {"email": "", "phone": "", "whatsapp": ""}
    page = context.new_page()
    try:
        tok_url = search_first_url(page, f"{brand_name} tokopedia", "tokopedia.com")
        if not tok_url:
            log.info(f"    [TOK] No store found")
            return result

        tok_url = re.split(r"\?", tok_url)[0].rstrip("/")
        log.info(f"    [TOK] {tok_url}")
        page.goto(tok_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        for link in page.query_selector_all("a[href*='wa.me'], a[href*='whatsapp']"):
            href = link.get_attribute("href") or ""
            wa = extract_wa_number(href)
            if wa and not result["whatsapp"]:
                result["whatsapp"] = wa
                result["phone"] = wa

        full_text = page.inner_text("body")

        if not result["whatsapp"]:
            wa = extract_wa_number(full_text)
            if wa:
                result["whatsapp"] = wa
                result["phone"] = wa

        if not result["email"]:
            result["email"] = extract_email(full_text)
        if not result["phone"]:
            result["phone"] = extract_phone(full_text)

        log.info(f"    [TOK] email={result['email'] or '-'} phone={result['phone'] or '-'} wa={result['whatsapp'] or '-'}")

    except Exception as e:
        log.warning(f"    [TOK] Error: {e}")
    finally:
        page.close()
    return result


# ---------------------------------------------------------------------------
# Layer 4 — Facebook page
# ---------------------------------------------------------------------------

def scrape_facebook(context, brand_name: str) -> dict:
    result = {"email": "", "phone": "", "whatsapp": ""}
    page = context.new_page()
    try:
        # Search for the brand's Facebook page via DuckDuckGo/Bing first
        fb_url = search_first_url(page, f"{brand_name} site:facebook.com", "facebook.com")
        if not fb_url:
            fb_url = search_first_url(page, f"{brand_name} facebook indonesia", "facebook.com")
        if not fb_url:
            log.info("    [FB] No page found")
            return result

        # Normalise: strip query params, keep only page root
        fb_url = re.split(r"\?", fb_url)[0].rstrip("/")
        # Skip non-page URLs (groups, videos, posts, photos, people)
        if any(x in fb_url for x in ["/groups/", "/video", "/posts/", "/photos/", "/people/"]):
            log.info(f"    [FB] Skipping non-page URL: {fb_url}")
            return result

        log.info(f"    [FB] {fb_url}")
        page.goto(fb_url, wait_until="domcontentloaded", timeout=20000)
        page.wait_for_timeout(random.uniform(3000, 4500))

        # Redirect to login? Re-login and retry.
        if "login" in page.url or "checkpoint" in page.url:
            log.warning("    [FB] Login wall — attempting re-login")
            login_facebook(page)
            page.goto(fb_url, wait_until="domcontentloaded", timeout=20000)
            page.wait_for_timeout(3000)

        # Try the /about tab which often has contact details
        about_url = fb_url.rstrip("/") + "/about"
        page.goto(about_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2500)

        # WhatsApp links
        for link in page.query_selector_all("a[href*='wa.me'], a[href*='whatsapp']"):
            href = link.get_attribute("href") or ""
            wa = extract_wa_number(href)
            if wa and not result["whatsapp"]:
                result["whatsapp"] = wa
                if not result["phone"]:
                    result["phone"] = wa

        # mailto: links
        for link in page.query_selector_all("a[href^='mailto:']"):
            em = (link.get_attribute("href") or "").replace("mailto:", "").strip()
            if em and not result["email"]:
                result["email"] = em

        # tel: links
        for link in page.query_selector_all("a[href^='tel:']"):
            ph = (link.get_attribute("href") or "").replace("tel:", "").strip()
            if ph and not result["phone"]:
                result["phone"] = clean_phone(ph)

        full_text = page.inner_text("body")

        if not result["whatsapp"]:
            wa = extract_wa_number(full_text)
            if wa:
                result["whatsapp"] = wa
                if not result["phone"]:
                    result["phone"] = wa

        if not result["email"]:
            result["email"] = extract_email(full_text)
        if not result["phone"]:
            result["phone"] = extract_phone(full_text)

        # Linktree in bio
        linktree_url = extract_linktree_url(full_text)
        if linktree_url and (not result["email"] or not result["whatsapp"]):
            lt = scrape_linktree(context, linktree_url)
            if not result["whatsapp"] and lt.get("whatsapp"):
                result["whatsapp"] = lt["whatsapp"]
                if not result["phone"]:
                    result["phone"] = lt["whatsapp"]
            if not result["email"] and lt.get("email"):
                result["email"] = lt["email"]

        log.info(f"    [FB] email={result['email'] or '-'} phone={result['phone'] or '-'} wa={result['whatsapp'] or '-'}")

    except Exception as e:
        log.warning(f"    [FB] Error: {e}")
    finally:
        page.close()
    return result


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------

def find_contact(context, brand_name: str) -> dict:
    result = {"brand_name": brand_name, "email": "", "phone": "", "whatsapp": ""}

    def merge(src: dict):
        for key in ("email", "phone", "whatsapp"):
            if not result[key] and src.get(key):
                result[key] = src[key]

    def done():
        return bool(result["email"] and result["phone"])

    log.info(f"  [1/4] Instagram")
    merge(scrape_instagram(context, brand_name))
    if done():
        return result

    log.info(f"  [2/4] TikTok")
    merge(scrape_tiktok(context, brand_name))
    if done():
        return result

    log.info(f"  [3/4] Tokopedia")
    merge(scrape_tokopedia(context, brand_name))
    if done():
        return result

    log.info(f"  [4/4] Facebook")
    merge(scrape_facebook(context, brand_name))

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
# Login helpers
# ---------------------------------------------------------------------------

def login_fastmoss(page):
    try:
        log.info("Logging in to FastMoss...")
        page.wait_for_timeout(1500)

        # Step 1: Click the "Masuk" div button to open the login modal
        masuk_btn = page.query_selector("div.bg-vi:has-text('Masuk'), div.text-white:has-text('Masuk')")
        if masuk_btn:
            masuk_btn.click()
            log.info("Clicked Masuk button")
            page.wait_for_timeout(2000)
        else:
            log.warning("Could not find Masuk button")
            return

        # Step 2: Fill email
        email_found = False
        for sel in ["input[type='email']", "input[name='email']", "input[placeholder*='email']", "input[placeholder*='Email']"]:
            try:
                page.wait_for_selector(sel, timeout=3000)
                page.fill(sel, "creative.mcnasia@gmail.com")
                email_found = True
                log.info("Found email input field")
                break
            except Exception:
                pass

        if not email_found:
            log.warning("Could not find email input field")
            return

        # Step 3: Fill password
        for sel in ["input[type='password']", "input[name='password']"]:
            try:
                page.fill(sel, "Mcnasia2000")
                log.info("Found password input field")
                break
            except Exception:
                pass

        # Step 4: Click submit
        for sel in ["button[type='submit']", "button:has-text('Login')", "button:has-text('Masuk')", "input[type='submit']"]:
            try:
                page.click(sel)
                log.info("Clicked submit button")
                break
            except Exception:
                pass

        page.wait_for_timeout(4000)
        log.info("FastMoss login attempt completed")
    except Exception as e:
        log.warning(f"FastMoss login failed: {e}")


def login_facebook(page):
    try:
        log.info("Logging in to Facebook...")
        page.goto("https://www.facebook.com/login", wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # Check if already logged in
        if "login" not in page.url and "checkpoint" not in page.url:
            log.info("Already logged in to Facebook")
            return

        # Fill email/phone
        page.wait_for_selector("input#email", timeout=8000)
        page.fill("input#email", "081953923038")
        log.info("Found Facebook email/phone input")

        # Fill password
        page.wait_for_selector("input#pass", timeout=5000)
        page.fill("input#pass", "Mcn2026@")
        log.info("Found Facebook password input")

        page.wait_for_timeout(500)

        # Click login button — Facebook uses button[name='login']
        clicked = False
        for sel in ["button[name='login']", "button[type='submit']", "input[type='submit']"]:
            try:
                btn = page.wait_for_selector(sel, timeout=3000)
                if btn:
                    btn.click()
                    log.info(f"Clicked Facebook login button ({sel})")
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            log.warning("Could not find Facebook login button")
            return

        page.wait_for_timeout(5000)

        # Dismiss any post-login prompts
        for prompt in ["button:has-text('Not Now')", "button:has-text('Nanti')", "[aria-label='Close']"]:
            try:
                page.click(prompt, timeout=2000)
                page.wait_for_timeout(800)
            except Exception:
                pass

        log.info("Facebook login attempt completed")
    except Exception as e:
        log.warning(f"Facebook login failed: {e}")


def login_instagram(page):
    try:
        log.info("Logging in to Instagram...")
        page.wait_for_load_state("domcontentloaded", timeout=10000)

        # Check if already logged in
        if "accounts/login" not in page.url and "challenge" not in page.url:
            log.info("Already logged in to Instagram")
            return

        # Wait for and fill username
        page.wait_for_selector("input[name='username']", timeout=8000)
        page.fill("input[name='username']", "ther.ezzas")
        log.info("Found email input field")

        # Fill password
        page.wait_for_selector("input[name='password']", timeout=5000)
        page.fill("input[name='password']", "Gilang21.")
        log.info("Found password input field")

        # Small pause so the button becomes enabled
        page.wait_for_timeout(500)

        # Instagram login button — try div[role='button'] first, then button[type='submit']
        clicked = False
        for sel in [
            "div[role='button'][aria-label='Log In']",
            "div[role='button'][aria-label='Masuk']",
            "button[type='submit']",
            "input[type='submit']",
        ]:
            try:
                btn = page.wait_for_selector(sel, timeout=3000)
                if btn:
                    btn.click()
                    log.info(f"Clicked login button ({sel})")
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            log.warning("Could not find Instagram login button")
            return

        page.wait_for_timeout(5000)

        # Dismiss any prompts
        for prompt in ["button:has-text('Not Now')", "button:has-text('Nanti Saja')", "button:has-text('Save Info')"]:
            try:
                page.click(prompt, timeout=4000)
                page.wait_for_timeout(1000)
                log.info(f"Dismissed prompt: {prompt}")
            except Exception:
                pass

        log.info("Instagram login attempt completed")
    except Exception as e:
        log.warning(f"Instagram login failed: {e}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def scrape(max_pages: int | None = None, output_file: str = "brands.csv", checkpoint_file: str = "checkpoint.json"):
    current_page, seen_brands = load_checkpoint(checkpoint_file)
    file_mode = "a" if current_page > 1 else "w"

    fieldnames = ["brand_name", "category", "email", "phone", "whatsapp"]

    with open(output_file, file_mode, newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
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

            list_page = context.new_page()
            log.info("Opening FastMoss...")
            list_page.goto("https://www.fastmoss.com/id/shop-marketing/search?region=ID")
            login_fastmoss(list_page)

            ig_page = context.new_page()
            ig_page.goto("https://www.instagram.com/accounts/login/")
            login_instagram(ig_page)
            ig_page.close()

            fb_page = context.new_page()
            login_facebook(fb_page)
            fb_page.close()

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

                    contact = find_contact(context, brand_name)
                    contact["category"] = category

                    writer.writerow({k: contact.get(k, "") for k in fieldnames})
                    csvfile.flush()

                    log.info(f"  => email={contact['email'] or 'MISSING'} | phone={contact['phone'] or 'MISSING'} | wa={contact['whatsapp'] or 'MISSING'}")

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
    parser = argparse.ArgumentParser(description="FastMoss contact scraper")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--output", type=str, default="brands.csv")
    parser.add_argument("--checkpoint", type=str, default="checkpoint.json")
    args = parser.parse_args()

    scrape(max_pages=args.max_pages, output_file=args.output, checkpoint_file=args.checkpoint)
