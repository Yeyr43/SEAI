import sys, json
from playwright.sync_api import sync_playwright

def run(action, url=None, selector=None):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        if action == "navigate": page.goto(url); return page.title()
        elif action == "click": page.goto(url); page.click(selector); return "clicked"
        elif action == "screenshot": page.goto(url); page.screenshot(path="screenshot.png"); return "screenshot saved"
        elif action == "get_text": page.goto(url); return page.inner_text(selector or "body")
        browser.close()

if __name__ == "__main__":
    args = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
    print(run(args.get("action"), args.get("url"), args.get("selector")))