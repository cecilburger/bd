"""
Phase 1 — Scrape brand names + categories from FastMoss.
Output: brands_raw.csv
"""
import argparse
import csv
import logging

from playwright.sync_api import sync_playwright

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)


def login_fastmoss(page):
    """Automatically log in to FastMoss."""
    try:
        log.info("Logging in to FastMoss...")
        # Wait for login form to appear
        page.wait_for_selector("input[type='email'], input[name='email'], input[placeholder*='email']", timeout=10000)

        # Fill email
        email_selectors = ["input[type='email']", "input[name='email']", "input[placeholder*='email']"]
        for selector in email_selectors:
            try:
                page.fill(selector, "creative.mcnasia@gmail.com")
                break
            except:
                continue

        # Fill password
        password_selectors = ["input[type='password']", "input[name='password']", "input[placeholder*='password']"]
        for selector in password_selectors:
            try:
                page.fill(selector, "Mcnasia2000")
                break
            except:
                continue

        # Click login button
        login_selectors = ["button[type='submit']", "button:has-text('Login')", "button:has-text('Masuk')", "input[type='submit']"]
        for selector in login_selectors:
            try:
                page.click(selector)
                break
            except:
                continue

        # Wait for login to complete
        page.wait_for_timeout(3000)
        log.info("FastMoss login completed")

    except Exception as e:
        log.warning(f"FastMoss login failed: {e}")


def scrape(max_pages: int | None = None, output_file: str = "brands_raw.csv"):
    brands = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        log.info("Opening FastMoss...")
        page.goto("https://www.fastmoss.com/id/shop-marketing/search?region=ID")
        login_fastmoss(page)

        current_page = 1

        while True:
            if max_pages and current_page > max_pages:
                log.info(f"Reached max page limit ({max_pages})")
                break

            log.info(f"--- Page {current_page} ---")

            try:
                page.wait_for_selector("tbody.ant-table-tbody tr.ant-table-row", timeout=15000)
            except Exception:
                log.warning("Table not found, stopping.")
                break

            rows = page.query_selector_all("tbody.ant-table-tbody tr.ant-table-row")
            for row in rows:
                name_el = row.query_selector("h3.content.truncate")
                brand_name = name_el.inner_text().strip() if name_el else ""

                cat_el = row.query_selector("div.custom-tag-container span.text-ellipsis")
                category = cat_el.inner_text().strip() if cat_el else ""

                if brand_name:
                    brands.append({"brand_name": brand_name, "category": category})
                    log.info(f"  {brand_name} | {category}")

            next_btn = page.query_selector("li.ant-pagination-next:not([aria-disabled='true']) button")
            if not next_btn:
                log.info("No more pages.")
                break

            next_btn.click()
            try:
                page.wait_for_selector("tbody.ant-table-tbody tr.ant-table-row", timeout=15000)
            except Exception:
                log.warning("Next page failed to load, stopping.")
                break

            current_page += 1

        browser.close()

    if not brands:
        log.warning("No brands scraped.")
        return

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["brand_name", "category"])
        writer.writeheader()
        writer.writerows(brands)

    log.info(f"Done. {len(brands)} brands saved to {output_file}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Phase 1 — FastMoss brand scraper")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--output", type=str, default="brands_raw.csv")
    args = parser.parse_args()
    scrape(max_pages=args.max_pages, output_file=args.output)
