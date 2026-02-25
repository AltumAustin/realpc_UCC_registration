"""
Data models for UCC filings and the SQLite storage layer.

Schema designed to accommodate the union of fields across all state formats
(Socrata JSON, state CSV/XML/tab-delimited, commercial provider JSON).
"""

import json
import logging
import os
import sqlite3
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class UCCFiling:
    """Normalized UCC filing record. Common schema across all sources."""
    # Identity
    filing_number: str
    state: str  # 2-letter abbreviation

    # Filing details
    filing_type: str  # UCC-1, UCC-3, UCC-5, etc.
    filing_date: Optional[str] = None  # ISO 8601
    lapse_date: Optional[str] = None
    filing_status: Optional[str] = None  # active, lapsed, terminated

    # Debtor information
    debtor_name: Optional[str] = None
    debtor_address: Optional[str] = None
    debtor_city: Optional[str] = None
    debtor_state: Optional[str] = None
    debtor_zip: Optional[str] = None
    debtor_organization: Optional[str] = None
    debtor_type: Optional[str] = None  # individual, organization

    # Secured party information
    secured_party_name: Optional[str] = None
    secured_party_address: Optional[str] = None
    secured_party_city: Optional[str] = None
    secured_party_state: Optional[str] = None
    secured_party_zip: Optional[str] = None

    # Collateral
    collateral_description: Optional[str] = None

    # Related filings
    original_filing_number: Optional[str] = None  # For amendments/continuations
    amendment_type: Optional[str] = None  # assignment, amendment, continuation, termination

    # Metadata
    source_tier: Optional[str] = None  # open_api, state_bulk, commercial
    source_raw: Optional[str] = None  # JSON blob of the original record
    ingested_at: Optional[str] = None  # When we ingested it
    last_updated_at: Optional[str] = None


@dataclass
class IngestionRun:
    """Tracks each ingestion run for audit and debugging."""
    run_id: str
    state: str
    source_tier: str
    started_at: str
    completed_at: Optional[str] = None
    records_fetched: int = 0
    records_new: int = 0
    records_updated: int = 0
    records_skipped: int = 0
    status: str = "running"  # running, completed, failed
    error_message: Optional[str] = None


