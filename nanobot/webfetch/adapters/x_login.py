#!/usr/bin/env python3
"""Interactive X/Twitter login — saves Playwright auth state for the X adapter.

Usage:
    uv run python -m nanobot.webfetch.adapters.x_login
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

AUTH_FILE = Path.home() / ".nanobot" / "x_auth.json"


def do_login(timeout_secs: int = 120) -> None:
    """Open browser for manual X login, auto-detect success, save auth state."""
    from playwright.sync_api import sync_playwright

    AUTH_FILE.parent.mkdir(parents=True, exist_ok=True)

    print(f"[x-login] Opening browser for X login...")
    print(f"[x-login] Please log in manually. Auto-detecting login (timeout: {timeout_secs}s)...")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(
            viewport={"width": 1280, "height": 900},
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/139.0.0.0 Safari/537.36"
            ),
        )
        page = context.new_page()
        page.goto("https://x.com/login", wait_until="domcontentloaded")

        start = time.time()
        logged_in = False
        while time.time() - start < timeout_secs:
            current_url = page.url
            if "/login" not in current_url and "/i/flow" not in current_url:
                page.wait_for_timeout(2000)
                logged_in = True
                break
            page.wait_for_timeout(1000)

        if not logged_in:
            print("[x-login] Timeout. Saving state anyway (may not work).")
        else:
            print(f"[x-login] Login detected! URL: {page.url}")

        context.storage_state(path=str(AUTH_FILE))
        print(f"[x-login] Auth state saved to {AUTH_FILE}")

        browser.close()


if __name__ == "__main__":
    do_login()
