"""
Ingestion configuration: maps each jurisdiction to its data source,
polling schedule, estimated cost, and expected latency.
"""

import json
import os
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class SourceTier(str, Enum):
    OPEN_API = "open_api"            # Free state open data APIs (Socrata SODA)
    STATE_BULK = "state_bulk"        # Direct state bulk data subscription
    COMMERCIAL = "commercial"        # Commercial provider API


class PollFrequency(str, Enum):
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"


class DataFormat(str, Enum):
    JSON = "json"
    CSV = "csv"
    XML = "xml"
    TAB_DELIMITED = "tab_delimited"
    FIXED_WIDTH = "fixed_width"


@dataclass
class StateSourceConfig:
    """Configuration for a single state's data source."""
    state: str
    abbreviation: str
    tier: SourceTier
    poll_frequency: PollFrequency
    data_format: DataFormat
    expected_latency_days: float
    annual_cost_usd: float
    api_endpoint: Optional[str] = None
    api_dataset_id: Optional[str] = None
    download_url: Optional[str] = None
    requires_auth: bool = False
    auth_env_var: Optional[str] = None
    notes: str = ""
    enabled: bool = True
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None


# Tier 1: Free Open Data APIs
TIER1_SOURCES = {
    "CT": StateSourceConfig(
        state="Connecticut",
        abbreviation="CT",
        tier=SourceTier.OPEN_API,
        poll_frequency=PollFrequency.DAILY,
        data_format=DataFormat.JSON,
        expected_latency_days=1.0,
        annual_cost_usd=0,
        api_endpoint="https://data.ct.gov/resource/xfev-8smz.json",
        api_dataset_id="xfev-8smz",
        notes="Socrata SODA API. Nightly updates. Active liens only (not lapsed >1yr).",
    ),
    "CO": StateSourceConfig(
        state="Colorado",
        abbreviation="CO",
        tier=SourceTier.OPEN_API,
        poll_frequency=PollFrequency.DAILY,
        data_format=DataFormat.JSON,
        expected_latency_days=1.5,
        annual_cost_usd=0,
        api_endpoint="https://data.colorado.gov/resource/wffy-3uut.json",
        api_dataset_id="wffy-3uut",
        notes="Socrata SODA API. Daily to weekly updates depending on dataset.",
    ),
}

