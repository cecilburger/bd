"""
Phase 2 — For each brand in brands_raw.csv, find Instagram profile
and extract contact info (email, phone).
Output: brands_final.csv
Checkpoint: checkpoint.json (resume-safe)
"""
import argparse
import csv
import json
import logging
import random
import re
import time

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

FIELDNAMES = ["brand_name", "category", "email", "phone", "whatsapp"]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def clean_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits

def extract_email(text: str) -> str:
    m = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
    return m.group(0) if m else ""

def extract_phone(text: str) -> str:
    m = re.search(r"(\+?62[\s\-]?\d[\d\s\-]{7,14}|0\d[\d\s\-]{7,14})", text)
    return clean_phone(m.group(0)) if m else ""


def extract_linktree_url(text: str) -> str:
    """Extract Linktree URL from text."""
    m = re.search(r"linktr\.ee/[^\s]+", text)
    return "https://" + m.group(0) if m else ""

def is_better_website(current: str, candidate: str) -> bool:
    """Check if candidate website is better than current one."""
    if not current:
        return True

    # Priority domains (higher = better)
    priority_domains = [
        '.com', '.co.id', '.id', '.net', '.org', '.io', '.co', '.shop', '.store'
    ]

    # E-commerce platforms
    ecomm_domains = ['tokopedia.com', 'shopee.co.id', 'bukalapak.com', 'lazada.co.id']

    # Low priority domains
    low_priority = ['threads.net', 'meta.com', 'instagram.com', 'facebook.com']

    # If current is low priority and candidate is not, prefer candidate
    current_low = any(domain in current.lower() for domain in low_priority)
    candidate_low = any(domain in candidate.lower() for domain in low_priority)

    if current_low and not candidate_low:
        return True

    # If both are similar priority, prefer e-commerce or .com domains
    current_ecomm = any(domain in current.lower() for domain in ecomm_domains)
    candidate_ecomm = any(domain in candidate.lower() for domain in ecomm_domains)

    if candidate_ecomm and not current_ecomm:
        return True

    # Prefer .com over other TLDs
    current_has_good_tld = any(current.lower().endswith(tld) for tld in priority_domains[:4])
    candidate_has_good_tld = any(candidate.lower().endswith(tld) for tld in priority_domains[:4])

    if candidate_has_good_tld and not current_has_good_tld:
        return True

    return False


# ---------------------------------------------------------------------------
# Instagram login
# ---------------------------------------------------------------------------

def login_instagram(page):
    """Automatically log in to Instagram."""
    try:
        log.info("Logging in to Instagram...")
        # Wait for login form
        page.wait_for_selector("input[name='username']", timeout=10000)

        # Fill username
        page.fill("input[name='username']", "ther.ezzas")

        # Fill password
        page.wait_for_selector("input[name='password']", timeout=5000)
        page.fill("input[name='password']", "Gilang21.")

        # Small pause so the button becomes enabled
        page.wait_for_timeout(500)

        # Click login button — Instagram uses div[role='button'], not button[type='submit']
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
                    log.info(f"Clicked login button ({sel})")
                    clicked = True
                    break
            except Exception:
                pass

        if not clicked:
            log.warning("Could not find Instagram login button")
            return

        # Wait for login to complete
        page.wait_for_timeout(5000)

        # Check for "Save Info" prompt
        try:
            page.click("button:has-text('Not Now')", timeout=5000)
        except:
            pass

        # Check for "Turn on notifications" prompt
        try:
            page.click("button:has-text('Not Now')", timeout=5000)
        except:
            pass

        log.info("Instagram login completed")

    except Exception as e:
        log.warning(f"Instagram login failed: {e}")


# ---------------------------------------------------------------------------
# Checkpoint
# ---------------------------------------------------------------------------

def save_checkpoint(path: str, last_index: int, seen: set):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"last_index": last_index, "seen": list(seen)}, f)

def load_checkpoint(path: str) -> tuple[int, set]:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        log.info(f"Resuming from index {data['last_index']}, {len(data['seen'])} brands done")
        return data["last_index"], set(data["seen"])
    except FileNotFoundError:
        return 0, set()


# ---------------------------------------------------------------------------
# Core: find IG profile and extract contact
# ---------------------------------------------------------------------------

