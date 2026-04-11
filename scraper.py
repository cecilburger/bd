from playwright.sync_api import sync_playwright
import csv
import time
import re

def clean_phone(raw):
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits

def extract_contact_from_page(page):
    """Extract phone and email from current page content."""
    phone, email = "", ""
    try:
        content = page.inner_text("body")

        email_match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", content)
        if email_match:
            email = email_match.group(0)

        phone_match = re.search(r"(\+?62[\s\-]?\d[\d\s\-]{7,14}|0\d[\d\s\-]{7,14})", content)
        if phone_match:
            phone = clean_phone(phone_match.group(0))
    except Exception:
        pass
    return phone, email

def search_and_extract(detail_page, brand_name, platform):
    """Search Yahoo for brand+platform, visit first result, extract contact."""
    phone, email, profile_url = "", "", ""
    query = f"{brand_name} {platform}"
    yahoo_url = f"https://search.yahoo.com/search?p={query.replace(' ', '+')}"

    try:
        detail_page.goto(yahoo_url, wait_until="domcontentloaded", timeout=15000)
        detail_page.wait_for_timeout(2000)

        # Get first organic result link
        result_links = detail_page.query_selector_all("div#web ol li h3 a, div.algo h3 a, div.dd.algo h3 a")
        target_url = ""
        for link in result_links:
            href = link.get_attribute("href") or ""
            if platform.lower() in href.lower():
                target_url = href
                break

        # Fallback: grab any link containing platform domain
        if not target_url:
            all_links = detail_page.query_selector_all("a[href]")
            for link in all_links:
                href = link.get_attribute("href") or ""
                if platform.lower() + ".com" in href.lower() and "yahoo" not in href.lower():
                    target_url = href
                    break

        if target_url:
            profile_url = target_url
            print(f"    [{platform}] Found: {target_url[:80]}")
            detail_page.goto(target_url, wait_until="domcontentloaded", timeout=15000)
            detail_page.wait_for_timeout(3000)
            phone, email = extract_contact_from_page(detail_page)
        else:
            print(f"    [{platform}] No result found")

    except Exception as e:
        print(f"    [{platform}] Error: {e}")

    return phone, email, profile_url


def scrape(max_pages=None, output_file="brands.csv"):
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        list_page = context.new_page()
        detail_page = context.new_page()

        print("Opening FastMoss...")
        list_page.goto("https://www.fastmoss.com/id/shop-marketing/search?region=ID")

        input("\n>>> Log in manually in the browser, then press Enter to start scraping...\n")

        current_page = 1

        while True:
            if max_pages and current_page > max_pages:
                print(f"Reached max page limit ({max_pages})")
                break

            print(f"\n--- Page {current_page} ---")

            try:
                list_page.wait_for_selector("tbody.ant-table-tbody tr.ant-table-row", timeout=15000)
            except Exception:
                print("Table not found, stopping.")
                break

            rows = list_page.query_selector_all("tbody.ant-table-tbody tr.ant-table-row")

            for i, row in enumerate(rows):
                # Brand name
                name_el = row.query_selector("h3.content.truncate")
                brand_name = name_el.get_attribute("text") or name_el.inner_text().strip() if name_el else ""

                # Category
                cat_el = row.query_selector("div.custom-tag-container span.text-ellipsis")
                category = cat_el.inner_text().strip() if cat_el else ""

                if not brand_name:
                    continue

                print(f"  [{i+1}] {brand_name} | {category}")

                # Search Facebook
                fb_phone, fb_email, fb_url = search_and_extract(detail_page, brand_name, "facebook")
                time.sleep(1)

                # Search Instagram
                ig_phone, ig_email, ig_url = search_and_extract(detail_page, brand_name, "instagram")
                time.sleep(1)

                results.append({
                    "brand_name": brand_name,
                    "category": category,
                    "fb_url": fb_url,
                    "fb_phone": fb_phone,
                    "fb_email": fb_email,
                    "ig_url": ig_url,
                    "ig_phone": ig_phone,
                    "ig_email": ig_email,
                })

                # Bring list page back to front
                list_page.bring_to_front()

            # Next page
            next_btn = list_page.query_selector("li.ant-pagination-next:not([aria-disabled='true']) button")
            if not next_btn:
                print("No more pages.")
                break

            next_btn.click()
            list_page.wait_for_timeout(2500)
            current_page += 1

        browser.close()

    if not results:
        print("Nothing scraped.")
        return

    with open(output_file, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=[
            "brand_name", "category",
            "fb_url", "fb_phone", "fb_email",
            "ig_url", "ig_phone", "ig_email",
        ])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nDone. {len(results)} brands saved to {output_file}")


if __name__ == "__main__":
    # Set max_pages=2 to test first, None = all 500 pages
    scrape(max_pages=2, output_file="brands.csv")
