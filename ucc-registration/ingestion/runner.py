"""
CLI runner for the UCC filing ingestion pipeline.

Usage:
    python -m ingestion.runner status          Show pipeline status
    python -m ingestion.runner run             Run all due states
    python -m ingestion.runner run --all       Run all states (ignore schedule)
    python -m ingestion.runner run --state CT  Run a specific state
    python -m ingestion.runner run --tier open_api   Run all states in a tier
    python -m ingestion.runner run --full      Full refresh (not incremental)
    python -m ingestion.runner test            Test all data source connections
    python -m ingestion.runner costs           Show annual cost breakdown
    python -m ingestion.runner stats           Show database statistics
"""

import argparse
import json
import logging
import sys

from .config import SourceTier, get_annual_cost_breakdown, get_all_source_configs
from .scheduler import IngestionScheduler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


def cmd_status(scheduler: IngestionScheduler):
    """Display current pipeline status."""
    status = scheduler.get_status()

    print("\n=== UCC Ingestion Pipeline Status ===\n")

    db = status["database"]
    print(f"Total filings in database: {db['total_filings']:,}")
    print(f"States with data: {db['states_covered']}")
    if db["earliest_filing"]:
        print(f"Date range: {db['earliest_filing']} to {db['latest_filing']}")

    if db.get("by_source_tier"):
        print("\nBy source tier:")
        for tier, count in db["by_source_tier"].items():
            print(f"  {tier}: {count:,}")

    overdue = status["overdue_states"]
    if overdue:
        print(f"\nOverdue states ({len(overdue)}): {', '.join(sorted(overdue))}")
    else:
        print("\nAll states are up to date.")

    print("\nPer-state status:")
    print(f"  {'State':<6} {'Tier':<12} {'Freq':<10} {'Count':>10} {'Last Ingestion':<25} {'Due'}")
    print("  " + "-" * 80)
    for state, info in sorted(status["states"].items()):
        due_marker = "** DUE **" if info["due"] else ""
        last = info["last_ingestion"] or "never"
        if not info["enabled"]:
            due_marker = "(disabled)"
        print(
            f"  {state:<6} {info['tier']:<12} {info['frequency']:<10} "
            f"{info['filing_count']:>10,} {last:<25} {due_marker}"
        )

    if status.get("recent_runs"):
        print("\nRecent ingestion runs:")
        for run in status["recent_runs"][:5]:
            print(
                f"  {run['state']} {run['started_at'][:19]} "
                f"status={run['status']} fetched={run['records_fetched']} "
                f"new={run['records_new']}"
            )


def cmd_run(scheduler: IngestionScheduler, args):
    """Run the ingestion pipeline."""
    if args.state:
        state = args.state.upper()
        print(f"\nRunning ingestion for {state}...")
        result = scheduler.ingest_state(state, full_refresh=args.full)
        _print_result(result)

    elif args.tier:
        tier_map = {
            "open_api": SourceTier.OPEN_API,
            "state_bulk": SourceTier.STATE_BULK,
            "commercial": SourceTier.COMMERCIAL,
        }
        tier = tier_map.get(args.tier)
        if not tier:
            print(f"Unknown tier: {args.tier}. Use: open_api, state_bulk, commercial")
            return
        print(f"\nRunning tier {args.tier} ingestion...")
        results = scheduler.run_tier(tier, full_refresh=args.full)
        _print_results(results)

    elif args.all:
        print("\nRunning ingestion for ALL states...")
        results = scheduler.run_all(full_refresh=args.full)
        _print_results(results)

    else:
        print("\nRunning ingestion for due states...")
        results = scheduler.run_due_states()
        if not results:
            print("No states are due for ingestion. Use --all to force.")
        else:
            _print_results(results)


def cmd_test(scheduler: IngestionScheduler):
    """Test all data source connections."""
    print("\n=== Testing Data Source Connections ===\n")
    results = scheduler.test_connections()

    ok_count = sum(1 for r in results.values() if r["status"] == "ok")
    fail_count = sum(1 for r in results.values() if r["status"] in ("failed", "error"))
    disabled_count = sum(1 for r in results.values() if r["status"] == "disabled")

    for state, result in sorted(results.items()):
        status = result["status"]
        tier = result.get("tier", "")
        error = result.get("error", "")
        marker = {"ok": "[OK]", "failed": "[FAIL]", "error": "[ERR]", "disabled": "[--]"}.get(status, "[??]")
        line = f"  {marker} {state} ({tier})"
        if error:
            line += f" - {error}"
        print(line)

    print(f"\nSummary: {ok_count} ok, {fail_count} failed, {disabled_count} disabled")