def find_ig_contact(page, brand_name: str) -> dict:
    result = {"ig_url": "", "ig_phone": "", "ig_email": "", "ig_whatsapp": ""}

    # Step 1: Google search for instagram profile — same tab
    search_url = f"https://www.google.com/search?q={brand_name.replace(' ', '+')}+site:instagram.com"
    try:
        page.goto(search_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(random.uniform(1500, 2500))
    except Exception as e:
        log.warning(f"  Google search failed: {e}")
        return result

    # Step 2: Grab first instagram.com link from results
    ig_url = ""
    for link in page.query_selector_all("a[href]"):
        href = link.get_attribute("href") or ""
        if "instagram.com/" in href and "google.com" not in href:
            # Strip Google redirect wrapper if present
            m = re.search(r"(https?://(?:www\.)?instagram\.com/[^\s&\"]+)", href)
            if m:
                ig_url = m.group(1)
                break

    if not ig_url:
        log.info(f"  [IG] No profile found for: {brand_name}")
        return result

    result["ig_url"] = ig_url
    log.info(f"  [IG] {ig_url[:80]}")

    # Step 3: Visit IG profile — same tab
    try:
        page.goto(ig_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(random.uniform(3000, 5000))
        page.evaluate("window.scrollBy(0, 300)")
        page.wait_for_timeout(1000)
    except Exception as e:
        log.warning(f"  [IG] Failed to load profile: {e}")
        return result

    # Step 4: Detect login wall or challenge
    if "accounts/login" in page.url or "challenge" in page.url:
        log.warning("  [IG] Login wall detected — attempting automatic re-login")
        try:
            page.goto("https://www.instagram.com/accounts/login/", wait_until="domcontentloaded", timeout=10000)

            page.wait_for_selector("input[name='username']", timeout=8000)
            page.fill("input[name='username']", "ther.ezzas")
            page.wait_for_selector("input[name='password']", timeout=5000)
            page.fill("input[name='password']", "Gilang21.")
            page.wait_for_timeout(500)

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
                log.error("  [IG] Could not find login button during re-login")
                return result

            page.wait_for_timeout(4000)

            for prompt in ["button:has-text('Not Now')", "button:has-text('Nanti Saja')"]:
                try:
                    page.click(prompt, timeout=2000)
                    page.wait_for_timeout(1000)
                except Exception:
                    pass

            page.goto(ig_url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(3000)
            log.info("  [IG] Automatic re-login successful")
        except Exception as e:
            log.error(f"  [IG] Automatic re-login failed: {e}")
            return result

    # Step 5: Click Contact button to open modal
    btn = page.query_selector(
        "a[role='link']:has-text('Contact'), a[role='link']:has-text('Kontak'), "
        "button:has-text('Contact'), button:has-text('Kontak')"
    )
    if btn:
        try:
            btn.click()
            page.wait_for_timeout(2000)
        except Exception:
            pass

    # Step 6: mailto / tel links (most reliable, works after modal opens)
    for link in page.query_selector_all("a[href^='mailto:']"):
        em = (link.get_attribute("href") or "").replace("mailto:", "").strip()
        if em:
            result["ig_email"] = em
            break

    for link in page.query_selector_all("a[href^='tel:']"):
        ph = (link.get_attribute("href") or "").replace("tel:", "").strip()
        if ph:
            result["ig_phone"] = clean_phone(ph)
            break

    # Step 7: Regex fallback on full page text + bio
    full_text = page.inner_text("body")

    if not result["ig_email"]:
        result["ig_email"] = extract_email(full_text)

    if not result["ig_phone"]:
        result["ig_phone"] = extract_phone(full_text)

    # WhatsApp from wa.me links in page text
    wa_match = re.search(r"wa\.me/(\d+)", full_text)
    if wa_match:
        result["ig_whatsapp"] = wa_match.group(1)
        if not result["ig_phone"]:
            result["ig_phone"] = result["ig_whatsapp"]

    # Check bio for Linktree URL
    linktree_url = extract_linktree_url(full_text)
    if linktree_url:
        log.info(f"  [IG] Found Linktree: {linktree_url}")
        linktree_data = scrape_linktree(page, linktree_url)

        if not result["ig_whatsapp"] and linktree_data.get("whatsapp"):
            result["ig_whatsapp"] = linktree_data["whatsapp"]
            if not result["ig_phone"]:
                result["ig_phone"] = result["ig_whatsapp"]
            log.info(f"  [IG] WhatsApp from Linktree: {result['ig_whatsapp']}")

        if not result["ig_email"] and linktree_data.get("email"):
            result["ig_email"] = linktree_data["email"]
            log.info(f"  [IG] Email from Linktree: {result['ig_email']}")

    log.info(f"  [IG] email={result['ig_email'] or '-'} phone={result['ig_phone'] or '-'} wa={result['ig_whatsapp'] or '-'}")
    return result


# ---------------------------------------------------------------------------
# Linktree scraper (extracts WhatsApp and other links)
# ---------------------------------------------------------------------------

def scrape_linktree(page, linktree_url: str) -> dict:
    result = {"whatsapp": "", "email": "", "website": "", "tiktok": "", "facebook": ""}
    try:
        log.info(f"  [LINKTREE] {linktree_url[:80]}")
        page.goto(linktree_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # Check if Linktree is private/locked
        if "This Linktree is private" in page.inner_text("body") or "locked" in page.inner_text("body").lower():
            log.warning("  [LINKTREE] Linktree is private/locked, skipping")
            return result

        # Scan all links on the page
        for link in page.query_selector_all("a[href]"):
            href = link.get_attribute("href") or ""

            # WhatsApp links
            if not result["whatsapp"]:
                if "wa.me/" in href:
                    wa_match = re.search(r"wa\.me/(\d+)", href)
                    if wa_match:
                        result["whatsapp"] = wa_match.group(1)
                        log.info(f"  [LINKTREE] Found WhatsApp: {result['whatsapp']}")
                elif "whatsapp.com/send" in href:
                    phone_match = re.search(r"phone=(\d+)", href)
                    if phone_match:
                        result["whatsapp"] = clean_phone(phone_match.group(1))
                        log.info(f"  [LINKTREE] Found WhatsApp: {result['whatsapp']}")

            # Email links
            if not result["email"] and href.startswith("mailto:"):
                email = href.replace("mailto:", "").strip()
                if email:
                    result["email"] = email
                    log.info(f"  [LINKTREE] Found email: {result['email']}")

            # Website (external links, not social media)
            if not result["website"] and href.startswith("http"):
                if ("linktr.ee" not in href and
                    "instagram.com" not in href and
                    "facebook.com" not in href and
                    "tiktok.com" not in href and
                    "twitter.com" not in href and
                    "youtube.com" not in href and
                    "wa.me" not in href and
                    "whatsapp.com" not in href):
                    result["website"] = href
                    log.info(f"  [LINKTREE] Found website: {result['website']}")

            # TikTok
            if not result["tiktok"] and "tiktok.com" in href:
                result["tiktok"] = href
                log.info(f"  [LINKTREE] Found TikTok: {result['tiktok']}")

            # Facebook (additional)
            if not result["facebook"] and "facebook.com" in href and "facebook.com/l.php" not in href:
                result["facebook"] = href
                log.info(f"  [LINKTREE] Found Facebook: {result['facebook']}")

    except Exception as e:
        log.warning(f"  [LINKTREE] Error: {e}")

    return result


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run(
    input_file: str = "brands_raw.csv",
    output_file: str = "brands_final.csv",
    checkpoint_file: str = "checkpoint.json",
):
    # Load brands
    with open(input_file, encoding="utf-8") as f:
        brands = list(csv.DictReader(f))
    log.info(f"Loaded {len(brands)} brands from {input_file}")

    start_index, seen = load_checkpoint(checkpoint_file)
    file_mode = "a" if start_index > 0 else "w"

    with open(output_file, file_mode, newline="", encoding="utf-8") as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=FIELDNAMES)
        if file_mode == "w":
            writer.writeheader()
        csvfile.flush()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=False)
            context = browser.new_context()
            page = context.new_page()  # single tab for all operations

            # Login Instagram once
            page.goto("https://www.instagram.com/accounts/login/")
            login_instagram(page)

            for i, brand in enumerate(brands):
                if i < start_index:
                    continue

                brand_name = brand["brand_name"]
                category = brand["category"]

                if brand_name in seen:
                    continue
                seen.add(brand_name)

                log.info(f"[{i+1}/{len(brands)}] {brand_name}")

                contact = find_ig_contact(page, brand_name)

                writer.writerow({
                    "brand_name": brand_name,
                    "category": category,
                    "email": contact["ig_email"],
                    "phone": contact["ig_phone"],
                    "whatsapp": contact.get("ig_whatsapp", ""),
                })
                csvfile.flush()

                save_checkpoint(checkpoint_file, i + 1, seen)

                time.sleep(random.uniform(3.0, 6.0))

            browser.close()

    log.info(f"Done. Results saved to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 2 — Instagram contact scraper")
    parser.add_argument("--input", type=str, default="brands_raw.csv")
    parser.add_argument("--output", type=str, default="brands_final.csv")
    parser.add_argument("--checkpoint", type=str, default="checkpoint.json")
    args = parser.parse_args()
    run(input_file=args.input, output_file=args.output, checkpoint_file=args.checkpoint)
