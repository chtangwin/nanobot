#!/usr/bin/env python3
"""Benchmark runner for webfetch.

Runs all defined benchmark URLs and generates a report with:
- Success rate
- Latency metrics
- Field completeness
- Action traces

Usage:
    # Run from project root
    uv run python tests/webfetch/run_benchmarks.py

    # With JSON output
    uv run python tests/webfetch/run_benchmarks.py --output report.json

    # Quiet mode (summary only)
    uv run python tests/webfetch/run_benchmarks.py --quiet

NOTE: This script is NOT collected by pytest (name doesn't match test_*.py pattern).
Run it directly to generate benchmark reports.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path

# Add project root to path (script is in tests/webfetch/)
import sys
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from nanobot.webfetch.core.models import FetchConfig
from nanobot.webfetch.core.pipeline import robust_fetch
from tests.webfetch.conftest import BENCHMARKS


@dataclass
class BenchmarkResult:
    """Result for a single benchmark URL."""

    key: str
    url: str
    description: str
    expect_tier: str

    # Results
    ok: bool
    actual_tier: str
    duration_ms: float

    # Content metrics
    content_length: int
    discovered_items: int
    discovery_actions_count: int

    # Field completeness
    has_title: bool
    has_error: bool
    error_message: str | None

    # Raw result for debugging
    raw: dict


async def run_benchmark(key: str, spec: dict) -> BenchmarkResult:
    """Run a single benchmark."""
    url = spec["url"]
    description = spec["description"]
    expect_tier = spec["expect_tier"]

    print(f"\n[{key}] {url}")
    print(f"  {description}")

    cfg = FetchConfig(
        http_read_timeout_s=20.0,
        browser_timeout_s=30.0,
        browser_post_wait_ms=2000,
    )

    start = time.time()
    result = await robust_fetch(url, cfg)
    duration_ms = (time.time() - start) * 1000

    print(f"  ok={result.ok} tier={result.source_tier} duration={duration_ms:.0f}ms")
    print(f"  items={result.discovered_items} actions={len(result.discovery_actions)}")

    return BenchmarkResult(
        key=key,
        url=url,
        description=description,
        expect_tier=expect_tier,
        ok=result.ok,
        actual_tier=result.source_tier,
        duration_ms=duration_ms,
        content_length=len(result.content),
        discovered_items=result.discovered_items,
        discovery_actions_count=len(result.discovery_actions),
        has_title=bool(result.title),
        has_error=bool(result.error),
        error_message=result.error,
        raw=result.to_dict(),
    )


async def run_all_benchmarks() -> dict[str, BenchmarkResult]:
    """Run all benchmarks and return results."""
    results = {}

    for key, spec in BENCHMARKS.items():
        try:
            result = await run_benchmark(key, spec)
            results[key] = result
        except Exception as e:
            print(f"  ERROR: {e}")
            # Create a failed result
            results[key] = BenchmarkResult(
                key=key,
                url=spec["url"],
                description=spec["description"],
                expect_tier=spec["expect_tier"],
                ok=False,
                actual_tier="error",
                duration_ms=0,
                content_length=0,
                discovered_items=0,
                discovery_actions_count=0,
                has_title=False,
                has_error=True,
                error_message=str(e),
                raw={},
            )

    return results


def generate_report(results: dict[str, BenchmarkResult]) -> dict:
    """Generate summary report."""
    total = len(results)
    success = sum(1 for r in results.values() if r.ok)
    success_rate = success / total if total > 0 else 0

    # Tier distribution
    tier_counts: dict[str, int] = {}
    for r in results.values():
        tier = r.actual_tier
        tier_counts[tier] = tier_counts.get(tier, 0) + 1

    # Latency stats
    durations = [r.duration_ms for r in results.values() if r.ok]
    avg_duration = sum(durations) / len(durations) if durations else 0
    max_duration = max(durations) if durations else 0
    min_duration = min(durations) if durations else 0

    # Field completeness
    with_title = sum(1 for r in results.values() if r.has_title)
    without_error = sum(1 for r in results.values() if not r.has_error)

    return {
        "timestamp": datetime.now().isoformat(),
        "summary": {
            "total": total,
            "success": success,
            "success_rate": success_rate,
            "tier_distribution": tier_counts,
        },
        "latency": {
            "avg_ms": avg_duration,
            "min_ms": min_duration,
            "max_ms": max_duration,
        },
        "completeness": {
            "with_title": with_title,
            "without_error": without_error,
        },
        "benchmarks": {k: asdict(v) for k, v in results.items()},
    }


def print_report(report: dict):
    """Print human-readable report."""
    print("\n" + "=" * 70)
    print("WEBFETCH BENCHMARK REPORT")
    print("=" * 70)

    summary = report["summary"]
    print(f"\nSuccess Rate: {summary['success']}/{summary['total']} ({summary['success_rate']:.1%})")

    print("\nTier Distribution:")
    for tier, count in summary["tier_distribution"].items():
        print(f"  {tier}: {count}")

    latency = report["latency"]
    print(f"\nLatency (successful runs):")
    print(f"  Average: {latency['avg_ms']:.0f}ms")
    print(f"  Min: {latency['min_ms']:.0f}ms")
    print(f"  Max: {latency['max_ms']:.0f}ms")

    completeness = report["completeness"]
    print(f"\nField Completeness:")
    print(f"  With title: {completeness['with_title']}/{summary['total']}")
    print(f"  Without error: {completeness['without_error']}/{summary['total']}")

    print("\nPer-Benchmark Results:")
    for key, bm in report["benchmarks"].items():
        status = "PASS" if bm["ok"] else "FAIL"
        print(f"  [{status}] {key}: {bm['actual_tier']} ({bm['duration_ms']:.0f}ms)")
        if not bm["ok"]:
            print(f"      Error: {bm['error_message']}")


async def main():
    parser = argparse.ArgumentParser(description="Run webfetch benchmarks")
    parser.add_argument("--output", "-o", help="Output JSON file path")
    parser.add_argument("--quiet", "-q", action="store_true", help="Only print summary")
    args = parser.parse_args()

    print("=" * 70)
    print("WEBFETCH BENCHMARK RUNNER")
    print("=" * 70)
    print(f"Started at: {datetime.now().isoformat()}")

    results = await run_all_benchmarks()
    report = generate_report(results)

    if not args.quiet:
        print_report(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to: {output_path}")

    # Exit with error code if any benchmark failed
    failed = sum(1 for r in results.values() if not r.ok)
    if failed > 0:
        print(f"\n{failed} benchmark(s) failed!")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
