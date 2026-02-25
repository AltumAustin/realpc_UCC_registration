"""Tests for state_bulk.py parsers using sample data files."""

import csv
import json
import os
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.adapters.state_bulk import StateBulkAdapter, _is_before_date, CSV_COLUMN_MAPS
from ingestion.config import StateSourceConfig, SourceTier, PollFrequency, DataFormat, IngestionSettings


def _make_config(state="TX", data_format=DataFormat.JSON):
    return StateSourceConfig(
        state="Test",
        abbreviation=state,
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.DAILY,
        data_format=data_format,
        expected_latency_days=1.0,
        annual_cost_usd=0,
    )


def _make_settings():
    return IngestionSettings(
        db_path=":memory:",
        download_dir=tempfile.mkdtemp(),
    )


class TestIsBeforeDate:
    def test_before(self):
        assert _is_before_date("2024-01-15", "2024-02-01") is True

    def test_after(self):
        assert _is_before_date("2024-03-15", "2024-02-01") is False

    def test_equal(self):
        assert _is_before_date("2024-02-01", "2024-02-01") is False

    def test_none_filing_date(self):
        assert _is_before_date(None, "2024-02-01") is False

    def test_empty_filing_date(self):
        assert _is_before_date("", "2024-02-01") is False

    def test_invalid_dates_not_skipped(self):
        assert _is_before_date("not-a-date", "2024-02-01") is False


class TestCSVParser:
    def test_parse_csv_with_column_map(self):
        config = _make_config(state="KY", data_format=DataFormat.CSV)
        settings = _make_settings()
        adapter = StateBulkAdapter(config, settings)

        # Write a sample CSV matching Kentucky's column map
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8",
        )
        column_map = CSV_COLUMN_MAPS["KY"]
        writer = csv.DictWriter(tmp, fieldnames=list(column_map.keys()))
        writer.writeheader()
        writer.writerow({
            "FileNumber": "KY-2024-001",
            "FilingType": "UCC-1",
            "FileDate": "2024-01-15",
            "LapseDate": "2029-01-15",
            "Status": "Active",
            "DebtorName": "Test Corp",
            "DebtorAddress": "123 Main St",
            "DebtorCity": "Louisville",
            "DebtorState": "KY",
            "DebtorZip": "40202",
            "SecuredPartyName": "Big Bank",
            "SecuredPartyAddress": "456 Finance Ave",
            "SecuredPartyCity": "Lexington",
            "SecuredPartyState": "KY",
            "SecuredPartyZip": "40507",
        })
        tmp.close()

        filings = list(adapter._parse_csv(tmp.name, column_map))
        os.unlink(tmp.name)

        assert len(filings) == 1
        f = filings[0]
        assert f.filing_number == "KY-2024-001"
        assert f.filing_type == "UCC-1"
        assert f.debtor_name == "Test Corp"
        assert f.secured_party_name == "Big Bank"
        assert f.state == "KY"

    def test_skip_rows_without_filing_number(self):
        config = _make_config(state="KY", data_format=DataFormat.CSV)
        settings = _make_settings()
        adapter = StateBulkAdapter(config, settings)

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".csv", delete=False, encoding="utf-8",
        )
        writer = csv.DictWriter(tmp, fieldnames=["FileNumber", "FilingType"])
        writer.writeheader()
        writer.writerow({"FileNumber": "", "FilingType": "UCC-1"})
        writer.writerow({"FileNumber": "KY-001", "FilingType": "UCC-1"})
        tmp.close()

        column_map = {"FileNumber": "filing_number", "FilingType": "filing_type"}
        filings = list(adapter._parse_csv(tmp.name, column_map))
        os.unlink(tmp.name)

        assert len(filings) == 1


class TestJSONParser:
    def test_parse_json_array(self):
        config = _make_config(state="TX")
        settings = _make_settings()
        adapter = StateBulkAdapter(config, settings)

        data = [
            {"filing_number": "TX-001", "filing_type": "UCC-1", "file_date": "2024-01-15"},
            {"filing_number": "TX-002", "filing_type": "UCC-3", "file_date": "2024-02-01"},
        ]

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        )
        json.dump(data, tmp)
        tmp.close()

        from ingestion.adapters.state_bulk import TX_FIELD_MAP
        filings = list(adapter._parse_json_bulk(tmp.name, TX_FIELD_MAP))
        os.unlink(tmp.name)

        assert len(filings) == 2
        assert filings[0].filing_number == "TX-001"
        assert filings[1].filing_number == "TX-002"

    def test_parse_json_nested_records(self):
        config = _make_config(state="TX")
        settings = _make_settings()
        adapter = StateBulkAdapter(config, settings)

        data = {"records": [
            {"filing_number": "TX-001", "filing_type": "UCC-1"},
        ]}

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8",
        )
        json.dump(data, tmp)
        tmp.close()

        from ingestion.adapters.state_bulk import TX_FIELD_MAP
        filings = list(adapter._parse_json_bulk(tmp.name, TX_FIELD_MAP))
        os.unlink(tmp.name)

        assert len(filings) == 1


