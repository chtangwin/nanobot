#!/usr/bin/env python3
"""CLI thin wrapper over nanobot.webfetch core pipeline.

Usage examples:
  uv run python tests/webfetch/run_web_fetch.py "https://example.com"
  uv run python tests/webfetch/run_web_fetch.py "https://example.com" --json
  uv run python tests/webfetch/run_web_fetch.py "https://airank.dev" --mode discovery --json
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Add project root to path (script is in tests/webfetch/)
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from nanobot.webfetch.core.models import FetchConfig
from nanobot.webfetch.core.pipeline import robust_fetch


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Robust fast web fetch (HTTP first, Playwright fallback)"
    )
    parser.add_argument("url", help="Target URL")
    parser.add_argument("--json", action="store_true", help="Print JSON result")
    parser.add_argument("--save-text", help="Save extracted text to file")
    parser.add_argument("--min-text", type=int, default=300, help="Minimum extracted text chars")
    parser.add_argument("--browser-timeout", type=float, default=20.0, help="Playwright goto timeout seconds")
    parser.add_argument("--browser-wait-ms", type=int, default=1200, help="Extra wait after DOM content loaded")
    parser.add_argument("--force-browser", action="store_true", help="Skip HTTP fast path and use browser directly")
    parser.add_argument(
        "--mode",
        choices=["snapshot", "discovery"],
        default="snapshot",
        help="snapshot=visible page only; discovery=attempt generic pagination/load-more/scroll expansion",
    )
    return parser.parse_args(argv)


async def _main_async(args: argparse.Namespace) -> int:
    cfg = FetchConfig(
        min_text_chars=args.min_text,
        browser_timeout_s=args.browser_timeout,
        browser_post_wait_ms=args.browser_wait_ms,
    )
    result = await robust_fetch(
        args.url,
        cfg,
        force_browser=args.force_browser,
        discovery_mode=(args.mode == "discovery"),
    )

    if args.save_text:
        with open(args.save_text, "w", encoding="utf-8") as f:
            f.write(result.content)

    if args.json:
        print(json.dumps(result.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(f"ok={result.ok} tier={result.source_tier} extractor={result.extractor} final_url={result.final_url}")
        if result.discovery_actions:
            print(f"discovery_actions={len(result.discovery_actions)}")
        if result.discovered_items:
            print(f"discovered_items={result.discovered_items}")
        if result.error:
            print(f"error={result.error}")
        if result.title:
            print(f"title={result.title}")
        if result.content:
            print("\n" + result.content)

    return 0 if result.ok else 2


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = parse_args(argv or sys.argv[1:])
    return asyncio.run(_main_async(args))


if __name__ == "__main__":
    raise SystemExit(main())
