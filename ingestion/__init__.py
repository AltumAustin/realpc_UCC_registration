"""
UCC Filing Data Ingestion Pipeline

Hybrid system for continuous nationwide UCC filing ingestion.
Combines free state APIs, paid state bulk data subscriptions,
and commercial provider feeds to achieve ≤3 day latency across
all 51 jurisdictions.

Data Source Tiers:
  Tier 1 - Free Open Data APIs (CT, CO): Polled daily, ~$0/year
  Tier 2 - State Bulk Subscriptions (CA, TX, KY, etc.): Downloaded on schedule
  Tier 3 - Commercial Provider (remaining states): Polled daily via API
"""

__version__ = "0.1.0"