# Tier 2: State Bulk Data Subscriptions
TIER2_SOURCES = {
    "CA": StateSourceConfig(
        state="California",
        abbreviation="CA",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.WEEKLY,
        data_format=DataFormat.XML,
        expected_latency_days=7.0,
        annual_cost_usd=0,
        download_url="https://bpd.cdn.sos.ca.gov/ucc/",
        notes="Free weekly XML downloads. Master file $100 (data only). Weekly updates free.",
        contact_email="UCChelp@sos.ca.gov",
    ),
    "TX": StateSourceConfig(
        state="Texas",
        abbreviation="TX",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.DAILY,
        data_format=DataFormat.JSON,
        expected_latency_days=1.0,
        annual_cost_usd=1350,
        download_url="https://www.sos.state.tx.us/ucc/bulk-order.shtml",
        requires_auth=True,
        auth_env_var="TX_BULK_CREDENTIALS",
        notes="$1,350 master file. Daily JSON updates available.",
        contact_phone="(512) 463-5555",
    ),
    "KY": StateSourceConfig(
        state="Kentucky",
        abbreviation="KY",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.DAILY,
        data_format=DataFormat.CSV,
        expected_latency_days=1.0,
        annual_cost_usd=18000,
        download_url="https://www.sos.ky.gov/bus/Pages/Bulk-Data-Service.aspx",
        requires_auth=True,
        auth_env_var="KY_BULK_CREDENTIALS",
        notes="$1,500/month plus $75 KY.gov subscription fee. Daily downloads.",
        contact_phone="(502) 564-3490",
    ),
    "WV": StateSourceConfig(
        state="West Virginia",
        abbreviation="WV",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.WEEKLY,
        data_format=DataFormat.CSV,
        expected_latency_days=3.0,
        annual_cost_usd=5000,
        download_url="https://apps.wv.gov/sos/bulkdata/",
        requires_auth=True,
        auth_env_var="WV_BULK_CREDENTIALS",
        notes="Weekly CSV (3 files: Debtors, SecuredParties, Documents). State law requires weekly minimum.",
    ),
    "ID": StateSourceConfig(
        state="Idaho",
        abbreviation="ID",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.BIWEEKLY,
        data_format=DataFormat.TAB_DELIMITED,
        expected_latency_days=3.0,
        annual_cost_usd=3250,
        download_url="https://sos.idaho.gov/ucc/subscriptions.html",
        requires_auth=True,
        auth_env_var="ID_BULK_CREDENTIALS",
        notes="$125/extract, bi-weekly (every other Monday). Full replacement each extract. Collateral not included.",
    ),
    "ND": StateSourceConfig(
        state="North Dakota",
        abbreviation="ND",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.BIWEEKLY,
        data_format=DataFormat.CSV,
        expected_latency_days=3.0,
        annual_cost_usd=480,
        download_url="https://www.sos.nd.gov/business/lien-filings-ucc/data-and-report-subscriptions",
        requires_auth=True,
        auth_env_var="ND_BULK_CREDENTIALS",
        notes="$40/month. Data on 1st and 16th of each month.",
    ),
    "MN": StateSourceConfig(
        state="Minnesota",
        abbreviation="MN",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.WEEKLY,
        data_format=DataFormat.CSV,
        expected_latency_days=3.0,
        annual_cost_usd=5000,
        download_url="https://www.sos.mn.gov/business-liens/business-liens-data/ucc-data-available-for-purchase/",
        requires_auth=True,
        auth_env_var="MN_BULK_CREDENTIALS",
        notes="CSV comma-delimited. Initial dataset + weekly subscription. License agreement required.",
    ),
    "AR": StateSourceConfig(
        state="Arkansas",
        abbreviation="AR",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.WEEKLY,
        data_format=DataFormat.CSV,
        expected_latency_days=3.0,
        annual_cost_usd=150,
        download_url="https://portal.arkansas.gov/service/ar-ucc-bulk-records-data-download/",
        requires_auth=True,
        auth_env_var="AR_INA_CREDENTIALS",
        notes="$150/year INA subscription + transaction fees.",
    ),
    "IN": StateSourceConfig(
        state="Indiana",
        abbreviation="IN",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.WEEKLY,
        data_format=DataFormat.XML,
        expected_latency_days=3.0,
        annual_cost_usd=2000,
        api_endpoint="https://inbiz.in.gov/",
        download_url="https://inbiz.in.gov/Inbiz/BulkDataServices/Index",
        requires_auth=True,
        auth_env_var="IN_INBIZ_CREDENTIALS",
        notes="IACA v4.0 XML via INBiz portal. RESTful API.",
    ),
    "NY": StateSourceConfig(
        state="New York",
        abbreviation="NY",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.WEEKLY,
        data_format=DataFormat.XML,
        expected_latency_days=3.0,
        annual_cost_usd=3600,
        download_url="https://appext20.dos.ny.gov/subscription/",
        requires_auth=True,
        auth_env_var="NY_SUBSCRIPTION_CREDENTIALS",
        notes="$300/month. TIFF images available 5 business days after filing. XML bulk filing system for data.",
    ),
    "NC": StateSourceConfig(
        state="North Carolina",
        abbreviation="NC",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.WEEKLY,
        data_format=DataFormat.CSV,
        expected_latency_days=3.0,
        annual_cost_usd=5000,
        download_url="https://www.sosnc.gov/online_services/data_subscriptions",
        requires_auth=True,
        auth_env_var="NC_SUBSCRIPTION_CREDENTIALS",
        notes="Contract-based. Contact subscription@sosnc.gov.",
        contact_email="subscription@sosnc.gov",
    ),
    "SC": StateSourceConfig(
        state="South Carolina",
        abbreviation="SC",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.WEEKLY,
        data_format=DataFormat.CSV,
        expected_latency_days=3.0,
        annual_cost_usd=54000,
        download_url="https://scdgs.sc.gov/service/secretary-state-bulk-data-images-and-notary-registration",
        requires_auth=True,
        auth_env_var="SC_BULK_CREDENTIALS",
        notes="$4,500/month for weekly UCC filings. XML web service API also available.",
    ),
    "SD": StateSourceConfig(
        state="South Dakota",
        abbreviation="SD",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.WEEKLY,
        data_format=DataFormat.CSV,
        expected_latency_days=3.0,
        annual_cost_usd=1000,
        download_url="https://sdsos.gov/Business-Services/database-downloads.aspx",
        requires_auth=True,
        auth_env_var="SD_BULK_CREDENTIALS",
        notes="Subscription-based. Contact for pricing and format details.",
    ),
    "AZ": StateSourceConfig(
        state="Arizona",
        abbreviation="AZ",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.MONTHLY,
        data_format=DataFormat.CSV,
        expected_latency_days=3.0,
        annual_cost_usd=2000,
        notes="Monthly subscription or single request. 5 options for UCC Filing Index.",
    ),
    "FL": StateSourceConfig(
        state="Florida",
        abbreviation="FL",
        tier=SourceTier.STATE_BULK,
        poll_frequency=PollFrequency.DAILY,
        data_format=DataFormat.FIXED_WIDTH,
        expected_latency_days=1.0,
        annual_cost_usd=3000,
        notes="Daily + quarterly fixed-length ASCII. Public records request may be needed for UCC.",
    ),
}

# All remaining states go through the commercial provider.
# These are states without practical direct bulk data access.
ALL_STATES = [
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "DC", "FL",
    "GA", "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME",
    "MD", "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH",
    "NJ", "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI",
    "SC", "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY",
]

