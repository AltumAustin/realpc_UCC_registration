"""Tests for the normalizer module."""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from ingestion.normalizer import (
    normalize_date,
    normalize_name,
    normalize_filing_type,
    normalize_status,
    normalize_zip,
    normalize_state_abbrev,
    normalize_filing,
)
from ingestion.models import UCCFiling


class TestNormalizeDate:
    def test_iso_format_passthrough(self):
        assert normalize_date("2024-01-15") == "2024-01-15"

    def test_iso_datetime_strips_time(self):
        assert normalize_date("2024-01-15T12:30:00") == "2024-01-15"

    def test_mm_dd_yyyy_slash(self):
        assert normalize_date("01/15/2024") == "2024-01-15"

    def test_mm_dd_yyyy_dash(self):
        assert normalize_date("01-15-2024") == "2024-01-15"

    def test_yyyymmdd_compact(self):
        assert normalize_date("20240115") == "2024-01-15"

    def test_mm_dd_yy_short(self):
        assert normalize_date("01/15/24") == "2024-01-15"

    def test_none_input(self):
        assert normalize_date(None) is None

    def test_empty_string(self):
        assert normalize_date("") is None

    def test_whitespace_only(self):
        assert normalize_date("   ") is None

    def test_invalid_date_returns_none(self):
        assert normalize_date("2024-13-45") is None

    def test_garbage_returns_none(self):
        assert normalize_date("not-a-date") is None

    def test_strips_whitespace(self):
        assert normalize_date("  2024-01-15  ") == "2024-01-15"


class TestNormalizeName:
    def test_basic_name(self):
        assert normalize_name("John Doe") == "John Doe"

    def test_uppercase_flag(self):
        assert normalize_name("John Doe", uppercase=True) == "JOHN DOE"

    def test_collapse_whitespace(self):
        assert normalize_name("John   Doe") == "John Doe"

    def test_strip_whitespace(self):
        assert normalize_name("  John Doe  ") == "John Doe"

    def test_none_input(self):
        assert normalize_name(None) is None

    def test_empty_string(self):
        assert normalize_name("") is None

    def test_whitespace_only(self):
        assert normalize_name("   ") is None

    def test_uppercase_with_extra_spaces(self):
        assert normalize_name("  john   doe  ", uppercase=True) == "JOHN DOE"


class TestNormalizeFilingType:
    def test_ucc1_variants(self):
        assert normalize_filing_type("UCC1") == "UCC-1"
        assert normalize_filing_type("UCC-1") == "UCC-1"
        assert normalize_filing_type("UCC 1") == "UCC-1"
        assert normalize_filing_type("INITIAL") == "UCC-1"

    def test_ucc3_variants(self):
        assert normalize_filing_type("UCC3") == "UCC-3"
        assert normalize_filing_type("AMENDMENT") == "UCC-3"

    def test_specific_actions(self):
        assert normalize_filing_type("CONTINUATION") == "UCC-3-CONTINUATION"
        assert normalize_filing_type("TERMINATION") == "UCC-3-TERMINATION"

    def test_none_input(self):
        assert normalize_filing_type(None) is None

    def test_unknown_type_uppercased(self):
        assert normalize_filing_type("something") == "SOMETHING"


class TestNormalizeStatus:
    def test_single_letter_codes(self):
        assert normalize_status("A") == "active"
        assert normalize_status("L") == "lapsed"
        assert normalize_status("T") == "terminated"

    def test_full_word_variants(self):
        assert normalize_status("ACTIVE") == "active"
        assert normalize_status("Active") == "active"
        assert normalize_status("EXPIRED") == "lapsed"

    def test_none_input(self):
        assert normalize_status(None) is None


class TestNormalizeZip:
    def test_five_digit(self):
        assert normalize_zip("12345") == "12345"

    def test_nine_digit_to_plus_four(self):
        assert normalize_zip("123456789") == "12345-6789"

    def test_with_dash(self):
        assert normalize_zip("12345-6789") == "12345-6789"

    def test_none_input(self):
        assert normalize_zip(None) is None


class TestNormalizeStateAbbrev:
    def test_two_letter(self):
        assert normalize_state_abbrev("CA") == "CA"

    def test_lowercase(self):
        assert normalize_state_abbrev("ca") == "CA"

    def test_none_input(self):
        assert normalize_state_abbrev(None) is None


class TestNormalizeFiling:
    def test_full_normalization(self):
        filing = UCCFiling(
            filing_number="123",
            state="TX",
            filing_type="UCC1",
            filing_date="01/15/2024",
            debtor_name="john doe",
            secured_party_name="Jane Smith",
            debtor_state="tx",
            debtor_zip="123456789",
        )
        result = normalize_filing(filing)
        assert result.filing_type == "UCC-1"
        assert result.filing_date == "2024-01-15"
        assert result.debtor_name == "JOHN DOE"
        assert result.secured_party_name == "JANE SMITH"
        assert result.debtor_state == "TX"
        assert result.debtor_zip == "12345-6789"
