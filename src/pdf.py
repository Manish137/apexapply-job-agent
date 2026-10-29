"""
HTML to PDF rendering via headless Chromium (Playwright).
"""

from pathlib import Path


def html_to_pdf(html: str, out_path: Path) -> Path:
    from playwright.sync_api import sync_playwright

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=str(out_path), format="Letter", print_background=True,
                     margin={"top": "0.8in", "bottom": "0.8in", "left": "0.9in", "right": "0.9in"})
        finally:
            browser.close()
    return out_path
