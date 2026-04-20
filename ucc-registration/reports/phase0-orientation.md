# Phase 0 — Orientation Summary

**Date:** 2026-04-20
**Branch:** `claude/add-ucc-filings-search-miAyM`
**Author:** Claude (engagement lead)

This is the Phase 0 deliverable from the nationwide UCC ingestion brief: a read
of the existing repo so we can plan Phase 1 with open eyes. No code changes
yet — this is diagnosis only.

---

## 1. What Exists Today

The code lives at `ucc-registration/` and follows a clean three-tier adapter
pattern. Key components:

| Component | Path | Role |
|---|---|---|
| CLI | `ingestion/runner.py` | `status`, `run`, `test`, `costs`, `stats` subcommands |
| Config | `ingestion/config.py` | Per-jurisdiction source configs for all 51 |
| Storage | `ingestion/models.py` | SQLite schema + `UCCFiling` dataclass |
| Normalizer | `ingestion/normalizer.py` | Date/name/type/status/zip standardization |
| Scheduler | `ingestion/scheduler.py` | Orchestrates fetch → normalize → upsert; thread-pool capable |
| Tier 1 adapter | `adapters/socrata.py` | Socrata SODA for CT + CO |
| Tier 2 adapter | `adapters/state_bulk.py` (918 LOC) | 15 states across CSV/XML/TSV/fixed-width/JSON |
| Tier 3 adapter | `adapters/commercial.py` | Pluggable backend (Baselayer / FCS / LexisNexis) |
| Audit | `data/ingestion_log.jsonl` | Append-only event log |
| Deploy | `deploy/` + `deploy/terraform/` | EC2 + systemd + AWS Secrets Manager |
| Outreach tooling | `tools/bland_caller.py`, `tools/call_scheduler.py`, `tools/transcript_parser.py` | Gated behind human approval |

Design decisions worth preserving:
- Natural key `(filing_number, state)` enforced via `UNIQUE` constraint (see
  caveat in §4 — this is too narrow for real UCC data).
- Raw source blob retained in `source_raw` for every record.
- Batch upserts inside explicit SQLite transactions with per-record error
  capture, so one bad row doesn't kill a run.
- Retries restricted to transient HTTP errors (429/5xx, connection/timeout);
  parse errors and auth failures fail fast.
- Incremental pulls use `MAX(filing_date) WHERE state=?` as the cutoff,
  with a `--full` flag to override.

---

## 2. What Works Today

Verified on 2026-04-20:

- CLI boots: `python -m ingestion status`, `stats`, `costs` all run and
  produce sensible output.
- Schema initializes on first run (`data/ucc_filings.db` auto-created, WAL
  mode, indexes per the DDL).
- Scheduler's config validation logs clear warnings when
  `UCC_COMMERCIAL_API_URL` / `UCC_COMMERCIAL_API_KEY` are unset — no
  crashes, just degradation.
- Cost breakdown totals **$403,830/year** (Tier 1 $0 + Tier 2 $103,830 +
  Tier 3 ~$300,000 est.), under the $1M/yr ceiling in `ingestion_plan.md`.
- All 51 jurisdictions have a `StateSourceConfig` and route to an adapter.

Status as of today: **zero filings in the database** (`total_filings: 0`,
`states_covered: 0`). No ingestion has ever been executed against any live
source. Every state shows as `** DUE **` / `last_ingestion=never`.

---

## 3. What's Stubbed or Broken

### 3a. Stubbed / not-yet-live
- **Commercial provider** — no provider selected, no contract, env vars are
  placeholders (`https://api.example.com`). 34 states fail at runtime until
  this is resolved. This is the single biggest Phase 2 gap.
- **Tier 2 credentials** — all 12 `*_BULK_CREDENTIALS` env vars unset. Bulk
  endpoints will 401 until each is provisioned.
- **Several Tier 2 column maps are provisional** — `state_bulk.py:192`
  explicitly notes ID's column names are "provisional — update after
  receiving first data file." Same risk likely applies to KY, WV, MN, NC,
  SC, SD, AZ since no actual file has been parsed end-to-end.
- **WV multi-file join** — WV delivers Documents + Debtors + SecuredParties
  as three separate files. Current `CSV_COLUMN_MAPS["WV"]` maps only
  Documents; no merge logic exists, so debtor/secured-party fields will be
  null for WV records.
