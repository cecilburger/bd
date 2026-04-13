"""
Test login page structure
"""
from playwright.sync_api import sync_playwright
import time

def test_login_pages():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()

        # Test FastMoss login page
        print("=== Testing FastMoss Login ===")
        fm_page = context.new_page()
        fm_page.goto("https://www.fastmoss.com/id/shop-marketing/search?region=ID")
        fm_page.wait_for_load_state("networkidle", timeout=10000)

        # Get all input elements
        inputs = fm_page.query_selector_all("input")
        print(f"Found {len(inputs)} input elements:")
        for i, inp in enumerate(inputs):
            attrs = fm_page.evaluate("""
                (el) => {
                    return {
                        type: el.type,
                        name: el.name,
                        placeholder: el.placeholder,
                        id: el.id,
                        className: el.className
                    };
                }
            """, inp)
            print(f"  {i+1}: {attrs}")

        # Get all button elements
        buttons = fm_page.query_selector_all("button")
        print(f"Found {len(buttons)} button elements:")
        for i, btn in enumerate(buttons):
            text = btn.inner_text().strip()
            attrs = fm_page.evaluate("""
                (el) => {
                    return {
                        type: el.type,
                        text: el.innerText.trim()
                    };
                }
            """, btn)
            print(f"  {i+1}: {attrs}")

        fm_page.close()

        # Test Instagram login page
        print("\n=== Testing Instagram Login ===")
        ig_page = context.new_page()
        ig_page.goto("https://www.instagram.com/accounts/login/")
        ig_page.wait_for_load_state("networkidle", timeout=10000)

        # Get all input elements
        inputs = ig_page.query_selector_all("input")
        print(f"Found {len(inputs)} input elements:")
        for i, inp in enumerate(inputs):
            attrs = ig_page.evaluate("""
                (el) => {
                    return {
                        type: el.type,
                        name: el.name,
                        placeholder: el.placeholder,
                        id: el.id,
                        className: el.className
                    };
                }
            """, inp)
            print(f"  {i+1}: {attrs}")

        # Get all button elements
        buttons = ig_page.query_selector_all("button")
        print(f"Found {len(buttons)} button elements:")
        for i, btn in enumerate(buttons):
            text = btn.inner_text().strip()
            attrs = ig_page.evaluate("""
                (el) => {
                    return {
                        type: el.type,
                        text: el.innerText.trim()
                    };
                }
            """, btn)
            print(f"  {i+1}: {attrs}")

        ig_page.close()
        browser.close()

if __name__ == "__main__":
    test_login_pages()