"""
State bulk data download adapters.

Handles downloading, parsing, and normalizing bulk data files from
individual state Secretary of State offices. Each state has its own
format (CSV, XML, tab-delimited, fixed-width, JSON) with different
column names and conventions.

States covered in Tier 2:
  CA (XML, weekly), TX (JSON, daily), KY (CSV, daily), WV (CSV, weekly),
  ID (tab-delimited, biweekly), ND (CSV, biweekly), MN (CSV, weekly),
  AR (CSV, weekly), IN (XML, weekly), NY (XML, weekly), NC (CSV, weekly),
  SC (CSV, weekly), SD (CSV, weekly), AZ (CSV, monthly), FL (fixed-width, daily)
"""

import csv
import io
import json
import logging
import os
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from typing import Generator, Optional

import requests

from .base import BaseAdapter
from ..config import StateSourceConfig, IngestionSettings
from ..models import UCCFiling

logger = logging.getLogger(__name__)


# CSV column mappings per state (maps state CSV header → UCCFiling field)
CSV_COLUMN_MAPS = {
    "KY": {
        "FileNumber": "filing_number",
        "FilingType": "filing_type",
        "FileDate": "filing_date",
        "LapseDate": "lapse_date",
        "Status": "filing_status",
        "DebtorName": "debtor_name",
        "DebtorAddress": "debtor_address",
        "DebtorCity": "debtor_city",
        "DebtorState": "debtor_state",
        "DebtorZip": "debtor_zip",
        "SecuredPartyName": "secured_party_name",
        "SecuredPartyAddress": "secured_party_address",
        "SecuredPartyCity": "secured_party_city",
        "SecuredPartyState": "secured_party_state",
        "SecuredPartyZip": "secured_party_zip",
    },
    "WV": {
        # WV delivers 3 separate files — Documents, Debtors, SecuredParties
        # This maps the Documents file; debtors/secured parties merged in post-processing
        "DocNumber": "filing_number",
        "DocType": "filing_type",
        "FileDate": "filing_date",
        "LapseDate": "lapse_date",
        "Status": "filing_status",
        "OriginalFileNumber": "original_filing_number",
    },
    "ND": {
        "Filing_Number": "filing_number",
        "Filing_Type": "filing_type",
        "Filing_Date": "filing_date",
        "Lapse_Date": "lapse_date",
        "Debtor_Name": "debtor_name",
        "Debtor_Address": "debtor_address",
        "Debtor_City": "debtor_city",
        "Debtor_State": "debtor_state",
        "Debtor_Zip": "debtor_zip",
        "Secured_Party_Name": "secured_party_name",
        "Secured_Party_Address": "secured_party_address",
        "Secured_Party_City": "secured_party_city",
        "Secured_Party_State": "secured_party_state",
        "Secured_Party_Zip": "secured_party_zip",
    },
    "MN": {
        "FilingNumber": "filing_number",
        "FilingType": "filing_type",
        "FilingDate": "filing_date",
        "LapseDate": "lapse_date",
        "DebtorName": "debtor_name",
        "DebtorAddr": "debtor_address",
        "DebtorCity": "debtor_city",
        "DebtorState": "debtor_state",
        "DebtorZip": "debtor_zip",
        "SecuredName": "secured_party_name",
        "SecuredAddr": "secured_party_address",
        "SecuredCity": "secured_party_city",
        "SecuredState": "secured_party_state",
        "SecuredZip": "secured_party_zip",
    },
    "NC": {
        "FILE_NUMBER": "filing_number",
        "FILE_TYPE": "filing_type",
        "FILE_DATE": "filing_date",
        "LAPSE_DATE": "lapse_date",
        "STATUS": "filing_status",
        "DEBTOR_NAME": "debtor_name",
        "DEBTOR_ADDR": "debtor_address",
        "DEBTOR_CITY": "debtor_city",
        "DEBTOR_STATE": "debtor_state",
        "DEBTOR_ZIP": "debtor_zip",
        "SECURED_NAME": "secured_party_name",
        "SECURED_ADDR": "secured_party_address",
        "SECURED_CITY": "secured_party_city",
        "SECURED_STATE": "secured_party_state",
        "SECURED_ZIP": "secured_party_zip",
    },
    "SC": {
        "FilingNumber": "filing_number",
        "FilingType": "filing_type",
        "FilingDate": "filing_date",
        "LapseDate": "lapse_date",
        "Status": "filing_status",
        "DebtorName": "debtor_name",
        "DebtorAddress1": "debtor_address",
        "DebtorCity": "debtor_city",
        "DebtorState": "debtor_state",
        "DebtorZip": "debtor_zip",
        "SecuredPartyName": "secured_party_name",
        "SecuredPartyAddress1": "secured_party_address",
        "SecuredPartyCity": "secured_party_city",
        "SecuredPartyState": "secured_party_state",
        "SecuredPartyZip": "secured_party_zip",
    },
    "SD": {
        "FileNum": "filing_number",
        "FileType": "filing_type",
        "FileDate": "filing_date",
        "LapseDate": "lapse_date",
        "DebtorName": "debtor_name",
        "DebtorAddr": "debtor_address",
        "DebtorCity": "debtor_city",
        "DebtorState": "debtor_state",
        "DebtorZip": "debtor_zip",
        "SecuredName": "secured_party_name",
        "SecuredAddr": "secured_party_address",
        "SecuredCity": "secured_party_city",
        "SecuredState": "secured_party_state",
        "SecuredZip": "secured_party_zip",
    },
    "AR": {
        "filing_number": "filing_number",
        "filing_type": "filing_type",
        "filing_date": "filing_date",
        "lapse_date": "lapse_date",
        "debtor_name": "debtor_name",
        "debtor_address": "debtor_address",
        "debtor_city": "debtor_city",
        "debtor_state": "debtor_state",
        "debtor_zip": "debtor_zip",
        "secured_party_name": "secured_party_name",
        "secured_party_address": "secured_party_address",
        "secured_party_city": "secured_party_city",
        "secured_party_state": "secured_party_state",
        "secured_party_zip": "secured_party_zip",
    },
    "AZ": {
        "FilingNo": "filing_number",
        "FilingType": "filing_type",
        "FilingDate": "filing_date",
        "LapseDate": "lapse_date",
        "DebtorName": "debtor_name",
        "DebtorAddress": "debtor_address",
        "DebtorCity": "debtor_city",
        "DebtorState": "debtor_state",
        "DebtorZip": "debtor_zip",
        "SecuredPartyName": "secured_party_name",
        "SecuredPartyAddress": "secured_party_address",
        "SecuredPartyCity": "secured_party_city",
        "SecuredPartyState": "secured_party_state",
        "SecuredPartyZip": "secured_party_zip",
    },
}

