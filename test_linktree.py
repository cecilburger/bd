"""
Quick test of Linktree scraping
"""
import re
from playwright.sync_api import sync_playwright

def clean_phone(raw: str) -> str:
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits

def extract_linktree_url(text: str) -> str:
    """Extract Linktree URL from text."""
    m = re.search(r"linktr\.ee/[^\s]+", text)
    return "https://" + m.group(0) if m else ""

def test_linktree():
    linktree_url = "https://linktr.ee/glad2glowofficial"

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        print(f"Visiting: {linktree_url}")
        page.goto(linktree_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        # Check if private
        if "This Linktree is private" in page.inner_text("body"):
            print("Linktree is private")
            return

        print("Scanning links...")
        links = page.query_selector_all("a[href]")
        for link in links:
            href = link.get_attribute("href") or ""
            text = link.inner_text().strip()
            print(f"  {text[:50]} -> {href}")

        browser.close()

if __name__ == "__main__":
    test_linktree()