def cmd_costs():
    """Display annual cost breakdown."""
    breakdown = get_annual_cost_breakdown()

    print("\n=== Annual Cost Breakdown ===\n")

    tier1 = breakdown["tier1_open_api"]
    print(f"Tier 1 - Open APIs ({tier1['count']} states): ${tier1['annual_cost']:,.0f}/year")
    print(f"  States: {', '.join(tier1['states'])}")

    tier2 = breakdown["tier2_state_bulk"]
    print(f"\nTier 2 - State Bulk Subscriptions ({tier2['count']} states): ${tier2['annual_cost']:,.0f}/year")
    print(f"  States: {', '.join(tier2['states'])}")

    # Per-state costs for Tier 2
    configs = get_all_source_configs()
    print("  Per-state breakdown:")
    for state in sorted(tier2["states"]):
        config = configs.get(state)
        if config:
            print(f"    {state} ({config.state}): ${config.annual_cost_usd:,.0f}/year — {config.notes[:60]}")

    tier3 = breakdown["tier3_commercial"]
    print(f"\nTier 3 - Commercial Provider ({tier3['count']} states): ~${tier3['annual_cost_estimated']:,.0f}/year (estimated)")
    print(f"  States: {', '.join(tier3['states'])}")

    total = breakdown["total_estimated_annual"]
    print(f"\n{'='*50}")
    print(f"TOTAL ESTIMATED ANNUAL COST: ${total:,.0f}")
    print(f"Budget remaining (of $1,000,000): ${1_000_000 - total:,.0f}")


def cmd_stats(scheduler: IngestionScheduler):
    """Display database statistics."""
    stats = scheduler.db.get_stats()
    print("\n=== Database Statistics ===\n")
    print(f"Total filings: {stats['total_filings']:,}")
    print(f"States covered: {stats['states_covered']}")
    if stats["earliest_filing"]:
        print(f"Date range: {stats['earliest_filing']} to {stats['latest_filing']}")

    if stats["by_status"]:
        print("\nBy status:")
        for status, count in sorted(stats["by_status"].items(), key=lambda x: -x[1]):
            print(f"  {status}: {count:,}")

    if stats["by_source_tier"]:
        print("\nBy source tier:")
        for tier, count in sorted(stats["by_source_tier"].items(), key=lambda x: -x[1]):
            print(f"  {tier}: {count:,}")

    if stats["by_state"]:
        print("\nTop 10 states by filing count:")
        for i, (state, count) in enumerate(list(stats["by_state"].items())[:10]):
            print(f"  {state}: {count:,}")


def _print_result(result: dict):
    """Print a single ingestion result."""
    if result.get("success"):
        print(
            f"  {result['state']}: OK — "
            f"fetched={result['records_fetched']:,} "
            f"new={result['records_new']:,} "
            f"updated={result['records_updated']:,} "
            f"skipped={result['records_skipped']:,}"
        )
    else:
        print(f"  {result.get('state', '??')}: FAILED — {result.get('error', 'unknown error')}")


def _print_results(results: list[dict]):
    """Print a batch of ingestion results."""
    successes = [r for r in results if r.get("success")]
    failures = [r for r in results if not r.get("success")]

    print(f"\nResults: {len(successes)} succeeded, {len(failures)} failed\n")
    for result in results:
        _print_result(result)

    if successes:
        total_new = sum(r.get("records_new", 0) for r in successes)
        total_fetched = sum(r.get("records_fetched", 0) for r in successes)
        print(f"\nTotals: {total_fetched:,} fetched, {total_new:,} new records")


def main():
    parser = argparse.ArgumentParser(
        description="UCC Filing Ingestion Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # status
    subparsers.add_parser("status", help="Show pipeline status")

    # run
    run_parser = subparsers.add_parser("run", help="Run ingestion")
    run_parser.add_argument("--state", help="Run a specific state (e.g., CT)")
    run_parser.add_argument("--tier", help="Run a specific tier (open_api, state_bulk, commercial)")
    run_parser.add_argument("--all", action="store_true", help="Run all states regardless of schedule")
    run_parser.add_argument("--full", action="store_true", help="Full refresh (not incremental)")

    # test
    subparsers.add_parser("test", help="Test all data source connections")

    # costs
    subparsers.add_parser("costs", help="Show annual cost breakdown")

    # stats
    subparsers.add_parser("stats", help="Show database statistics")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    if args.command == "costs":
        cmd_costs()
        return

    scheduler = IngestionScheduler()
    try:
        if args.command == "status":
            cmd_status(scheduler)
        elif args.command == "run":
            cmd_run(scheduler, args)
        elif args.command == "test":
            cmd_test(scheduler)
        elif args.command == "stats":
            cmd_stats(scheduler)
    finally:
        scheduler.close()


if __name__ == "__main__":
    main()
