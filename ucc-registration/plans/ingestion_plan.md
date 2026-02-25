# UCC Filing Ingestion Plan

## Objective

Continuously ingest **every UCC filing from all 51 jurisdictions** (50 states + DC) into a centralized database within **≤3 days of filing**, at a total annual cost **≤$1,000,000**.

## Architecture: Hybrid 3-Tier System

```
┌─────────────────────────────────────────────────────────────┐
│                    Ingestion Scheduler                       │
│   (runs daily via cron, determines which states are due)     │
├──────────┬──────────────────┬────────────────────────────────┤
│ Tier 1   │ Tier 2           │ Tier 3                         │
│ Open API │ State Bulk Subs  │ Commercial Provider            │
│ (2 st.)  │ (15 states)      │ (~34 states)                   │
├──────────┼──────────────────┼────────────────────────────────┤
│ CT, CO   │ CA, TX, KY, WV,  │ AL, AK, DC, DE, GA, HI, IA,  │
│          │ ID, ND, MN, AR,  │ IL, KS, LA, ME, MD, MA, MI,   │
│ Socrata  │ IN, NY, NC, SC,  │ MS, MO, MT, NE, NV, NH, NJ,  │
│ SODA API │ SD, AZ, FL       │ NM, OH, OK, OR, PA, RI, TN,   │
│          │                  │ UT, VT, VA, WA, WI, WY         │
├──────────┼──────────────────┼────────────────────────────────┤
│    ↓          ↓                    ↓                         │
│              Normalizer                                      │
│   (dates, names, types, statuses → common format)            │
│                    ↓                                         │
│            SQLite Database                                   │
│         (data/ucc_filings.db)                                │
│                    ↓                                         │
│           Ingestion Log                                      │
│       (data/ingestion_log.jsonl)                             │
└─────────────────────────────────────────────────────────────┘
```

## Tier Details

### Tier 1: Free Open Data APIs — $0/year

| State | Source | Frequency | Latency | Format |
|-------|--------|-----------|---------|--------|
| CT | data.ct.gov SODA API | Daily | ~1 day | JSON |
| CO | data.colorado.gov SODA API | Daily | ~1.5 days | JSON |

- No authentication required (optional app token raises rate limits)
- Pagination via `$limit`/`$offset`, incremental via `$where` date filter
- Most reliable and cheapest data source

### Tier 2: State Bulk Subscriptions — ~$98,830/year

| State | Format | Frequency | Latency | Annual Cost |
|-------|--------|-----------|---------|-------------|
| CA | XML | Weekly | ≤3 days | $0 (free updates) |
| TX | JSON | Daily | 1 day | $1,350 (Master Unload) |
| KY | CSV | Daily | 1 day | $18,000 |
| WV | CSV | Weekly | ≤3 days | ~$5,000 |
| ID | Tab-delimited | Biweekly | ≤3 days | $3,250 |
| ND | CSV | Biweekly | ≤3 days | $480 |
| MN | CSV | Weekly | ≤3 days | ~$5,000 |
| AR | CSV | Weekly | ≤3 days | $150 |
| IN | XML (IACA v4.0) | Weekly | ≤3 days | ~$2,000 |
| NY | XML | Weekly | ≤3 days | $3,600 |
| NC | CSV | Weekly | ≤3 days | ~$5,000 |
| SC | CSV | Weekly | ≤3 days | $54,000 |
| SD | CSV | Weekly | ≤3 days | ~$1,000 |
| AZ | CSV | Monthly | ≤3 days* | ~$2,000 |
| FL | Fixed-width ASCII | Daily | 1 day | ~$3,000 |

*AZ monthly cadence may exceed 3-day target; commercial provider used as backup.

**Action items to activate Tier 2:**
1. Subscribe to each state's bulk data program
2. Set up download credentials and store in `.env`
3. For manual-download states, establish a process to place files in `data/bulk_downloads/{STATE}/`

**Texas two-step process:**
1. **Purchase Master Unload ($1,350)** — one-time purchase from the Texas SOS containing
   all historical UCC filings. This seeds the local database with the complete SOS filing index.
2. **Subscribe to Daily Filing Data Updates** — ongoing subscription to receive daily
   incremental JSON files. These are downloaded and applied against the Master Unload
   to keep the local database current with the SOS database.

### Tier 3: Commercial Provider — ~$300,000/year (estimated)

Covers ~34 states that don't offer practical direct bulk access.

**Recommended providers (choose one):**

| Provider | Coverage | API Style | Estimated Cost | Strengths |
|----------|----------|-----------|----------------|-----------|
| **Baselayer** | 50 states | REST/JSON | $200K-400K | API-first, modern, daily refresh |
| **First Corporate Solutions** | 50 states | REST/JSON | $200K-400K | Purchases direct from states |
| **LexisNexis** | 48 states daily | REST/JSON | $300K-500K | Deepest archive, most complete |