STATE_NAMES = {
    "AL": "Alabama", "AK": "Alaska", "AZ": "Arizona", "AR": "Arkansas",
    "CA": "California", "CO": "Colorado", "CT": "Connecticut", "DE": "Delaware",
    "DC": "District of Columbia", "FL": "Florida", "GA": "Georgia", "HI": "Hawaii",
    "ID": "Idaho", "IL": "Illinois", "IN": "Indiana", "IA": "Iowa",
    "KS": "Kansas", "KY": "Kentucky", "LA": "Louisiana", "ME": "Maine",
    "MD": "Maryland", "MA": "Massachusetts", "MI": "Michigan", "MN": "Minnesota",
    "MS": "Mississippi", "MO": "Missouri", "MT": "Montana", "NE": "Nebraska",
    "NV": "Nevada", "NH": "New Hampshire", "NJ": "New Jersey", "NM": "New Mexico",
    "NY": "New York", "NC": "North Carolina", "ND": "North Dakota", "OH": "Ohio",
    "OK": "Oklahoma", "OR": "Oregon", "PA": "Pennsylvania", "RI": "Rhode Island",
    "SC": "South Carolina", "SD": "South Dakota", "TN": "Tennessee", "TX": "Texas",
    "UT": "Utah", "VT": "Vermont", "VA": "Virginia", "WA": "Washington",
    "WV": "West Virginia", "WI": "Wisconsin", "WY": "Wyoming",
}


def get_tier3_states():
    """States covered by the commercial provider (everything not in Tier 1 or 2)."""
    direct_states = set(TIER1_SOURCES.keys()) | set(TIER2_SOURCES.keys())
    return [s for s in ALL_STATES if s not in direct_states]


def get_all_source_configs():
    """Return a dict of all state source configs, keyed by abbreviation."""
    configs = {}
    configs.update(TIER1_SOURCES)
    configs.update(TIER2_SOURCES)

    # Generate configs for Tier 3 (commercial provider) states
    for abbr in get_tier3_states():
        configs[abbr] = StateSourceConfig(
            state=STATE_NAMES[abbr],
            abbreviation=abbr,
            tier=SourceTier.COMMERCIAL,
            poll_frequency=PollFrequency.DAILY,
            data_format=DataFormat.JSON,
            expected_latency_days=2.0,
            annual_cost_usd=0,  # Covered by commercial provider contract
            requires_auth=True,
            auth_env_var="COMMERCIAL_PROVIDER_API_KEY",
            notes="Via commercial provider API (Baselayer/FCS/LexisNexis).",
        )
    return configs


def get_annual_cost_breakdown():
    """Calculate total annual cost by tier."""
    tier1_cost = sum(s.annual_cost_usd for s in TIER1_SOURCES.values())
    tier2_cost = sum(s.annual_cost_usd for s in TIER2_SOURCES.values())

    # Commercial provider contract estimate
    tier3_states = get_tier3_states()
    tier3_estimated_cost = 300_000  # Estimated annual contract

    return {
        "tier1_open_api": {
            "states": list(TIER1_SOURCES.keys()),
            "count": len(TIER1_SOURCES),
            "annual_cost": tier1_cost,
        },
        "tier2_state_bulk": {
            "states": list(TIER2_SOURCES.keys()),
            "count": len(TIER2_SOURCES),
            "annual_cost": tier2_cost,
        },
        "tier3_commercial": {
            "states": tier3_states,
            "count": len(tier3_states),
            "annual_cost_estimated": tier3_estimated_cost,
        },
        "total_estimated_annual": tier1_cost + tier2_cost + tier3_estimated_cost,
    }


@dataclass
class IngestionSettings:
    """Global ingestion pipeline settings."""
    db_path: str = "data/ucc_filings.db"
    download_dir: str = "data/bulk_downloads"
    log_path: str = "data/ingestion_log.jsonl"
    max_retries: int = 3
    retry_backoff_seconds: float = 2.0
    request_timeout_seconds: int = 120
    socrata_app_token: Optional[str] = None
    commercial_provider: str = "baselayer"  # baselayer | fcs | lexisnexis
    commercial_api_base_url: str = ""
    commercial_api_key: Optional[str] = None
    batch_size: int = 5000  # Records per API page/batch

    @classmethod
    def from_env(cls):
        return cls(
            db_path=os.environ.get("UCC_DB_PATH", "data/ucc_filings.db"),
            download_dir=os.environ.get("UCC_DOWNLOAD_DIR", "data/bulk_downloads"),
            log_path=os.environ.get("UCC_INGESTION_LOG", "data/ingestion_log.jsonl"),
            socrata_app_token=os.environ.get("SOCRATA_APP_TOKEN"),
            commercial_provider=os.environ.get("UCC_COMMERCIAL_PROVIDER", "baselayer"),
            commercial_api_base_url=os.environ.get("UCC_COMMERCIAL_API_URL", ""),
            commercial_api_key=os.environ.get("UCC_COMMERCIAL_API_KEY"),
            batch_size=int(os.environ.get("UCC_BATCH_SIZE", "5000")),
        )
