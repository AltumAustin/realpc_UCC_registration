# UCC Authorized Searcher Registration — All 50 States + DC

## Overview

This project manages RealPC Real Finance, Inc.'s registration as an authorized UCC (Uniform Commercial Code) searcher across all 50 U.S. states and the District of Columbia.

## Company Information

- **Company**: RealPC Real Finance, Inc.
- **Incorporated in**: Delaware
- **Principal Office**: 9240 SW 72ND ST STE 114, MIAMI, FL 33173
- **Authorized Representative**: Austin, Chief Legal Officer
- **Contact**: austin@realpc.ai | (949) 887-5775

## Directory Structure

```
ucc-registration/
├── data/                          # Core data files
│   ├── ucc_requirements.json      # State-by-state requirements database
│   ├── state_status.json          # Real-time status for all jurisdictions
│   ├── activity_log.jsonl         # Append-only activity log (JSON Lines)
│   ├── interactions_log.jsonl     # External communications log
│   ├── recording_consent_laws.json # State recording consent classifications
│   └── call_queue.json            # Bland.ai call queue
├── tools/                         # Automation tooling
│   ├── bland_caller.py            # Bland.ai API integration
│   ├── transcript_parser.py       # Call transcript processing
│   └── call_scheduler.py          # Call queue & time zone management
├── plans/                         # Registration planning documents
│   ├── registration_plan.md       # Tiered registration plan
│   ├── prerequisites_checklist.md # Master prerequisites list
│   └── timeline.md                # Project timeline
├── reports/                       # Status reports
│   ├── ucc_requirements_summary.md # Human-readable requirements summary
│   ├── progress_report.md         # Current progress report
│   └── decisions_needed.md        # Items needing human approval
├── outreach/                      # External communications
│   ├── emails/                    # Draft and sent emails
│   ├── call_scripts/              # Bland.ai and manual call scripts
│   └── call_transcripts/          # Bland.ai transcript archives
├── applications/                  # Per-state application materials
│   └── {STATE}/                   # State-specific application files
├── .env.example                   # Environment variable template
└── README.md                      # This file
```

## Setup

1. Copy `.env.example` to `.env` and add your Bland.ai API key
2. Install Python dependencies: `pip install requests`
3. Ensure Python 3.10+ is available

## Workflow

1. **Phase 1**: Research requirements for all 51 jurisdictions
2. **Phase 2**: Create prioritized registration plan
3. **Phase 3**: Execute registrations (with human approval gates)
4. **Phase 4**: Ongoing record-keeping and follow-up

## Approval Gates

The following actions require explicit human approval before execution:
- Sending any emails to state agencies
- Placing any Bland.ai phone calls
- Submitting any applications
- Making any payments
