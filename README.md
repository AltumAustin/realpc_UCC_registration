# UCC Registration & Filing Ingestion System

**Company:** Real Finance, Inc.
**Status:** Research phase 98% complete; ingestion pipeline built; execution ready to begin

## What This Project Does

This system manages two interconnected objectives for Real Finance, Inc.:

1. **UCC Searcher Registration** — Systematically registering the company as an authorized UCC (Uniform Commercial Code) searcher across all 50 U.S. states and the District of Columbia
2. **UCC Filing Ingestion** — Continuously pulling every UCC filing from all 51 jurisdictions into a centralized, normalized SQLite database with a target latency of 3 days or less

## How It Works

### Registration Module

The registration side handles the administrative complexity of 51 different jurisdictions, each with its own portal, requirements, and fee structure. States are classified into tiers based on access model:

| Tier | States | Cost | Description |
|------|--------|------|-------------|
| **1A — Open Access** | 20 states | $0 | Free public search portals, no account needed |
| **1B — Free Registration** | 26 states + DC | $0 | Requires creating a free online account |
| **2 — Paid Subscription** | 3 states (AR, GA, ND) | $150–510/yr | Paid subscription or account required |
| **3 — Special Arrangement** | 1 state (DE) | $100–175/search | Delaware requires a certified Authorized Searcher |