class TestXMLParser:
    def test_parse_xml_basic(self):
        config = _make_config(state="CA", data_format=DataFormat.XML)
        settings = _make_settings()
        adapter = StateBulkAdapter(config, settings)

        xml_content = """<?xml version="1.0"?>
<Root>
    <Filing>
        <FileNumber>CA-2024-001</FileNumber>
        <FileType>UCC-1</FileType>
        <FileDate>2024-03-15</FileDate>
        <LapseDate>2029-03-15</LapseDate>
        <Debtor>
            <Name>Test Corp</Name>
            <City>Los Angeles</City>
            <State>CA</State>
        </Debtor>
        <SecuredParty>
            <Name>Pacific Bank</Name>
            <City>San Francisco</City>
            <State>CA</State>
        </SecuredParty>
    </Filing>
</Root>"""

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False, encoding="utf-8",
        )
        tmp.write(xml_content)
        tmp.close()

        filings = list(adapter._parse_xml_bulk(tmp.name))
        os.unlink(tmp.name)

        assert len(filings) == 1
        f = filings[0]
        assert f.filing_number == "CA-2024-001"
        assert f.filing_type == "UCC-1"
        assert f.debtor_name == "Test Corp"
        assert f.secured_party_name == "Pacific Bank"

    def test_parse_xml_with_namespace(self):
        config = _make_config(state="IN", data_format=DataFormat.XML)
        settings = _make_settings()
        adapter = StateBulkAdapter(config, settings)

        xml_content = """<?xml version="1.0"?>
<Root xmlns="http://iaca.org/ucc/v4">
    <Filing>
        <FilingNumber>IN-2024-001</FilingNumber>
        <FilingType>UCC-1</FilingType>
    </Filing>
</Root>"""

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".xml", delete=False, encoding="utf-8",
        )
        tmp.write(xml_content)
        tmp.close()

        filings = list(adapter._parse_xml_bulk(tmp.name))
        os.unlink(tmp.name)

        assert len(filings) == 1
        assert filings[0].filing_number == "IN-2024-001"


class TestFixedWidthParser:
    def test_parse_florida_format(self):
        config = _make_config(state="FL", data_format=DataFormat.FIXED_WIDTH)
        settings = _make_settings()
        adapter = StateBulkAdapter(config, settings)

        # Build a fixed-width line matching Florida's provisional positions
        line = ""
        line += "FL-2024-001    "   # 0-15: filing_number
        line += "UCC-1"             # 15-20: filing_type
        line += "2024-03-15"        # 20-30: filing_date
        line += "2029-03-15"        # 30-40: lapse_date
        line += "A    "             # 40-45: filing_status
        line += "Test Corporation" + " " * 84  # 45-145: debtor_name (100 chars)
        line += " " * 100           # 145-245: debtor_address
        line += " " * 50            # 245-295: debtor_city
        line += "FL"                # 295-297: debtor_state
        line += " " * 10            # 297-307: debtor_zip
        line += "Pacific Bank" + " " * 88  # 307-407: secured_party_name
        line += " " * 100           # 407-507: secured_party_address
        line += " " * 50            # 507-557: secured_party_city
        line += "FL"                # 557-559: secured_party_state
        line += " " * 10            # 559-569: secured_party_zip
        line += "\n"

        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".dat", delete=False, encoding="utf-8",
        )
        tmp.write(line)
        tmp.close()

        filings = list(adapter._parse_fixed_width(tmp.name))
        os.unlink(tmp.name)

        assert len(filings) == 1
        f = filings[0]
        assert f.filing_number == "FL-2024-001"
        assert f.filing_type == "UCC-1"
        assert f.debtor_name == "Test Corporation"
        assert f.secured_party_name == "Pacific Bank"