- **Texas two-step flow** — config and field map exist, but the Master
  Unload seeding path vs. Daily Update path is not exercised (or obviously
  differentiated) in `state_bulk.py`.
- **No `search` / `watch` / FastAPI** — the retrieval and monitoring
  deliverables (Phase 5) are greenfield.
- **No `backfill.py`** — the 5-year historical pull (Phase 3) has no
  dedicated script; today's incremental path only chases
  `MAX(filing_date)` forward.

### 3b. Likely-broken / data-quality issues

1. **Colorado Socrata field map is semantically wrong.**
   `adapters/socrata.py:48` maps `documenttype → collateral_description`.
   `documenttype` on the CO dataset is the filing-type code ("UCC", "FTL",
   etc.), not free-text collateral. Running CO today would populate the
   collateral column with filing types, poisoning every downstream query.

2. **Most Tier 2 CSV maps have no `collateral` column at all.**
   Grep shows collateral mapping only in TX field map (`collateral`), CT
   Socrata map (`tx_lien_descript`), CO map (the broken one above), and two
   inline cases in XML/fuzzy fallback paths. KY, WV, ND, MN, NC, SC, SD,
   AR, ID, AZ maps have no collateral key — either the state genuinely
   doesn't deliver collateral in its bulk feed (ID config already says as
   much), or the map is incomplete. This is the central Phase 1 question.

3. **Natural key is too narrow for UCC reality.**
   DDL is `UNIQUE(filing_number, state)`. A single UCC-1 commonly has
   multiple debtors and multiple secured parties. The current schema
   stores **one row per filing**, which forces one debtor / one
   secured-party pair per filing and silently drops the rest. The
   `README.md` even claims the unique key is
   `(filing_number, state, debtor_name, secured_party_name)`, which is
   inconsistent with the DDL. Either:
   - Keep one-row-per-filing and pull parties into `debtors` /
     `secured_parties` child tables (preferred — lossless), **or**
   - Widen the unique key to the README's (which still loses
     3-debtor/1-SP cases and makes de-dup thrashy).
   This is the biggest schema decision to resolve **before** the 5-year
   backfill, because re-shaping after ingest is painful.

4. **Normalizer does not enforce `collateral_description IS NOT NULL` or
   capture a reason code.** The Phase 3 acceptance criterion demands a
   `pending_collateral` audit row for any missing-collateral record; that
   mechanism doesn't exist yet.

5. **Tests aren't running.**
   `python3 -m unittest discover tests` finds 0 tests (files exist:
   `test_models.py`, `test_normalizer.py`, `test_parsers.py`). pytest is in
   `requirements.txt`? No — only `requests`, `ijson`, `boto3`. No pytest,
   no `pytest.ini`/`conftest.py`, no CI. I can't verify the existing test
   assertions run green without adding dev dependencies and a runner.

6. **`data/ingestion_log.jsonl` path collision risk.** The scheduler
   writes to `self.log_path` from settings (defaults to
   `data/ingestion_log.jsonl`). `data/activity_log.jsonl` already exists
   (registration audit log) — these are separate files with similar names,
   easy to conflate operationally.

### 3c. Documentation vs. reality mismatches

- `README.md` claims "~$399K/year" total; the cost command now totals
  `$403,830` after a $5K line-item drift.
- `reports/progress_report.md` is dated **2026-02-14**; several "pending"
  items (MA research, DE outreach) are still pending per the same file but
  the project is now April 2026.
- `README.md` unique-key claim disagrees with the DDL (see §3b.3).

---

## 4. Top 5 Risks (in priority order)

| # | Risk | Why it matters | Phase where it bites |
|---|---|---|---|
| 1 | **Collateral coverage per-state is unverified.** Most Tier 2 maps lack a collateral column; CO is mis-mapped; no state has had a real-data round-trip. | Collateral text is the central deliverable. If half the states don't return it, we need OCR or a commercial fallback — and we need to know which before signing any contract. | Phase 1, blocks everything downstream |
| 2 | **Commercial provider is a placeholder.** 34 states (67%) have no live data path. No vendor selected, no pricing validated, no API contract confirmed. | Without a real Tier 3, the 5-year backfill is impossible for two-thirds of jurisdictions. | Phase 2 |
| 3 | **Schema loses multi-party filing data.** One row per filing silently drops secondary debtors/secured parties. | Re-shaping after a 5-year backfill means re-pulling every source — expensive and slow. Decide before Phase 3. | Phase 3 |
| 4 | **CO field map is semantically wrong.** `documenttype → collateral_description` will write garbage collateral for every CO record. | Any CO search results would be misleading; confidence in the whole DB drops. | Phase 1 fix |
| 5 | **No 5-year backfill mechanism; no idempotent restart.** Current incremental path only chases the latest filing date; there's no script that can be resumed after interruption. | Phase 3 acceptance criterion (≥95% of 5-year filings per state) is unreachable without this. | Phase 3 |