# Texas uses JSON with specific field names
TX_FIELD_MAP = {
    "filing_number": "filing_number",
    "filing_type": "filing_type",
    "file_date": "filing_date",
    "lapse_date": "lapse_date",
    "status": "filing_status",
    "debtor_name": "debtor_name",
    "debtor_address": "debtor_address",
    "debtor_city": "debtor_city",
    "debtor_state": "debtor_state",
    "debtor_zip": "debtor_zip",
    "secured_party_name": "secured_party_name",
    "secured_party_address": "secured_party_address",
    "secured_party_city": "secured_party_city",
    "secured_party_state": "secured_party_state",
    "secured_party_zip": "secured_party_zip",
    "collateral": "collateral_description",
    "original_file_number": "original_filing_number",
    "amendment_type": "amendment_type",
}


class StateBulkAdapter(BaseAdapter):
    """Downloads and parses bulk data files from state filing offices.

    Each state requires specific handling. The adapter dispatches to
    format-specific parsers based on the state config.
    """

    def __init__(self, config: StateSourceConfig, settings: IngestionSettings):
        super().__init__(config, settings)
        self.download_dir = os.path.join(
            settings.download_dir, config.abbreviation
        )
        os.makedirs(self.download_dir, exist_ok=True)

    def _get_credentials(self) -> Optional[str]:
        """Load credentials from environment variable."""
        if self.config.auth_env_var:
            return os.environ.get(self.config.auth_env_var)
        return None

    def _download_file(self, url: str, filename: str) -> str:
        """Download a file atomically using a temp file.

        Downloads to a .tmp file first, then renames on success.
        If the download fails, the temp file is cleaned up so
        _find_latest_download() won't pick up a corrupt partial file.
        """
        filepath = os.path.join(self.download_dir, filename)
        tmp_path = filepath + ".tmp"
        creds = self._get_credentials()

        def do_request():
            auth = None
            if creds and ":" in creds:
                user, pwd = creds.split(":", 1)
                auth = (user, pwd)

            try:
                resp = requests.get(
                    url,
                    auth=auth,
                    timeout=self.settings.request_timeout_seconds,
                    stream=True,
                )
                resp.raise_for_status()

                with open(tmp_path, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        f.write(chunk)

                # Atomic rename on success
                os.replace(tmp_path, filepath)
            except Exception:
                # Clean up partial download
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
                raise

            return filepath

        return self._retry_request(do_request)

    def _parse_csv(self, filepath: str, column_map: dict) -> Generator[UCCFiling, None, None]:
        """Parse a CSV file using a column mapping."""
        now = datetime.now(timezone.utc).isoformat()

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                kwargs = {
                    "state": self.config.abbreviation,
                    "source_tier": "state_bulk",
                    "source_raw": json.dumps(row),
                    "ingested_at": now,
                }
                for csv_col, filing_field in column_map.items():
                    value = row.get(csv_col, "").strip()
                    if value:
                        kwargs[filing_field] = value

                if not kwargs.get("filing_number"):
                    logger.debug(
                        "%s: skipping CSV row without filing_number: %s",
                        self.config.abbreviation, {k: v[:50] for k, v in row.items() if v},
                    )
                    continue
                if not kwargs.get("filing_type"):
                    kwargs["filing_type"] = "UCC"

                yield UCCFiling(**kwargs)

    def _parse_tab_delimited(self, filepath: str) -> Generator[UCCFiling, None, None]:
        """Parse tab-delimited file (Idaho format)."""
        now = datetime.now(timezone.utc).isoformat()

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                kwargs = {
                    "state": self.config.abbreviation,
                    "source_tier": "state_bulk",
                    "source_raw": json.dumps(row),
                    "ingested_at": now,
                }
                # Idaho's exact columns will need verification on first download,
                # but they typically follow this pattern:
                for key, value in row.items():
                    value = value.strip() if value else ""
                    if not value:
                        continue
                    key_lower = key.lower().replace(" ", "_")
                    if "file" in key_lower and "num" in key_lower:
                        kwargs["filing_number"] = value
                    elif "file" in key_lower and "type" in key_lower:
                        kwargs["filing_type"] = value
                    elif "file" in key_lower and "date" in key_lower:
                        kwargs["filing_date"] = value
                    elif "lapse" in key_lower:
                        kwargs["lapse_date"] = value
                    elif "debtor" in key_lower and "name" in key_lower:
                        kwargs["debtor_name"] = value
                    elif "debtor" in key_lower and ("addr" in key_lower or "street" in key_lower):
                        kwargs["debtor_address"] = value
                    elif "debtor" in key_lower and "city" in key_lower:
                        kwargs["debtor_city"] = value
                    elif "debtor" in key_lower and "state" in key_lower:
                        kwargs["debtor_state"] = value
                    elif "debtor" in key_lower and "zip" in key_lower:
                        kwargs["debtor_zip"] = value
                    elif "secured" in key_lower and "name" in key_lower:
                        kwargs["secured_party_name"] = value
                    elif "secured" in key_lower and ("addr" in key_lower or "street" in key_lower):
                        kwargs["secured_party_address"] = value
                    elif "secured" in key_lower and "city" in key_lower:
                        kwargs["secured_party_city"] = value
                    elif "secured" in key_lower and "state" in key_lower:
                        kwargs["secured_party_state"] = value
                    elif "secured" in key_lower and "zip" in key_lower:
                        kwargs["secured_party_zip"] = value

                if not kwargs.get("filing_number"):
                    continue
                if not kwargs.get("filing_type"):
                    kwargs["filing_type"] = "UCC"

                yield UCCFiling(**kwargs)

    def _parse_json_bulk(self, filepath: str, field_map: dict) -> Generator[UCCFiling, None, None]:
        """Parse a JSON bulk data file using streaming for large files.

        Uses ijson for streaming when available and file is large (>10MB),
        falls back to json.load() for small files or when ijson is missing.
        """
        now = datetime.now(timezone.utc).isoformat()
        file_size = os.path.getsize(filepath)

        if file_size > 10 * 1024 * 1024:  # >10MB — stream
            try:
                import ijson
                yield from self._parse_json_streaming(filepath, field_map, now)
                return
            except ImportError:
                logger.warning(
                    "ijson not installed — loading %dMB JSON into memory. "
                    "Install ijson for streaming: pip install ijson",
                    file_size // (1024 * 1024),
                )

        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)

        records = data if isinstance(data, list) else data.get("records", data.get("filings", [data]))

        for raw in records:
            filing = self._json_record_to_filing(raw, field_map, now)
            if filing:
                yield filing

    def _parse_json_streaming(self, filepath: str, field_map: dict, now: str) -> Generator[UCCFiling, None, None]:
        """Stream JSON records one at a time using ijson."""
        import ijson

        with open(filepath, "rb") as f:
            # Try array at root level first (items), then nested keys
            try:
                for raw in ijson.items(f, "item"):
                    filing = self._json_record_to_filing(raw, field_map, now)
                    if filing:
                        yield filing
                return
            except ijson.common.IncompleteJSONError:
                pass

        # Fallback: try known nested keys
        for key in ("records", "filings"):
            with open(filepath, "rb") as f:
                try:
                    for raw in ijson.items(f, f"{key}.item"):
                        filing = self._json_record_to_filing(raw, field_map, now)
                        if filing:
                            yield filing
                    return
                except (ijson.common.IncompleteJSONError, StopIteration):
                    continue

    def _json_record_to_filing(self, raw: dict, field_map: dict, now: str) -> Optional[UCCFiling]:
        """Convert a single JSON record dict to a UCCFiling."""
        kwargs = {
            "state": self.config.abbreviation,
            "source_tier": "state_bulk",
            "source_raw": json.dumps(raw),
            "ingested_at": now,
        }
        for src_field, dst_field in field_map.items():
            value = raw.get(src_field, "")
            if value:
                kwargs[dst_field] = str(value).strip()

        if not kwargs.get("filing_number"):
            return None
        if not kwargs.get("filing_type"):
            kwargs["filing_type"] = "UCC"

        return UCCFiling(**kwargs)

    def _parse_xml_bulk(self, filepath: str) -> Generator[UCCFiling, None, None]:
        """Parse XML bulk data using iterparse for memory efficiency.

        Streams elements one at a time instead of loading the full tree.
        Handles common IACA XML elements for CA, IN, NY.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Filing-level element local names (without namespace)
        filing_local_names = {"Filing", "FinancingStatement", "Document"}

        # Detect namespace from first element
        ns = ""
        for event, elem in ET.iterparse(filepath, events=("start",)):
            if elem.tag.startswith("{"):
                ns = elem.tag.split("}")[0] + "}"
            break

        # Build the set of tags to match (with and without namespace)
        filing_tags = set()
        for name in filing_local_names:
            filing_tags.add(name)
            if ns:
                filing_tags.add(f"{ns}{name}")

        for event, elem in ET.iterparse(filepath, events=("end",)):
            tag_local = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag
            if tag_local not in filing_local_names:
                continue

            kwargs = {
                "state": self.config.abbreviation,
                "source_tier": "state_bulk",
                "source_raw": ET.tostring(elem, encoding="unicode"),
                "ingested_at": now,
            }

            # Extract filing number
            for tag in ["FileNumber", "FilingNumber", "DocumentNumber", "TransactionNumber"]:
                child = elem.find(f"{ns}{tag}") if ns else elem.find(tag)
                if child is not None and child.text:
                    kwargs["filing_number"] = child.text.strip()
                    break

            # Extract filing type
            for tag in ["FileType", "FilingType", "DocumentType", "ActionCode"]:
                child = elem.find(f"{ns}{tag}") if ns else elem.find(tag)
                if child is not None and child.text:
                    kwargs["filing_type"] = child.text.strip()
                    break

            # Extract dates
            for tag in ["FileDate", "FilingDate", "DocumentDate"]:
                child = elem.find(f"{ns}{tag}") if ns else elem.find(tag)
                if child is not None and child.text:
                    kwargs["filing_date"] = child.text.strip()[:10]
                    break

            for tag in ["LapseDate", "ExpirationDate"]:
                child = elem.find(f"{ns}{tag}") if ns else elem.find(tag)
                if child is not None and child.text:
                    kwargs["lapse_date"] = child.text.strip()[:10]
                    break

            # Debtor info — look in Debtor sub-element
            debtor = elem.find(f"{ns}Debtor") if ns else elem.find("Debtor")
            if debtor is not None:
                for tag, field in [("Name", "debtor_name"), ("OrganizationName", "debtor_name"),
                                   ("Address", "debtor_address"), ("StreetAddress", "debtor_address"),
                                   ("City", "debtor_city"), ("State", "debtor_state"),
                                   ("ZipCode", "debtor_zip"), ("PostalCode", "debtor_zip")]:
                    child = debtor.find(f"{ns}{tag}") if ns else debtor.find(tag)
                    if child is not None and child.text and field not in kwargs:
                        kwargs[field] = child.text.strip()

            # Secured party info
            sp = elem.find(f"{ns}SecuredParty") if ns else elem.find("SecuredParty")
            if sp is not None:
                for tag, field in [("Name", "secured_party_name"), ("OrganizationName", "secured_party_name"),
                                   ("Address", "secured_party_address"), ("StreetAddress", "secured_party_address"),
                                   ("City", "secured_party_city"), ("State", "secured_party_state"),
                                   ("ZipCode", "secured_party_zip"), ("PostalCode", "secured_party_zip")]:
                    child = sp.find(f"{ns}{tag}") if ns else sp.find(tag)
                    if child is not None and child.text and field not in kwargs:
                        kwargs[field] = child.text.strip()

            # Collateral
            for tag in ["Collateral", "CollateralDescription"]:
                child = elem.find(f"{ns}{tag}") if ns else elem.find(tag)
                if child is not None and child.text:
                    kwargs["collateral_description"] = child.text.strip()
                    break

            # Release processed element to free memory
            elem.clear()

            if not kwargs.get("filing_number"):
                continue
            if not kwargs.get("filing_type"):
                kwargs["filing_type"] = "UCC"

            yield UCCFiling(**kwargs)

    def _parse_fixed_width(self, filepath: str) -> Generator[UCCFiling, None, None]:
        """Parse fixed-width ASCII format (Florida).

        Florida's exact field positions will need to be confirmed from their
        data dictionary. This provides the framework; positions are
        provisional and should be updated after receiving the first file.
        """
        now = datetime.now(timezone.utc).isoformat()

        # Provisional field positions — update after receiving FL data dictionary
        # Format: (start, end, field_name)
        field_positions = [
            (0, 15, "filing_number"),
            (15, 20, "filing_type"),
            (20, 30, "filing_date"),
            (30, 40, "lapse_date"),
            (40, 45, "filing_status"),
            (45, 145, "debtor_name"),
            (145, 245, "debtor_address"),
            (245, 295, "debtor_city"),
            (295, 297, "debtor_state"),
            (297, 307, "debtor_zip"),
            (307, 407, "secured_party_name"),
            (407, 507, "secured_party_address"),
            (507, 557, "secured_party_city"),
            (557, 559, "secured_party_state"),
            (559, 569, "secured_party_zip"),
        ]

        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                if len(line.strip()) < 20:
                    continue  # Skip short/header lines

                kwargs = {
                    "state": "FL",
                    "source_tier": "state_bulk",
                    "source_raw": line.rstrip(),
                    "ingested_at": now,
                }

                for start, end, field_name in field_positions:
                    if end <= len(line):
                        value = line[start:end].strip()
                        if value:
                            kwargs[field_name] = value

                if not kwargs.get("filing_number"):
                    continue
                if not kwargs.get("filing_type"):
                    kwargs["filing_type"] = "UCC"

                yield UCCFiling(**kwargs)

    def fetch(self, since: Optional[str] = None) -> Generator[UCCFiling, None, None]:
        """Download and parse the state bulk data file.

        For states with download URLs that we have credentials for,
        this will download the file and parse it. For states where
        the download process is manual (e.g., requires logging into
        a portal), this expects the file to already be placed in
        the download directory.
        """
        state = self.config.abbreviation

        logger.info("Starting bulk data fetch for %s", state)

        # Check for manually-placed files first
        existing_files = self._find_latest_download()
        if existing_files:
            filepath = existing_files
            logger.info("%s: using existing download at %s", state, filepath)
        elif self.config.download_url and self._get_credentials():
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            ext = {
                "json": ".json", "csv": ".csv", "xml": ".xml",
                "tab_delimited": ".tsv", "fixed_width": ".dat",
            }.get(self.config.data_format.value, ".dat")
            filename = f"{state}_ucc_{timestamp}{ext}"

            filepath = self._download_file(self.config.download_url, filename)
            logger.info("%s: downloaded to %s", state, filepath)
        else:
            logger.warning(
                "%s: no download URL/credentials and no file found in %s. "
                "Place the bulk data file there manually.",
                state, self.download_dir,
            )
            return

        # Dispatch to format-specific parser
        count = 0
        if self.config.data_format.value == "csv":
            column_map = CSV_COLUMN_MAPS.get(state, {})
            if not column_map:
                logger.warning("%s: no CSV column map configured, using fuzzy mapping", state)
                yield from self._parse_csv_fuzzy(filepath)
                return
            for filing in self._parse_csv(filepath, column_map):
                if since and filing.filing_date and filing.filing_date < since:
                    continue
                count += 1
                yield filing

        elif self.config.data_format.value == "json":
            field_map = TX_FIELD_MAP if state == "TX" else {}
            for filing in self._parse_json_bulk(filepath, field_map):
                if since and filing.filing_date and filing.filing_date < since:
                    continue
                count += 1
                yield filing

        elif self.config.data_format.value == "xml":
            for filing in self._parse_xml_bulk(filepath):
                if since and filing.filing_date and filing.filing_date < since:
                    continue
                count += 1
                yield filing

        elif self.config.data_format.value == "tab_delimited":
            for filing in self._parse_tab_delimited(filepath):
                if since and filing.filing_date and filing.filing_date < since:
                    continue
                count += 1
                yield filing

        elif self.config.data_format.value == "fixed_width":
            for filing in self._parse_fixed_width(filepath):
                if since and filing.filing_date and filing.filing_date < since:
                    continue
                count += 1
                yield filing

        logger.info("%s: parsed %d records from bulk data", state, count)

    def _parse_csv_fuzzy(self, filepath: str) -> Generator[UCCFiling, None, None]:
        """Attempt to parse a CSV with unknown column names using fuzzy matching."""
        now = datetime.now(timezone.utc).isoformat()

        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                kwargs = {
                    "state": self.config.abbreviation,
                    "source_tier": "state_bulk",
                    "source_raw": json.dumps(row),
                    "ingested_at": now,
                }
                for key, value in row.items():
                    if not value or not value.strip():
                        continue
                    value = value.strip()
                    k = key.lower().replace(" ", "_").replace("-", "_")

                    if any(x in k for x in ["file_num", "filing_num", "file_no", "filing_no", "filenumber", "filingnum"]):
                        kwargs.setdefault("filing_number", value)
                    elif any(x in k for x in ["file_type", "filing_type", "doc_type"]):
                        kwargs.setdefault("filing_type", value)
                    elif any(x in k for x in ["file_date", "filing_date"]):
                        kwargs.setdefault("filing_date", value)
                    elif "lapse" in k:
                        kwargs.setdefault("lapse_date", value)
                    elif "status" in k:
                        kwargs.setdefault("filing_status", value)
                    elif "debtor" in k and "name" in k:
                        kwargs.setdefault("debtor_name", value)
                    elif "secured" in k and "name" in k:
                        kwargs.setdefault("secured_party_name", value)
                    elif "collateral" in k:
                        kwargs.setdefault("collateral_description", value)

                if not kwargs.get("filing_number"):
                    continue
                if not kwargs.get("filing_type"):
                    kwargs["filing_type"] = "UCC"

                yield UCCFiling(**kwargs)

    def _find_latest_download(self) -> Optional[str]:
        """Find the most recently modified file in the download directory.

        Ignores hidden files and .tmp partial downloads.
        """
        if not os.path.isdir(self.download_dir):
            return None

        files = [
            os.path.join(self.download_dir, f)
            for f in os.listdir(self.download_dir)
            if os.path.isfile(os.path.join(self.download_dir, f))
            and not f.startswith(".")
            and not f.endswith(".tmp")
        ]
        if not files:
            return None

        return max(files, key=os.path.getmtime)

    def test_connection(self) -> bool:
        """Verify credentials and download URL are accessible."""
        if not self.config.download_url:
            existing = self._find_latest_download()
            if existing:
                logger.info("%s: no download URL, but found local file: %s", self.config.abbreviation, existing)
                return True
            logger.warning("%s: no download URL configured", self.config.abbreviation)
            return False

        try:
            creds = self._get_credentials()
            auth = None
            if creds and ":" in creds:
                user, pwd = creds.split(":", 1)
                auth = (user, pwd)

            resp = requests.head(
                self.config.download_url,
                auth=auth,
                timeout=30,
                allow_redirects=True,
            )
            ok = resp.status_code < 400
            if ok:
                logger.info("%s: bulk download URL reachable", self.config.abbreviation)
            else:
                logger.warning(
                    "%s: bulk download URL returned %d",
                    self.config.abbreviation, resp.status_code,
                )
            return ok
        except Exception as e:
            logger.error("%s: connection test failed: %s", self.config.abbreviation, e)
            return False
