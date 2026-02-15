"""
Ingestion scheduler and orchestrator.

Manages when each state's data source should be polled, tracks
the last successful ingestion for each state, and orchestrates
the full ingestion pipeline (fetch → normalize → store → log).
"""

import json
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from .config import (
    SourceTier, PollFrequency, IngestionSettings,
    get_all_source_configs, StateSourceConfig,
)
from .models import UCCDatabase, UCCFiling, IngestionRun
from .normalizer import normalize_filing
from .adapters.base import BaseAdapter
from .adapters.socrata import SocrataAdapter
from .adapters.state_bulk import StateBulkAdapter
from .adapters.commercial import CommercialProviderAdapter

logger = logging.getLogger(__name__)

# How often each frequency should poll (in hours)
FREQUENCY_HOURS = {
    PollFrequency.HOURLY: 1,
    PollFrequency.DAILY: 24,
    PollFrequency.WEEKLY: 168,
    PollFrequency.BIWEEKLY: 336,
    PollFrequency.MONTHLY: 720,
}


class IngestionScheduler:
    """Orchestrates the full ingestion pipeline across all states."""

    def __init__(self, settings: Optional[IngestionSettings] = None):
        self.settings = settings or IngestionSettings.from_env()
        self.db = UCCDatabase(self.settings.db_path)
        self.configs = get_all_source_configs()
        self.log_path = self.settings.log_path
        os.makedirs(os.path.dirname(self.log_path) or ".", exist_ok=True)

    def _get_adapter(self, config: StateSourceConfig) -> BaseAdapter:
        """Create the appropriate adapter for a state's source tier."""
        if config.tier == SourceTier.OPEN_API:
            return SocrataAdapter(config, self.settings)
        elif config.tier == SourceTier.STATE_BULK:
            return StateBulkAdapter(config, self.settings)
        elif config.tier == SourceTier.COMMERCIAL:
            return CommercialProviderAdapter(config, self.settings)
        else:
            raise ValueError(f"Unknown source tier: {config.tier}")

    def _should_run(self, state: str) -> bool:
        """Check if it's time to poll this state based on its frequency."""
        config = self.configs.get(state)
        if not config or not config.enabled:
            return False

        last_ingestion = self.db.get_latest_ingestion(state)
        if not last_ingestion:
            return True  # Never ingested — run now

        interval_hours = FREQUENCY_HOURS.get(config.poll_frequency, 24)
        try:
            last_dt = datetime.fromisoformat(last_ingestion.replace("Z", "+00:00"))
        except ValueError:
            return True

        next_run = last_dt + timedelta(hours=interval_hours)
        return datetime.now(timezone.utc) >= next_run

    def _log_event(self, event: dict):
        """Append an event to the ingestion log."""
        event["timestamp"] = datetime.now(timezone.utc).isoformat()
        with open(self.log_path, "a") as f:
            f.write(json.dumps(event) + "\n")

    def ingest_state(self, state: str, full_refresh: bool = False) -> dict:
        """Run the ingestion pipeline for a single state.

        Args:
            state: 2-letter state abbreviation.
            full_refresh: If True, ignore last ingestion date and pull everything.

        Returns:
            dict with run results (records_fetched, new, updated, skipped, etc.)
        """
        config = self.configs.get(state)
        if not config:
            return {"success": False, "error": f"No config for state {state}"}

        run_id = f"{state}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        run = IngestionRun(
            run_id=run_id,
            state=state,
            source_tier=config.tier.value,
            started_at=datetime.now(timezone.utc).isoformat(),
        )
        self.db.record_ingestion_run(run)

        self._log_event({
            "event": "ingestion_start",
            "state": state,
            "run_id": run_id,
            "tier": config.tier.value,
            "full_refresh": full_refresh,
        })

        try:
            adapter = self._get_adapter(config)

            # Determine the "since" date for incremental pulls
            since = None
            if not full_refresh:
                since = self.db.get_latest_filing_date(state)

            # Fetch, normalize, and store
            batch = []
            total_fetched = 0
            total_new = 0
            total_updated = 0
            total_skipped = 0

            for filing in adapter.fetch(since=since):
                normalized = normalize_filing(filing)
                batch.append(normalized)
                total_fetched += 1

                if len(batch) >= 1000:
                    counts = self.db.upsert_filings_batch(batch)
                    total_new += counts["new"]
                    total_updated += counts["updated"]
                    total_skipped += counts["skipped"]
                    batch = []

            # Flush remaining batch
            if batch:
                counts = self.db.upsert_filings_batch(batch)
                total_new += counts["new"]
                total_updated += counts["updated"]
                total_skipped += counts["skipped"]

            # Update run record
            run.completed_at = datetime.now(timezone.utc).isoformat()
            run.records_fetched = total_fetched
            run.records_new = total_new
            run.records_updated = total_updated
            run.records_skipped = total_skipped
            run.status = "completed"
            self.db.record_ingestion_run(run)

            self._log_event({
                "event": "ingestion_complete",
                "state": state,
                "run_id": run_id,
                "records_fetched": total_fetched,
                "records_new": total_new,
                "records_updated": total_updated,
                "records_skipped": total_skipped,
            })

            logger.info(
                "%s: ingestion complete. fetched=%d new=%d updated=%d skipped=%d",
                state, total_fetched, total_new, total_updated, total_skipped,
            )

            return {
                "success": True,
                "run_id": run_id,
                "state": state,
                "records_fetched": total_fetched,
                "records_new": total_new,
                "records_updated": total_updated,
                "records_skipped": total_skipped,
            }

        except Exception as e:
            run.completed_at = datetime.now(timezone.utc).isoformat()
            run.status = "failed"
            run.error_message = str(e)
            self.db.record_ingestion_run(run)

            self._log_event({
                "event": "ingestion_failed",
                "state": state,
                "run_id": run_id,
                "error": str(e),
            })

            logger.error("%s: ingestion failed: %s", state, e)
            return {"success": False, "run_id": run_id, "state": state, "error": str(e)}

    def run_due_states(self) -> list[dict]:
        """Run ingestion for all states that are due for a refresh.

        Returns:
            List of result dicts, one per state that was processed.
        """
        results = []
        due_states = [s for s in self.configs if self._should_run(s)]

        if not due_states:
            logger.info("No states are due for ingestion.")
            return results

        logger.info(
            "%d states due for ingestion: %s",
            len(due_states), ", ".join(due_states),
        )

        for state in sorted(due_states):
            result = self.ingest_state(state)
            results.append(result)

        return results

    def run_all(self, full_refresh: bool = False) -> list[dict]:
        """Run ingestion for ALL configured states regardless of schedule.

        Args:
            full_refresh: If True, pull all records (not just incremental).
        """
        results = []
        enabled_states = [s for s, c in self.configs.items() if c.enabled]

        logger.info("Running ingestion for all %d enabled states", len(enabled_states))

        for state in sorted(enabled_states):
            result = self.ingest_state(state, full_refresh=full_refresh)
            results.append(result)

        return results

    def run_tier(self, tier: SourceTier, full_refresh: bool = False) -> list[dict]:
        """Run ingestion for all states in a specific tier."""
        results = []
        tier_states = [s for s, c in self.configs.items() if c.tier == tier and c.enabled]

        logger.info("Running tier %s ingestion for %d states", tier.value, len(tier_states))

        for state in sorted(tier_states):
            result = self.ingest_state(state, full_refresh=full_refresh)
            results.append(result)

        return results

    def test_connections(self) -> dict:
        """Test connectivity to all configured data sources."""
        results = {}
        for state, config in sorted(self.configs.items()):
            if not config.enabled:
                results[state] = {"status": "disabled"}
                continue
            try:
                adapter = self._get_adapter(config)
                ok = adapter.test_connection()
                results[state] = {
                    "status": "ok" if ok else "failed",
                    "tier": config.tier.value,
                }
            except Exception as e:
                results[state] = {"status": "error", "error": str(e)}
        return results

    def get_status(self) -> dict:
        """Get current status of the ingestion pipeline."""
        db_stats = self.db.get_stats()
        recent_runs = self.db.get_ingestion_history(limit=50)

        # Calculate which states are overdue
        overdue = []
        for state in self.configs:
            if self._should_run(state):
                overdue.append(state)

        # Per-state status
        state_status = {}
        for state, config in self.configs.items():
            last = self.db.get_latest_ingestion(state)
            count = self.db.get_filing_count(state)
            state_status[state] = {
                "tier": config.tier.value,
                "frequency": config.poll_frequency.value,
                "last_ingestion": last,
                "filing_count": count,
                "due": state in overdue,
                "enabled": config.enabled,
            }

        return {
            "database": db_stats,
            "states": state_status,
            "overdue_states": overdue,
            "recent_runs": recent_runs[:10],
        }

    def close(self):
        self.db.close()