class UCCDatabase:
    """SQLite-backed storage for UCC filings.

    SQLite handles the expected volume (~145K records/month nationwide)
    comfortably. Schema is designed to be migratable to PostgreSQL
    if volume or concurrency demands increase.
    """

    SCHEMA_VERSION = 1

    DDL = """
    CREATE TABLE IF NOT EXISTS ucc_filings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        filing_number TEXT NOT NULL,
        state TEXT NOT NULL,
        filing_type TEXT,
        filing_date TEXT,
        lapse_date TEXT,
        filing_status TEXT,
        debtor_name TEXT,
        debtor_address TEXT,
        debtor_city TEXT,
        debtor_state TEXT,
        debtor_zip TEXT,
        debtor_organization TEXT,
        debtor_type TEXT,
        secured_party_name TEXT,
        secured_party_address TEXT,
        secured_party_city TEXT,
        secured_party_state TEXT,
        secured_party_zip TEXT,
        collateral_description TEXT,
        original_filing_number TEXT,
        amendment_type TEXT,
        source_tier TEXT,
        source_raw TEXT,
        ingested_at TEXT NOT NULL,
        last_updated_at TEXT,
        UNIQUE(filing_number, state)
    );

    -- Compound indexes for common query patterns
    CREATE INDEX IF NOT EXISTS idx_filings_state_date ON ucc_filings(state, filing_date);
    CREATE INDEX IF NOT EXISTS idx_filings_state_status ON ucc_filings(state, filing_status);
    CREATE INDEX IF NOT EXISTS idx_filings_number_state ON ucc_filings(filing_number, state);

    -- Single-column indexes for standalone lookups
    CREATE INDEX IF NOT EXISTS idx_filings_debtor_name ON ucc_filings(debtor_name);
    CREATE INDEX IF NOT EXISTS idx_filings_secured_party ON ucc_filings(secured_party_name);
    CREATE INDEX IF NOT EXISTS idx_filings_ingested ON ucc_filings(ingested_at);
    CREATE INDEX IF NOT EXISTS idx_filings_lapse ON ucc_filings(lapse_date);

    CREATE TABLE IF NOT EXISTS ingestion_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        run_id TEXT UNIQUE NOT NULL,
        state TEXT NOT NULL,
        source_tier TEXT NOT NULL,
        started_at TEXT NOT NULL,
        completed_at TEXT,
        records_fetched INTEGER DEFAULT 0,
        records_new INTEGER DEFAULT 0,
        records_updated INTEGER DEFAULT 0,
        records_skipped INTEGER DEFAULT 0,
        status TEXT DEFAULT 'running',
        error_message TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_runs_state ON ingestion_runs(state);
    CREATE INDEX IF NOT EXISTS idx_runs_status ON ingestion_runs(status);

    CREATE TABLE IF NOT EXISTS schema_version (
        version INTEGER PRIMARY KEY
    );
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self):
        cursor = self.conn.cursor()
        cursor.executescript(self.DDL)

        # Track schema version
        cursor.execute("SELECT version FROM schema_version LIMIT 1")
        row = cursor.fetchone()
        if row is None:
            cursor.execute(
                "INSERT INTO schema_version (version) VALUES (?)",
                (self.SCHEMA_VERSION,),
            )
        self.conn.commit()

    def upsert_filing(self, filing: UCCFiling) -> str:
        """Insert or update a filing. Returns 'new', 'updated', or 'skipped'."""
        now = datetime.now(timezone.utc).isoformat()
        if not filing.ingested_at:
            filing.ingested_at = now

        cursor = self.conn.cursor()

        # Check for existing record by the natural key (filing_number, state)
        cursor.execute(
            """SELECT id, last_updated_at, source_raw FROM ucc_filings
               WHERE filing_number = ? AND state = ?
            """,
            (filing.filing_number, filing.state),
        )
        existing = cursor.fetchone()

        if existing is None:
            # New record
            cursor.execute(
                """INSERT INTO ucc_filings (
                    filing_number, state, filing_type, filing_date, lapse_date,
                    filing_status, debtor_name, debtor_address, debtor_city,
                    debtor_state, debtor_zip, debtor_organization, debtor_type,
                    secured_party_name, secured_party_address, secured_party_city,
                    secured_party_state, secured_party_zip, collateral_description,
                    original_filing_number, amendment_type, source_tier, source_raw,
                    ingested_at, last_updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    filing.filing_number, filing.state, filing.filing_type,
                    filing.filing_date, filing.lapse_date, filing.filing_status,
                    filing.debtor_name, filing.debtor_address, filing.debtor_city,
                    filing.debtor_state, filing.debtor_zip, filing.debtor_organization,
                    filing.debtor_type, filing.secured_party_name,
                    filing.secured_party_address, filing.secured_party_city,
                    filing.secured_party_state, filing.secured_party_zip,
                    filing.collateral_description, filing.original_filing_number,
                    filing.amendment_type, filing.source_tier, filing.source_raw,
                    filing.ingested_at, now,
                ),
            )
            return "new"

        # Existing record — update if source data changed
        existing_id, existing_updated, existing_raw = existing
        if existing_raw == filing.source_raw:
            return "skipped"

        cursor.execute(
            """UPDATE ucc_filings SET
                filing_type=?, filing_date=?, lapse_date=?, filing_status=?,
                debtor_name=?, debtor_address=?, debtor_city=?, debtor_state=?,
                debtor_zip=?, debtor_organization=?, debtor_type=?,
                secured_party_name=?, secured_party_address=?, secured_party_city=?,
                secured_party_state=?, secured_party_zip=?,
                collateral_description=?, original_filing_number=?,
                amendment_type=?, source_tier=?, source_raw=?,
                last_updated_at=?
               WHERE id=?""",
            (
                filing.filing_type, filing.filing_date, filing.lapse_date,
                filing.filing_status, filing.debtor_name, filing.debtor_address,
                filing.debtor_city, filing.debtor_state, filing.debtor_zip,
                filing.debtor_organization, filing.debtor_type,
                filing.secured_party_name, filing.secured_party_address,
                filing.secured_party_city, filing.secured_party_state,
                filing.secured_party_zip, filing.collateral_description,
                filing.original_filing_number, filing.amendment_type,
                filing.source_tier, filing.source_raw, now,
                existing_id,
            ),
        )
        return "updated"

    def upsert_filings_batch(self, filings: list[UCCFiling]) -> dict:
        """Batch upsert with explicit transaction. Returns counts and errors.

        The entire batch is wrapped in a transaction. If any record fails,
        the transaction is rolled back and the error is recorded. Individual
        failures are tracked so they can be retried separately.
        """
        counts = {"new": 0, "updated": 0, "skipped": 0, "errors": []}
        try:
            self.conn.execute("BEGIN")
            for i, filing in enumerate(filings):
                try:
                    result = self.upsert_filing(filing)
                    counts[result] += 1
                except Exception as e:
                    logger.warning(
                        "Record %d failed (filing_number=%s, state=%s): %s",
                        i, filing.filing_number, filing.state, e,
                    )
                    counts["errors"].append({
                        "index": i,
                        "filing_number": filing.filing_number,
                        "state": filing.state,
                        "error": str(e),
                    })
            self.conn.execute("COMMIT")
        except Exception as e:
            logger.error("Batch transaction failed, rolling back: %s", e)
            self.conn.execute("ROLLBACK")
            raise
        return counts

    def record_ingestion_run(self, run: IngestionRun):
        """Insert or update an ingestion run record."""
        cursor = self.conn.cursor()
        cursor.execute(
            """INSERT INTO ingestion_runs
               (run_id, state, source_tier, started_at, completed_at,
                records_fetched, records_new, records_updated, records_skipped,
                status, error_message)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(run_id) DO UPDATE SET
                completed_at=excluded.completed_at,
                records_fetched=excluded.records_fetched,
                records_new=excluded.records_new,
                records_updated=excluded.records_updated,
                records_skipped=excluded.records_skipped,
                status=excluded.status,
                error_message=excluded.error_message
            """,
            (
                run.run_id, run.state, run.source_tier, run.started_at,
                run.completed_at, run.records_fetched, run.records_new,
                run.records_updated, run.records_skipped, run.status,
                run.error_message,
            ),
        )
        self.conn.commit()

    def get_filing_count(self, state: Optional[str] = None) -> int:
        cursor = self.conn.cursor()
        if state:
            cursor.execute(
                "SELECT COUNT(*) FROM ucc_filings WHERE state=?", (state,)
            )
        else:
            cursor.execute("SELECT COUNT(*) FROM ucc_filings")
        return cursor.fetchone()[0]

    def get_latest_filing_date(self, state: str) -> Optional[str]:
        """Get the most recent filing_date for a state (for incremental pulls)."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT MAX(filing_date) FROM ucc_filings WHERE state=?", (state,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_latest_ingestion(self, state: str) -> Optional[str]:
        """Get the most recent ingested_at timestamp for a state."""
        cursor = self.conn.cursor()
        cursor.execute(
            "SELECT MAX(ingested_at) FROM ucc_filings WHERE state=?", (state,)
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def get_ingestion_history(self, state: Optional[str] = None, limit: int = 20):
        """Get recent ingestion runs."""
        cursor = self.conn.cursor()
        if state:
            cursor.execute(
                """SELECT * FROM ingestion_runs WHERE state=?
                   ORDER BY started_at DESC LIMIT ?""",
                (state, limit),
            )
        else:
            cursor.execute(
                "SELECT * FROM ingestion_runs ORDER BY started_at DESC LIMIT ?",
                (limit,),
            )
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def get_stats(self) -> dict:
        """Get overall database statistics."""
        cursor = self.conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM ucc_filings")
        total = cursor.fetchone()[0]

        cursor.execute(
            "SELECT state, COUNT(*) FROM ucc_filings GROUP BY state ORDER BY COUNT(*) DESC"
        )
        by_state = {row[0]: row[1] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT filing_status, COUNT(*) FROM ucc_filings GROUP BY filing_status"
        )
        by_status = {row[0] or "unknown": row[1] for row in cursor.fetchall()}

        cursor.execute(
            "SELECT source_tier, COUNT(*) FROM ucc_filings GROUP BY source_tier"
        )
        by_source = {row[0] or "unknown": row[1] for row in cursor.fetchall()}

        cursor.execute("SELECT MIN(filing_date), MAX(filing_date) FROM ucc_filings")
        date_range = cursor.fetchone()

        return {
            "total_filings": total,
            "states_covered": len(by_state),
            "by_state": by_state,
            "by_status": by_status,
            "by_source_tier": by_source,
            "earliest_filing": date_range[0],
            "latest_filing": date_range[1],
        }

    def close(self):
        self.conn.close()
