"""
Debug Instagram contact extraction
"""
from playwright.sync_api import sync_playwright
import logging
import re
import random

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

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
    import urllib.parse
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

def scrape_instagram(context, brand_name: str) -> dict:
    result = {"email": "", "phone": "", "whatsapp": ""}
    page = context.new_page()
    try:
        ig_url = search_first_url(page, f"{brand_name} site:instagram.com", "instagram.com")
        if not ig_url:
            log.info(f"    [IG] No Instagram profile found for {brand_name}")
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
                page.wait_for_selector("input[name='username']", timeout=5000)
                page.fill("input[name='username']", "ther.ezzas")
                page.fill("input[name='password']", "Gilang21.")
                page.click("button[type='submit']")
                page.wait_for_timeout(3000)
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
        contact_clicked = False
        for selector in [
            "a[role='link']:has-text('Contact')", "a[role='link']:has-text('Kontak')",
            "button:has-text('Contact')", "button:has-text('Kontak')",
        ]:
            try:
                btn = page.query_selector(selector)
                if btn:
                    btn.click()
                    page.wait_for_timeout(2000)
                    contact_clicked = True
                    log.info("    [IG] Clicked contact button")
                    break
            except Exception:
                pass

        # Extract from mailto/tel links (most reliable)
        for link in page.query_selector_all("a[href^='mailto:']"):
            em = link.get_attribute("href").replace("mailto:", "").split("?")[0].strip()
            if em and not result["email"]:
                result["email"] = em
                log.info(f"    [IG] Found email: {em}")

        for link in page.query_selector_all("a[href^='tel:']"):
            ph = link.get_attribute("href").replace("tel:", "").strip()
            if ph and not result["phone"]:
                result["phone"] = clean_phone(ph)
                log.info(f"    [IG] Found phone: {result['phone']}")

        # Extract from page text
        full_text = page.inner_text("body")
        log.info(f"    [IG] Page text length: {len(full_text)}")

        # Check for Linktree
        linktree_url = extract_linktree_url(full_text)
        if linktree_url:
            log.info(f"    [IG] Found Linktree: {linktree_url}")
            linktree_data = scrape_linktree(context, linktree_url)
            if linktree_data.get("whatsapp") and not result["phone"]:
                result["phone"] = linktree_data["whatsapp"]
                result["whatsapp"] = linktree_data["whatsapp"]
                log.info(f"    [IG] WhatsApp from Linktree: {result['whatsapp']}")
            if linktree_data.get("email") and not result["email"]:
                result["email"] = linktree_data["email"]
                log.info(f"    [IG] Email from Linktree: {result['email']}")

        # Regex fallbacks
        if not result["email"]:
            result["email"] = extract_email(full_text)
        if not result["phone"]:
            result["phone"] = extract_phone(full_text)
        if not result["whatsapp"]:
            result["whatsapp"] = extract_wa_number(full_text)

        log.info(f"    [IG] Final: email={result['email'] or '-'} phone={result['phone'] or '-'} wa={result['whatsapp'] or '-'}")

    except Exception as e:
        log.warning(f"    [IG] Error: {e}")
    finally:
        page.close()
    return result

def test_brand(brand_name: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        # Login to Instagram first
        login_page = context.new_page()
        login_page.goto("https://www.instagram.com/accounts/login/")
        login_page.wait_for_selector("input[name='username']", timeout=10000)
        login_page.fill("input[name='username']", "ther.ezzas")
        login_page.fill("input[name='password']", "Gilang21.")
        login_page.click("button[type='submit']")
        login_page.wait_for_timeout(5000)

        # Dismiss prompts
        for prompt in ["button:has-text('Not Now')", "button:has-text('Nanti Saja')"]:
            try:
                login_page.click(prompt, timeout=3000)
                login_page.wait_for_timeout(1000)
            except Exception:
                pass

        login_page.close()

        # Test scraping
        result = scrape_instagram(context, brand_name)
        print(f"\nResult for {brand_name}: {result}")

        browser.close()

if __name__ == "__main__":
    test_brand("glad2glow.indo")