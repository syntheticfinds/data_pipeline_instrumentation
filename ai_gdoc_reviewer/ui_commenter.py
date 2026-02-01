from dataclasses import dataclass
from typing import List, Optional, Set

from playwright.sync_api import sync_playwright, Page, TimeoutError as PlaywrightTimeoutError


@dataclass(frozen=True)
class UIComment:
    target_quote: str
    comment_text: str


def _open_doc(page: Page, doc_url: str) -> None:
    page.goto(doc_url, wait_until="domcontentloaded")
    page.wait_for_timeout(2500)


def _ensure_doc_ready(page: Page) -> None:
    page.wait_for_selector("text=File", timeout=30_000)
    page.wait_for_selector("text=Edit", timeout=30_000)
    page.wait_for_timeout(1000)


def _focus_doc_body(page: Page) -> None:
    # Click roughly in the document area to ensure keyboard shortcuts target the editor
    page.mouse.click(350, 350)
    page.wait_for_timeout(150)


def _open_find(page: Page) -> None:
    page.keyboard.press("Meta+F")
    page.wait_for_timeout(150)


def _find_quote(page: Page, quote: str) -> None:
    _open_find(page)
    page.keyboard.type(quote, delay=5)
    page.wait_for_timeout(200)
    page.keyboard.press("Enter")
    page.wait_for_timeout(350)


def _close_find(page: Page) -> None:
    page.keyboard.press("Escape")
    page.wait_for_timeout(100)


def _open_comment_box(page: Page) -> None:
    # Google Docs comment shortcut on Mac
    page.keyboard.press("Meta+Alt+M")


def _wait_for_comment_box(page: Page) -> None:
    # Comment input is role=textbox
    page.wait_for_selector('[role="textbox"]', timeout=10_000)


def _type_and_submit_comment(page: Page, comment_text: str) -> None:
    textboxes = page.locator('[role="textbox"]')
    n = textboxes.count()
    if n == 0:
        raise RuntimeError("No textbox found for comment input.")

    # last textbox tends to be the comment editor
    box = textboxes.nth(n - 1)
    box.click()
    page.keyboard.type(comment_text, delay=5)

    # Submit comment (Cmd+Enter)
    page.keyboard.press("Meta+Enter")
    page.wait_for_timeout(800)


def add_anchored_comments_headful(
    doc_url: str,
    comments: List[UIComment],
    user_data_dir: str = ".pw_google_profile",
    slow_mo_ms: int = 50,
    max_comments: Optional[int] = None,
    retries: int = 2,
) -> None:
    """
    Headful, persistent-auth Playwright comment injector.
    """
    seen: Set[str] = set()

    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=user_data_dir,
            headless=False,
            slow_mo=slow_mo_ms,
            channel="chrome",
            args=[
                "--disable-blink-features=AutomationControlled",
                "--start-maximized",
            ],
        )
        page = ctx.new_page()

        print(f"🌐 Opening doc: {doc_url}")
        _open_doc(page, doc_url)
        _ensure_doc_ready(page)
        _focus_doc_body(page)

        posted = 0

        for i, c in enumerate(comments, start=1):
            if max_comments is not None and posted >= max_comments:
                break

            quote = c.target_quote.strip()
            if not quote:
                continue

            # Dedupe exact quotes (prevents repeated comments on same sentence)
            if quote in seen:
                continue
            seen.add(quote)

            print(f"\n[{i}/{len(comments)}] Quote:\n  {quote}")

            ok = False
            last_err = None

            for attempt in range(1, retries + 1):
                try:
                    _focus_doc_body(page)

                    # Find quote (highlights match)
                    _find_quote(page, quote)
                    _close_find(page)

                    # Open comment box and post
                    _open_comment_box(page)
                    _wait_for_comment_box(page)
                    _type_and_submit_comment(page, c.comment_text)

                    print("✅ Posted")
                    posted += 1
                    ok = True
                    break
                except PlaywrightTimeoutError as e:
                    last_err = e
                    print(f"⚠️ Timeout attempt {attempt}/{retries}. Retrying...")
                except Exception as e:
                    last_err = e
                    print(f"⚠️ Error attempt {attempt}/{retries}: {e}. Retrying...")

            if not ok:
                print("❌ Failed to post comment for quote.")
                print("   Last error:", last_err)

        print(f"\n🎉 Done. Posted {posted} comments.")
        ctx.close()