**Action items:**
1. Contact all three providers for quotes
2. Negotiate a nationwide daily data feed contract
3. Configure API credentials in `.env`

## Total Estimated Annual Cost

| Tier | Cost |
|------|------|
| Tier 1 (Open APIs) | $0 |
| Tier 2 (State Subscriptions) | ~$98,830 |
| Tier 3 (Commercial Provider) | ~$300,000 |
| **Total** | **~$398,830** |
| **Budget remaining** | **~$601,170** |

The ~$600K buffer can absorb:
- Higher-than-estimated commercial provider costs
- Additional state subscriptions if direct access becomes available
- Infrastructure/compute costs
- Potential price increases

## Expected Latency

| Source | States | Typical Latency |
|--------|--------|----------------|
| Socrata API (daily poll) | CT, CO | 1 day |
| State daily downloads | TX, KY, FL | 1 day |
| State weekly downloads | CA, WV, MN, AR, IN, NY, NC, SC, SD | 1-3 days |
| State biweekly downloads | ID, ND | 1-3 days |
| Commercial provider (daily) | ~34 states | 1-3 days |

**All states within the ≤3 day target.**

## Pipeline Operations

### CLI Commands

```bash
# From ucc-registration/ directory:

# Check which states need ingestion
python -m ingestion status

# Run all due states (respects polling schedule)
python -m ingestion run

# Run a specific state
python -m ingestion run --state CT

# Run all states in a tier
python -m ingestion run --tier open_api

# Full refresh (re-download everything)
python -m ingestion run --all --full

# Test all data source connections
python -m ingestion test

# View cost breakdown
python -m ingestion costs

# View database statistics
python -m ingestion stats
```

### Cron Schedule (Production)

```cron
# Run Tier 1 (open APIs) every 6 hours
0 */6 * * * cd /path/to/ucc-registration && python -m ingestion run --tier open_api

# Run Tier 2 + 3 daily at 2 AM ET
0 2 * * * cd /path/to/ucc-registration && python -m ingestion run

# Full status check weekly
0 8 * * 1 cd /path/to/ucc-registration && python -m ingestion status > /var/log/ucc_status.log
```

## Database Schema

SQLite database at `data/ucc_filings.db` with:

- **ucc_filings** table: All filing records with normalized fields
  - Indexed on: state, filing_date, debtor_name, secured_party_name, filing_number, filing_status, lapse_date
  - Unique constraint: (filing_number, state, debtor_name, secured_party_name)
  - Stores original raw record in `source_raw` column for audit

- **ingestion_runs** table: Audit trail of every ingestion run
  - Tracks: records fetched, new, updated, skipped, errors

- **Expected volume**: ~145,000 new records/month (~1.7M/year)
  - SQLite handles this comfortably; migrate to PostgreSQL if concurrent access or volume demands increase

## Rollout Plan

### Phase 1: Immediate (Week 1)
- [x] Build ingestion pipeline code
- [ ] Test Socrata adapters against CT and CO (free, no credentials needed)
- [ ] Verify database schema and normalization with real data

### Phase 2: Open APIs Live (Week 2)
- [ ] Set up cron job for CT and CO daily polling
- [ ] Register for Socrata app token (raises rate limits)
- [ ] Monitor ingestion logs for errors

### Phase 3: Commercial Provider (Weeks 3-6)
- [ ] Contact Baselayer, FCS, and LexisNexis for quotes
- [ ] Negotiate and sign contract
- [ ] Configure API credentials and test connection
- [ ] Run initial full pull for all Tier 3 states
- [ ] Set up daily cron

### Phase 4: State Subscriptions (Weeks 4-8)
- [ ] Subscribe to CA weekly downloads (free)
- [ ] Purchase TX Master Unload ($1,350) and subscribe to Daily Filing Data Updates
- [ ] Subscribe to remaining Tier 2 states in priority order:
  1. KY (daily, $18K/yr)
  2. FL (daily, ~$3K/yr)
  3. NY ($3,600/yr)
  4. WV, MN, NC, IN, AR, ND, SD, ID (~$21K/yr combined)
  5. SC ($54K/yr) — evaluate if commercial provider already covers adequately
  6. AZ ($2K/yr)

### Phase 5: Steady State (Week 8+)
- [ ] All 51 jurisdictions ingesting on schedule
- [ ] Monitor latency SLA (≤3 days) via `python -m ingestion status`
- [ ] Cross-reference Tier 2 direct data against Tier 3 commercial data for quality assurance
- [ ] Evaluate migration to PostgreSQL if needed
