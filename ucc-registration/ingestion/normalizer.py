"""
Post-ingestion normalizer.

Standardizes field values across different sources to ensure
consistency in the database (date formats, name casing, status
codes, filing type codes, etc.).
"""

import logging
import re
from datetime import datetime
from typing import Optional

from .models import UCCFiling

logger = logging.getLogger(__name__)


# Normalize filing type codes to standard labels
FILING_TYPE_MAP = {
    # UCC-1 variants
    "UCC1": "UCC-1", "UCC-1": "UCC-1", "UCC 1": "UCC-1",
    "INITIAL": "UCC-1", "FINANCING STATEMENT": "UCC-1",
    "FS": "UCC-1", "ORIGINAL": "UCC-1", "01": "UCC-1",
    "UCC1F": "UCC-1F", "UCC-1F": "UCC-1F",
    # UCC-3 variants
    "UCC3": "UCC-3", "UCC-3": "UCC-3", "UCC 3": "UCC-3",
    "AMENDMENT": "UCC-3", "03": "UCC-3",
    "UCC3F": "UCC-3F", "UCC-3F": "UCC-3F",
    # Specific UCC-3 actions
    "CONTINUATION": "UCC-3-CONTINUATION",
    "TERMINATION": "UCC-3-TERMINATION",
    "ASSIGNMENT": "UCC-3-ASSIGNMENT",
    "PARTIAL ASSIGNMENT": "UCC-3-PARTIAL-ASSIGNMENT",
    # UCC-5 variants
    "UCC5": "UCC-5", "UCC-5": "UCC-5", "UCC 5": "UCC-5",
    "CORRECTION": "UCC-5", "05": "UCC-5",
    # Tax liens
    "FEDERAL TAX LIEN": "FEDERAL-TAX-LIEN",
    "STATE TAX LIEN": "STATE-TAX-LIEN",
    "IRS": "FEDERAL-TAX-LIEN",
}

# Normalize status values
STATUS_MAP = {
    "A": "active", "ACTIVE": "active", "Active": "active",
    "L": "lapsed", "LAPSED": "lapsed", "Lapsed": "lapsed", "EXPIRED": "lapsed",
    "T": "terminated", "TERMINATED": "terminated", "Terminated": "terminated",
    "C": "continued", "CONTINUED": "continued",
}

# Date patterns we might encounter
DATE_PATTERNS = [
    (r"^\d{4}-\d{2}-\d{2}$", "%Y-%m-%d"),           # 2024-01-15
    (r"^\d{4}-\d{2}-\d{2}T", "%Y-%m-%dT%H:%M:%S"),  # 2024-01-15T00:00:00
    (r"^\d{2}/\d{2}/\d{4}$", "%m/%d/%Y"),             # 01/15/2024
    (r"^\d{2}-\d{2}-\d{4}$", "%m-%d-%Y"),             # 01-15-2024
    (r"^\d{8}$", "%Y%m%d"),                            # 20240115
    (r"^\d{2}/\d{2}/\d{2}$", "%m/%d/%y"),             # 01/15/24
]


def normalize_date(value: Optional[str]) -> Optional[str]:
    """Normalize any date string to ISO 8601 YYYY-MM-DD."""
    if not value or not value.strip():
        return None

    value = value.strip()

    # Already in correct format — but validate the actual date values
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        try:
            datetime.strptime(value, "%Y-%m-%d")
            return value
        except ValueError:
            logger.debug("Invalid ISO date value: %r", value)
            return None

    # Try to strip time portion from ISO datetime
    if "T" in value:
        date_part = value.split("T")[0]
        try:
            datetime.strptime(date_part, "%Y-%m-%d")
            return date_part
        except ValueError:
            pass

    for pattern, fmt in DATE_PATTERNS:
        if re.match(pattern, value):
            try:
                dt = datetime.strptime(value[:len(fmt.replace("%", "0"))], fmt)
                return dt.strftime("%Y-%m-%d")
            except ValueError:
                continue

    # Last resort: try common formats
    for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%Y%m%d", "%m/%d/%y", "%d-%b-%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue

    logger.debug("Could not parse date value: %r", value)
    return None  # Return None for unparseable dates instead of the invalid string


def normalize_name(value: Optional[str], uppercase: bool = False) -> Optional[str]:
    """Normalize a name: strip whitespace and collapse multiple spaces.

    Args:
        value: Raw name string.
        uppercase: If True, convert to uppercase (for dedup-sensitive fields).
    """
    if not value:
        return None
    value = re.sub(r"\s+", " ", value.strip())
    if not value:
        return None
    if uppercase:
        return value.upper()
    return value


def normalize_filing_type(value: Optional[str]) -> Optional[str]:
    """Normalize filing type codes."""
    if not value:
        return None
    key = value.strip().upper().replace("-", "").replace(" ", "")
    # Try exact match first
    if value.strip().upper() in FILING_TYPE_MAP:
        return FILING_TYPE_MAP[value.strip().upper()]
    # Try without punctuation
    if key in {k.replace("-", "").replace(" ", ""): v for k, v in FILING_TYPE_MAP.items()}:
        for k, v in FILING_TYPE_MAP.items():
            if k.replace("-", "").replace(" ", "") == key:
                return v
    return value.strip().upper()


def normalize_status(value: Optional[str]) -> Optional[str]:
    """Normalize filing status codes."""
    if not value:
        return None
    key = value.strip().upper()
    return STATUS_MAP.get(key, STATUS_MAP.get(value.strip(), value.strip().lower()))


def normalize_zip(value: Optional[str]) -> Optional[str]:
    """Normalize ZIP codes to 5-digit or ZIP+4 format."""
    if not value:
        return None
    digits = re.sub(r"[^0-9]", "", value.strip())
    if len(digits) == 9:
        return f"{digits[:5]}-{digits[5:]}"
    elif len(digits) >= 5:
        return digits[:5]
    return value.strip()


def normalize_state_abbrev(value: Optional[str]) -> Optional[str]:
    """Normalize state abbreviations to 2-letter uppercase."""
    if not value:
        return None
    value = value.strip().upper()
    if len(value) == 2:
        return value
    return value


def normalize_filing(filing: UCCFiling) -> UCCFiling:
    """Apply all normalizations to a UCCFiling record."""
    filing.filing_date = normalize_date(filing.filing_date)
    filing.lapse_date = normalize_date(filing.lapse_date)
    filing.filing_type = normalize_filing_type(filing.filing_type)
    filing.filing_status = normalize_status(filing.filing_status)

    filing.debtor_name = normalize_name(filing.debtor_name, uppercase=True)
    filing.debtor_address = normalize_name(filing.debtor_address)
    filing.debtor_city = normalize_name(filing.debtor_city)
    filing.debtor_state = normalize_state_abbrev(filing.debtor_state)
    filing.debtor_zip = normalize_zip(filing.debtor_zip)

    filing.secured_party_name = normalize_name(filing.secured_party_name, uppercase=True)
    filing.secured_party_address = normalize_name(filing.secured_party_address)
    filing.secured_party_city = normalize_name(filing.secured_party_city)
    filing.secured_party_state = normalize_state_abbrev(filing.secured_party_state)
    filing.secured_party_zip = normalize_zip(filing.secured_party_zip)

    filing.collateral_description = normalize_name(filing.collateral_description)

    return filing
