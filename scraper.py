from playwright.sync_api import sync_playwright
import csv
import time
import re

def clean_phone(raw):
    """Remove all non-digit characters, normalize leading 0 -> 62"""
    digits = re.sub(r"\D", "", raw)
    if digits.startswith("0"):
        digits = "62" + digits[1:]
    return digits

def scrape_contact(page, detail_url):
    """Open shop detail page and extract phone + email."""
    phone, email = "", ""
    try:
        page.goto(detail_url, wait_until="domcontentloaded", timeout=15000)
        page.wait_for_timeout(2000)

        content = page.content()

        # Email
        email_match = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", content)
        if email_match:
            email = email_match.group(0)

        # Phone — look for Indonesian numbers
        phone_match = re.search(r"(\+?62[\s\-]?\d[\d\s\-]{7,14}|0\d[\d\s\-]{7,14})", content)
        if phone_match:
            phone = clean_phone(phone_match.group(0))

        # Also try visible text on page
        if not phone or not email:
            try:
                contact_section = page.query_selector_all("[class*='contact'], [class*='Contact'], [class*='info'], [class*='Info']")
                for el in contact_section:
                    text = el.inner_text()
                    if not email:
                        em = re.search(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}", text)
                        if em:
                            email = em.group(0)
                    if not phone:
                        ph = re.search(r"(\+?62[\s\-]?\d[\d\s\-]{7,14}|0\d[\d\s\-]{7,14})", text)
                        if ph:
                            phone = clean_phone(ph.group(0))
            except Exception:
                pass

    except Exception as e:
        print(f"  Error fetching contact: {e}")

    return phone, email


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
                # Wait for the actual table rows with shop data
                list_page.wait_for_selector("tbody.ant-table-tbody tr.ant-table-row", timeout=15000)
            except Exception:
                print("Brand elements not found, stopping.")
                break

            rows = list_page.query_selector_all("tbody.ant-table-tbody tr.ant-table-row")

            for i, row in enumerate(rows):
                # Brand name
                name_el = row.query_selector("h3.content.truncate")
                brand_name = name_el.get_attribute("text") or name_el.inner_text().strip() if name_el else ""

                # Category - inside custom-tag-container
                cat_el = row.query_selector("div.custom-tag-container span.text-ellipsis")
                category = cat_el.inner_text().strip() if cat_el else ""

                if not brand_name:
                    continue

                print(f"  [{i+1}] {brand_name} | {category}")

                # Get detail page URL from the row link
                link_el = row.query_selector("a[href*='/shop-marketing/detail/']")
                detail_url = ""
                if link_el:
                    href = link_el.get_attribute("href")
                    if href:
                        detail_url = href if href.startswith("http") else "https://www.fastmoss.com" + href

                phone, email = "", ""
                if detail_url:
                    phone, email = scrape_contact(detail_page, detail_url)
                    print(f"     Phone: {phone or '-'} | Email: {email or '-'}")
                    # Go back to list page context
                    list_page.bring_to_front()

                results.append({
                    "brand_name": brand_name,
                    "category": category,
                    "phone": phone,
                    "email": email,
                })

                time.sleep(1)

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
        writer = csv.DictWriter(f, fieldnames=["brand_name", "category", "phone", "email"])
        writer.writeheader()
        writer.writerows(results)

    print(f"\nDone. {len(results)} brands saved to {output_file}")


if __name__ == "__main__":
    # Set max_pages=10 to test first, None = all 500 pages
    scrape(max_pages=10, output_file="brands.csv")