Secondary risks tracked but lower priority:
- No working test runner / no CI → regressions go undetected.
- Provisional column maps (ID and likely others) → parsers will silently
  produce all-null rows until we eyeball a real file.
- PII handling: stdout logs in fuzzy CSV fallback may leak debtor details;
  need to grep the log paths once we have real data.
- `README.md` vs. DDL drift on the unique key will mislead anyone onboarding.

---

## 5. Proposed Adjustments Before Phase 1

I'm not making any code changes in Phase 0. But the following should be
decided before or during Phase 1 so we don't pile up rework:

1. **Resolve schema shape (one row per filing vs. child tables).** My
   recommendation: add `filing_debtors` and `filing_secured_parties` child
   tables now; keep `ucc_filings` as the parent (one row per filing),
   collateral and filing_type on the parent. Uses the same upsert pattern.
   Cost: ~2 days of schema + adapter changes + a migration for future
   back-compat. Benefit: lossless forever.
2. **Answer the five Phase-2 questions from §6 of the brief** (commercial
   aggregator choice, budget ceiling, 5-year window shape, aliases, hit
   routing). Blocking Phase 2 start; mostly blocking Phase 1 budget.
3. **Add a minimal test runner (pytest + a `pytest.ini` + one GitHub
   Action)** so we know if normalizer/parser tests pass. ~0.5 day.
4. **Fix the CO Socrata field map** — at minimum set
   `collateral_description` to `None` and add a proper
   `cta_description`/`collateral_text` key if one exists in the CO
   dataset. Trivial fix but do it before anyone runs CO.
5. **Decide how to treat "collateral not delivered in bulk feed".** For
   states like ID where the state explicitly excludes collateral from the
   subscription, we need a reason code (`not_in_feed`, `image_only`,
   `paid_retrieval_required`) recorded per filing, not silent nulls.

---

## 6. Questions Back to Austin

From §6 of the brief — these block Phase 2, so answers would unlock more
of Phase 1 planning:

1. **Commercial aggregator shortlist:** Any existing conversations with
   Baselayer / FCS / LexisNexis / iLien / CSC / Parasec / Cogency? If yes,
   I should start there rather than cold-outreach (which is gated anyway).
2. **12-month budget ceiling:** Still ~$399K, or has it shifted given the
   Delaware authorized-searcher work and Tier 2 subscriptions?
3. **5-year window shape:** Rolling (always trailing) or fixed
   (Jan 2021 – present)? This affects backfill sizing and watchlist match
   logic.
4. **Debtor aliases / former names:** Does a search for "ACME CORP" need
   to hit "ACME CORPORATION", "ACME, INC.", "d/b/a ACME", and prior-name
   entries? This changes the matcher from simple-normalize to a fuzzy
   lookup (Jaro-Winkler or trigram) and affects latency.
5. **Hit routing for watchlist:** Sit in DB? Daily email digest? Slack?
   Attio? My default will be DB + stdout digest until told otherwise.

No commercial spend, no outreach, no contract work will happen without
explicit sign-off.

---

## 7. What's Next

Pending Austin's review of this document, I plan to:

- Open Phase 1 (Collateral Coverage Audit) and produce
  `reports/collateral-coverage-matrix.md`: per-state RAG rating for
  collateral access, backed by verification of each adapter's mapping
  against the actual source schema (live Socrata for CT/CO, published
  schemas + sample files for Tier 2, vendor docs for Tier 3).
- Fix the CO field map as a one-line bug before anything touches CO.
- File a single PR at the end of Phase 1 (≤500 lines), with the matrix,
  the CO fix, and any other mapping corrections surfaced during audit.

Acknowledged hard constraints: no contracts, no payments, no outreach, ToS
review per source, raw blob retention, idempotent ingestion, PII stays out
of stdout.
