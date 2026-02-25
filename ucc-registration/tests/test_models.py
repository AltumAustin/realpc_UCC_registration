"""Tests for the models module (UCCDatabase upsert logic)."""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.models import UCCDatabase, UCCFiling


def _make_db():
    """Create a temporary in-memory-like database for testing."""
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    return UCCDatabase(tmp.name), tmp.name


def _make_filing(**overrides):
    defaults = {
        "filing_number": "UCC-2024-001",
        "state": "TX",
        "filing_type": "UCC-1",
        "filing_date": "2024-01-15",
        "debtor_name": "JOHN DOE",
        "secured_party_name": "ACME BANK",
        "source_tier": "state_bulk",
        "source_raw": '{"test": "data"}',
    }
    defaults.update(overrides)
    return UCCFiling(**defaults)


class TestUpsertFiling:
    def setup_method(self):
        self.db, self.db_path = _make_db()

    def teardown_method(self):
        self.db.close()
        os.unlink(self.db_path)

    def test_new_record(self):
        filing = _make_filing()
        result = self.db.upsert_filing(filing)
        self.db.conn.commit()
        assert result == "new"
        assert self.db.get_filing_count() == 1

    def test_duplicate_skipped(self):
        filing = _make_filing()
        self.db.upsert_filing(filing)
        self.db.conn.commit()
        result = self.db.upsert_filing(filing)
        self.db.conn.commit()
        assert result == "skipped"
        assert self.db.get_filing_count() == 1

    def test_updated_when_source_raw_changes(self):
        filing = _make_filing()
        self.db.upsert_filing(filing)
        self.db.conn.commit()

        filing.source_raw = '{"test": "updated"}'
        result = self.db.upsert_filing(filing)
        self.db.conn.commit()
        assert result == "updated"
        assert self.db.get_filing_count() == 1

    def test_same_filing_number_different_name_is_same_record(self):
        """With UNIQUE(filing_number, state), name differences don't create dupes."""
        filing1 = _make_filing(debtor_name="JOHN DOE")
        filing2 = _make_filing(debtor_name="John Doe", source_raw='{"v": 2}')

        self.db.upsert_filing(filing1)
        self.db.conn.commit()
        result = self.db.upsert_filing(filing2)
        self.db.conn.commit()

        # Should be "updated" (same filing_number+state), not "new"
        assert result == "updated"
        assert self.db.get_filing_count() == 1

    def test_different_state_is_different_record(self):
        filing_tx = _make_filing(state="TX")
        filing_ca = _make_filing(state="CA")

        self.db.upsert_filing(filing_tx)
        self.db.upsert_filing(filing_ca)
        self.db.conn.commit()

        assert self.db.get_filing_count() == 2

    def test_update_includes_debtor_name(self):
        """Verify that UPDATE SET includes debtor_name and secured_party_name."""
        filing = _make_filing(debtor_name="OLD NAME")
        self.db.upsert_filing(filing)
        self.db.conn.commit()

        filing.debtor_name = "NEW NAME"
        filing.source_raw = '{"v": 2}'
        self.db.upsert_filing(filing)
        self.db.conn.commit()

        cursor = self.db.conn.cursor()
        cursor.execute("SELECT debtor_name FROM ucc_filings WHERE filing_number=?",
                        (filing.filing_number,))
        assert cursor.fetchone()[0] == "NEW NAME"


class TestUpsertFilingsBatch:
    def setup_method(self):
        self.db, self.db_path = _make_db()

    def teardown_method(self):
        self.db.close()
        os.unlink(self.db_path)

    def test_batch_counts(self):
        filings = [
            _make_filing(filing_number=f"UCC-{i}") for i in range(5)
        ]
        counts = self.db.upsert_filings_batch(filings)
        assert counts["new"] == 5
        assert counts["updated"] == 0
        assert counts["skipped"] == 0

    def test_batch_mixed_operations(self):
        # Insert first
        filing = _make_filing(filing_number="UCC-001")
        self.db.upsert_filing(filing)
        self.db.conn.commit()

        # Batch with: one skip (same data), one update, one new
        filings = [
            _make_filing(filing_number="UCC-001"),  # skip
            _make_filing(filing_number="UCC-001", source_raw='{"v":2}'),  # update (wait, UCC-001 was already skipped above)
            _make_filing(filing_number="UCC-002"),  # new
        ]
        counts = self.db.upsert_filings_batch(filings)
        # First UCC-001 matches existing raw → skip
        # Second UCC-001 has new raw → update
        # UCC-002 → new
        assert counts["new"] == 1
        assert counts["skipped"] == 1
        assert counts["updated"] == 1

    def test_batch_error_tracking(self):
        counts = self.db.upsert_filings_batch([])
        assert counts["errors"] == []


class TestDatabaseQueries:
    def setup_method(self):
        self.db, self.db_path = _make_db()

    def teardown_method(self):
        self.db.close()
        os.unlink(self.db_path)

    def test_get_filing_count_by_state(self):
        for i in range(3):
            self.db.upsert_filing(_make_filing(filing_number=f"TX-{i}", state="TX"))
        for i in range(2):
            self.db.upsert_filing(_make_filing(filing_number=f"CA-{i}", state="CA"))
        self.db.conn.commit()

        assert self.db.get_filing_count("TX") == 3
        assert self.db.get_filing_count("CA") == 2
        assert self.db.get_filing_count() == 5

    def test_get_latest_filing_date(self):
        for date in ["2024-01-01", "2024-06-15", "2024-03-10"]:
            self.db.upsert_filing(_make_filing(
                filing_number=f"TX-{date}", state="TX", filing_date=date,
                source_raw=f'{{"d":"{date}"}}',
            ))
        self.db.conn.commit()

        assert self.db.get_latest_filing_date("TX") == "2024-06-15"
        assert self.db.get_latest_filing_date("CA") is None
