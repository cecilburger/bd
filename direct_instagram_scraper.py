"""
Direct Instagram contact scraper - simplified approach
"""
from playwright.sync_api import sync_playwright
import logging
import re
import random
import time

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

def scrape_instagram_direct(brand_name: str):
    """Direct approach - try common Instagram URL patterns"""
    result = {"instagram_url": "", "email": "", "phone": "", "whatsapp": ""}

    # Try common Instagram URL patterns
    possible_urls = [
        f"https://www.instagram.com/{brand_name}/",
        f"https://www.instagram.com/{brand_name}official/",
        f"https://www.instagram.com/{brand_name}_official/",
        f"https://www.instagram.com/{brand_name}indonesia/",
        f"https://www.instagram.com/{brand_name}.indo/",
    ]

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )

        # Login to Instagram first
        login_page = context.new_page()
        try:
            log.info("Logging into Instagram...")
            login_page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=10000)

            # Debug: Check what elements are on the page
            inputs = login_page.query_selector_all("input")
            log.info(f"Found {len(inputs)} input elements on login page")
            for i, inp in enumerate(inputs):
                name = inp.get_attribute("name") or ""
                type_attr = inp.get_attribute("type") or ""
                log.info(f"  Input {i+1}: name='{name}', type='{type_attr}'")

            buttons = login_page.query_selector_all("input[type='submit'], button")
            log.info(f"Found {len(buttons)} buttons/submit elements")
            for i, btn in enumerate(buttons):
                tag = btn.evaluate("el => el.tagName")
                type_attr = btn.get_attribute("type") or ""
                text = btn.inner_text().strip()
                log.info(f"  Button {i+1}: {tag} type='{type_attr}' text='{text}'")

            # Wait for and fill login form
            login_page.wait_for_selector("input[name='email']", timeout=5000)
            login_page.fill("input[name='email']", "ther.ezzas")
            login_page.fill("input[name='pass']", "Gilang21.")

            # Try pressing Enter on password field instead of clicking submit
            login_page.press("input[name='pass']", "Enter")

            # Wait for login and dismiss prompts
            login_page.wait_for_timeout(5000)
            try:
                login_page.click("button:has-text('Not Now')", timeout=3000)
            except:
                pass

            log.info("Instagram login successful")
        except Exception as e:
            log.error(f"Instagram login failed: {e}")
            browser.close()
            return result

        login_page.close()

        # Try each possible Instagram URL
        for url in possible_urls:
            profile_page = context.new_page()
            try:
                log.info(f"Trying Instagram URL: {url}")
                profile_page.goto(url, wait_until="domcontentloaded", timeout=15000)
                profile_page.wait_for_timeout(random.uniform(2000, 3000))

                # Check if profile exists
                if "Page Not Found" in profile_page.title() or "/404" in profile_page.url:
                    log.info("Profile not found, trying next URL")
                    profile_page.close()
                    continue

                # Check for login wall
                if "accounts/login" in profile_page.url:
                    log.warning("Hit login wall")
                    profile_page.close()
                    continue

                result["instagram_url"] = url
                log.info(f"Found valid Instagram profile: {url}")

                # Scroll down to load content
                profile_page.evaluate("window.scrollBy(0, 500)")
                profile_page.wait_for_timeout(1000)

                # Try to click Contact button
                contact_clicked = False
                for selector in [
                    "a[role='link']:has-text('Contact')",
                    "a[role='link']:has-text('Kontak')",
                    "button:has-text('Contact')",
                    "button:has-text('Kontak')",
                ]:
                    try:
                        profile_page.click(selector, timeout=2000)
                        contact_clicked = True
                        log.info("Clicked contact button")
                        profile_page.wait_for_timeout(2000)  # Wait for modal to load

                        # Check if modal opened by looking for new content
                        modal_text = profile_page.inner_text("body")
                        if len(modal_text) > len(page_text):
                            log.info("Modal opened - additional content detected")
                            page_text = modal_text  # Update page_text with modal content
                        break
                    except:
                        pass

                if not contact_clicked:
                    log.info("Could not find contact button")

                # Extract from mailto/tel links
                mailto_links = profile_page.query_selector_all("a[href^='mailto:']")
                for link in mailto_links:
                    email = link.get_attribute("href").replace("mailto:", "").split("?")[0].strip()
                    if email and not result["email"]:
                        result["email"] = email
                        log.info(f"Found email: {email}")

                tel_links = profile_page.query_selector_all("a[href^='tel:']")
                for link in tel_links:
                    phone = link.get_attribute("href").replace("tel:", "").strip()
                    if phone and not result["phone"]:
                        result["phone"] = clean_phone(phone)
                        log.info(f"Found phone: {result['phone']}")

                # Extract from page text
                page_text = profile_page.inner_text("body")
                log.info(f"Page text length: {len(page_text)}")

                # Debug: Log some of the page content
                log.info(f"Page content preview: {page_text[:500]}...")

                # Check for Linktree
                linktree_url = extract_linktree_url(page_text)
                if linktree_url:
                    log.info(f"Found Linktree: {linktree_url}")
                    # Scrape Linktree for additional contacts
                    linktree_page = context.new_page()
                    try:
                        linktree_page.goto(linktree_url, wait_until="domcontentloaded", timeout=10000)
                        linktree_page.wait_for_timeout(2000)

                        linktree_text = linktree_page.inner_text("body")
                        log.info(f"Linktree content preview: {linktree_text[:300]}...")

                        if not result["email"]:
                            result["email"] = extract_email(linktree_text)
                        if not result["phone"]:
                            result["phone"] = extract_phone(linktree_text)
                        if not result["whatsapp"]:
                            result["whatsapp"] = extract_wa_number(linktree_text)

                        log.info(f"Linktree results: email={result['email']}, phone={result['phone']}, wa={result['whatsapp']}")
                    except Exception as e:
                        log.warning(f"Linktree scraping failed: {e}")
                    finally:
                        linktree_page.close()

                # Regex fallbacks on page text
                if not result["email"]:
                    result["email"] = extract_email(page_text)
                if not result["phone"]:
                    result["phone"] = extract_phone(page_text)
                if not result["whatsapp"]:
                    result["whatsapp"] = extract_wa_number(page_text)

                log.info(f"Final results: email={result['email'] or '-'}, phone={result['phone'] or '-'}, wa={result['whatsapp'] or '-'}")

                profile_page.close()
                break  # Found a working profile, stop trying other URLs

            except Exception as e:
                log.warning(f"Error with URL {url}: {e}")
                profile_page.close()

        browser.close()
    return result

# Test with known brands
if __name__ == "__main__":
    brands = ["glad2glow.indo", "satukeluargaid"]

    for brand in brands:
        print(f"\n{'='*50}")
        print(f"SCRAPING: {brand}")
        print(f"{'='*50}")

        result = scrape_instagram_direct(brand)
        print(f"Results: {result}")

        if any(result.values()):
            print("✅ Found contact information!")
        else:
            print("❌ No contact information found")

        time.sleep(5)  # Brief pause between brands