The project includes tools for automated phone outreach via [Bland.ai](https://bland.ai) to state agencies, with built-in protections for two-party recording consent states. All external communications (emails, calls) require explicit human approval before execution.

### Ingestion Pipeline

The ingestion pipeline uses a hybrid 3-tier architecture to minimize cost while maintaining nationwide coverage:

```
┌─────────────────────────────────────────────────────────────┐
│                    Ingestion Scheduler                       │
│         (determines which states are due for pull)           │
├──────────┬──────────────────┬────────────────────────────────┤
│ Tier 1   │ Tier 2           │ Tier 3                         │
│ Open API │ State Bulk Subs  │ Commercial Provider            │
│ (2 st.)  │ (15 states)      │ (~34 states)                   │
│ CT, CO   │ CA, TX, KY, WV,  │ All remaining states           │
│ Socrata  │ ID, ND, MN, AR,  │ Baselayer / FCS / LexisNexis   │
│ SODA API │ IN, NY, NC, SC,  │                                │
│          │ SD, AZ, FL       │                                │
├──────────┴──────────────────┴────────────────────────────────┤
│                      Normalizer                              │
│    (dates → ISO 8601, filing types, statuses, names, ZIPs)   │
├──────────────────────────────────────────────────────────────┤
│                  SQLite Database                              │
│           (ucc_filings + ingestion_runs)                     │
├──────────────────────────────────────────────────────────────┤
│                  Audit Log (JSONL)                            │
└─────────────────────────────────────────────────────────────┘
```

**Data sources by tier:**

- **Tier 1 — Free Open APIs ($0/yr):** Connecticut and Colorado via Socrata SODA API. Daily polling, ~1 day latency.
- **Tier 2 — State Bulk Subscriptions (~$99K/yr):** 15 states offering direct bulk data downloads in CSV, XML, JSON, tab-delimited, or fixed-width formats. Polling frequency varies from daily to monthly. Texas uses a two-step process: a one-time Master Unload ($1,350) to seed the database, then Daily Filing Data Updates to stay current with the SOS.
- **Tier 3 — Commercial Provider (~$300K/yr estimated):** ~34 states without practical direct bulk access, covered by a single commercial provider API (Baselayer, First Corporate Solutions, or LexisNexis).

**Total estimated annual cost: ~$399K** (within $1M budget, with ~$601K buffer)

## Project Structure

```
ucc-registration/
├── ingestion/                    # UCC Filing Ingestion Pipeline
│   ├── __main__.py               # CLI entry point (python -m ingestion)
│   ├── runner.py                 # CLI commands: status, run, test, costs, stats
│   ├── config.py                 # Source configs for all 51 jurisdictions
│   ├── models.py                 # Data models (UCCFiling, IngestionRun) + SQLite schema
│   ├── normalizer.py             # Field normalization (dates, names, types, statuses)
│   ├── scheduler.py              # Orchestrator — routes states to adapters, batches upserts
│   └── adapters/                 # Data source adapters
│       ├── base.py               # Abstract base with retry logic
│       ├── socrata.py            # Tier 1: Socrata SODA API (CT, CO)
│       ├── state_bulk.py         # Tier 2: Bulk downloads (15 states, 5 formats)
│       └── commercial.py         # Tier 3: Commercial provider API (~34 states)
│
├── tools/                        # Registration & Outreach Automation
│   ├── bland_caller.py           # Bland.ai phone call API integration
│   ├── call_scheduler.py         # Call queue with timezone + business hours enforcement
│   └── transcript_parser.py      # Parse call transcripts and extract structured data
│
├── data/                         # Core Data Files
│   ├── ucc_requirements.json     # State-by-state registration requirements database
│   ├── state_status.json         # Real-time status tracking for all 51 jurisdictions
│   ├── activity_log.jsonl        # Append-only activity audit log
│   ├── interactions_log.jsonl    # External communications log (emails, calls)
│   ├── recording_consent_laws.json # One-party vs two-party consent by state
│   ├── call_queue.json           # Bland.ai call queue (with approval workflow)
│   ├── agent_results/            # Per-state research summaries (30+ states)
│   └── bulk_downloads/           # Tier 2 bulk data files (gitignored)
│
├── plans/                        # Project Planning
│   ├── registration_plan.md      # Tiered 6-week registration execution plan
│   ├── ingestion_plan.md         # Ingestion architecture, tiers, costs, rollout
│   ├── prerequisites_checklist.md # Master checklist of requirements
│   └── timeline.md               # Project phases and milestones
│
├── reports/                      # Status Reports & Analysis
│   ├── progress_report.md        # Current progress summary (98% research complete)
│   ├── ucc_requirements_summary.md # Human-readable requirements by state
│   ├── decisions_needed.md       # Items requiring human approval + decision log
│   ├── delaware_recommendation.md # Delaware strategy deep-dive
│   └── *_ucc_research.json       # Per-state research data (AL, CT, DE, FL, etc.)
│
├── outreach/                     # External Communications
│   ├── emails/                   # Email drafts (DE inquiry ready)
│   └── call_scripts/             # Bland.ai call scripts (DE script ready)
│
├── applications/                 # Per-state application materials (not yet populated)
├── .env.example                  # Environment variable template
└── README.md                     # Inner project docs
```

## Setup

### Prerequisites

- Python 3.10+
- `pip install requests`

### Configuration

1. Copy `.env.example` to `.env`
2. Configure the required environment variables:

```bash
# Phone outreach (Bland.ai)
BLAND_API_KEY=your_key

# Tier 1 — Optional (raises Socrata rate limits for CT/CO)
SOCRATA_APP_TOKEN=your_token

# Tier 3 — Commercial provider
UCC_COMMERCIAL_PROVIDER=baselayer        # baselayer | fcs | lexisnexis
UCC_COMMERCIAL_API_URL=https://api.example.com
UCC_COMMERCIAL_API_KEY=your_key

# Tier 2 — State bulk credentials (as needed, format: username:password)
TX_BULK_CREDENTIALS=user:pass
KY_BULK_CREDENTIALS=user:pass
# ... see .env.example for all 12 state credential variables
```

## CLI Usage

All commands run from the `ucc-registration/` directory:

```bash
# Check pipeline status — which states need ingestion, what's overdue
python -m ingestion status

# Run ingestion for all states that are due (respects polling schedule)
python -m ingestion run

# Run a specific state
python -m ingestion run --state CT

# Run all states in a tier
python -m ingestion run --tier open_api      # or: state_bulk, commercial

# Full refresh — re-download everything, ignore incremental state
python -m ingestion run --all --full

# Test all data source connections
python -m ingestion test

# View annual cost breakdown by tier
python -m ingestion costs

# View database statistics (filing counts, date ranges, state coverage)
python -m ingestion stats
```

### Production Cron Schedule

```cron
# Tier 1 (open APIs) every 6 hours
0 */6 * * * cd /path/to/ucc-registration && python -m ingestion run --tier open_api

# All tiers daily at 2 AM ET
0 2 * * * cd /path/to/ucc-registration && python -m ingestion run

# Weekly status report
0 8 * * 1 cd /path/to/ucc-registration && python -m ingestion status > /var/log/ucc_status.log
```

## Database Schema

SQLite database at `data/ucc_filings.db` (gitignored):

**`ucc_filings` table** — Normalized filing records:
- Identity: `filing_number`, `state`
- Filing details: `filing_type`, `filing_date`, `lapse_date`, `filing_status`
- Debtor: `debtor_name`, `debtor_address`, `debtor_city`, `debtor_state`, `debtor_zip`, `debtor_type`
- Secured party: `secured_party_name`, `secured_party_address`, `secured_party_city`, `secured_party_state`, `secured_party_zip`
- Collateral: `collateral_description`
- Amendments: `original_filing_number`, `amendment_type`
- Metadata: `source_tier`, `source_raw` (original JSON), `ingested_at`, `last_updated_at`
- Unique constraint: `(filing_number, state, debtor_name, secured_party_name)`
- Indexes on: state, filing_date, debtor_name, secured_party_name, filing_number, filing_status, lapse_date, ingested_at

**`ingestion_runs` table** — Audit trail:
- Tracks records fetched, new, updated, skipped, errors per run per state

**Expected volume:** ~145K new records/month (~1.7M/year). SQLite handles this comfortably; migration to PostgreSQL is straightforward if needed.

## Current Status

### What's Complete
- Research on 50/51 jurisdictions (Massachusetts pending)
- Full tiered registration plan for all 51 jurisdictions
- Ingestion pipeline code (scheduler, normalizer, all 3 adapter tiers)
- CLI tooling with 5 commands (status, run, test, costs, stats)
- Bland.ai phone outreach automation (caller, scheduler, transcript parser)
- Delaware deep-dive analysis with recommendation
- Approved outreach materials (DE email draft, DE call script)
- State-by-state requirements database (`ucc_requirements.json`)
- Recording consent law classification for all states

### What's Pending
- Massachusetts research (1 remaining state)
- Execute Delaware outreach (approved, not yet sent)
- Create free accounts in 6 priority states (AK, CA, CO, CT, FL, GA)
- Arkansas INA subscription ($150/yr — approved)
- Commercial provider contract negotiation (Tier 3)
- State bulk data subscription provisioning (Tier 2 credentials)
- Live testing of Socrata adapters against CT and CO
- Fee verification calls for states with discrepancies (AL, AZ, FL)

### Approval Gates

The system enforces human approval before any external action:
- Sending emails to state agencies
- Placing Bland.ai phone calls
- Submitting applications
- Making payments

See `reports/decisions_needed.md` for the current decision log.

## Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| **Hybrid 3-tier ingestion** | Minimizes cost while achieving nationwide 3-day latency SLA |
| **SQLite** | Simple, portable, zero-config; sufficient for ~1.7M records/year |
| **JSONL audit logs** | Append-only for compliance; easy to grep and process |
| **Raw source preservation** | Every record stores original JSON in `source_raw` for debugging/disputes |
| **Polling over webhooks** | Simpler infrastructure; most state sources don't offer webhooks |
| **Modular adapters** | Each data source type is isolated; easy to add new sources |
| **Bland.ai for outreach** | AI-powered phone calls with recording consent handling |
| **Human approval gates** | All external-facing actions require explicit sign-off |

## Company Information

- **Company:** Real Finance, Inc.
- **Incorporated in:** Delaware
- **Principal Office:** 9240 SW 72ND ST STE 114, MIAMI, FL 33173
- **Authorized Representative:** Austin, Chief Legal Officer
- **Contact:** austin@realpc.ai | (949) 887-5775
