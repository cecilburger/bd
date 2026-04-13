"""
Test search functionality
"""
from playwright.sync_api import sync_playwright
import urllib.parse
import re

def test_search():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        query = "glad2glow.indo site:instagram.com"
        domain = "instagram.com"

        print(f"Searching for: {query}")
        print(f"Looking for domain: {domain}")

        # Try DuckDuckGo
        try:
            url = f"https://duckduckgo.com/?q={urllib.parse.quote(query)}&ia=web"
            print(f"\nTrying DuckDuckGo: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=15000)
            page.wait_for_timeout(2000)

            links = page.query_selector_all("a[href]")
            print(f"Found {len(links)} links")

            for i, link in enumerate(links[:10]):  # Just first 10
                href = link.get_attribute("href") or ""
                text = link.inner_text().strip()[:50]
                print(f"  {i+1}: {text} -> {href}")

                if domain in href.lower() and "duckduckgo.com" not in href.lower():
                    print(f"    *** FOUND: {href}")
                    if "duckduckgo.com/l/" in href:
                        m = re.search(r"uddg=([^&]+)", href)
                        if m:
                            real_url = urllib.parse.unquote(m.group(1))
                            print(f"    *** REAL URL: {real_url}")
                    break

        except Exception as e:
            print(f"DuckDuckGo error: {e}")

        browser.close()

if __name__ == "__main__":
    test_search()