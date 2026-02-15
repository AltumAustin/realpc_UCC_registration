#!/usr/bin/env python3
"""
Call Scheduler for UCC Registration Outreach

Manages the call queue, respects time zone business hours, enforces rate limits,
handles retries, and coordinates with the BlandCaller module.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

# State timezone mapping (primary time zone for each state's capital/main agency office)
STATE_TIMEZONES = {
    "AL": "America/Chicago",
    "AK": "America/Anchorage",
    "AZ": "America/Phoenix",
    "AR": "America/Chicago",
    "CA": "America/Los_Angeles",
    "CO": "America/Denver",
    "CT": "America/New_York",
    "DE": "America/New_York",
    "DC": "America/New_York",
    "FL": "America/New_York",
    "GA": "America/New_York",
    "HI": "Pacific/Honolulu",
    "ID": "America/Boise",
    "IL": "America/Chicago",
    "IN": "America/Indiana/Indianapolis",
    "IA": "America/Chicago",
    "KS": "America/Chicago",
    "KY": "America/New_York",
    "LA": "America/Chicago",
    "ME": "America/New_York",
    "MD": "America/New_York",
    "MA": "America/New_York",
    "MI": "America/Detroit",
    "MN": "America/Chicago",
    "MS": "America/Chicago",
    "MO": "America/Chicago",
    "MT": "America/Denver",
    "NE": "America/Chicago",
    "NV": "America/Los_Angeles",
    "NH": "America/New_York",
    "NJ": "America/New_York",
    "NM": "America/Denver",
    "NY": "America/New_York",
    "NC": "America/New_York",
    "ND": "America/Chicago",
    "OH": "America/New_York",
    "OK": "America/Chicago",
    "OR": "America/Los_Angeles",
    "PA": "America/New_York",
    "RI": "America/New_York",
    "SC": "America/New_York",
    "SD": "America/Chicago",
    "TN": "America/Chicago",
    "TX": "America/Chicago",
    "UT": "America/Denver",
    "VT": "America/New_York",
    "VA": "America/New_York",
    "WA": "America/Los_Angeles",
    "WV": "America/New_York",
    "WI": "America/Chicago",
    "WY": "America/Denver",
}

# Business hours: 9:00 AM - 4:30 PM local time, Monday-Friday
BUSINESS_HOURS_START = 9  # 9:00 AM
BUSINESS_HOURS_END_HOUR = 16  # 4:30 PM
BUSINESS_HOURS_END_MINUTE = 30


class CallScheduler:
    """Manages call queue, time zones, rate limiting, and retries."""

    def __init__(self, queue_path: str = "data/call_queue.json"):
        self.queue_path = queue_path
        self._load_queue()

    def _load_queue(self):
        """Load the call queue from disk."""
        if os.path.exists(self.queue_path):
            with open(self.queue_path, "r") as f:
                self.queue_data = json.load(f)
        else:
            self.queue_data = {
                "description": "Queue of Bland.ai phone calls pending human approval",
                "last_updated": datetime.now(timezone.utc).isoformat(),
                "calls": [],
            }

    def _save_queue(self):
        """Save the call queue to disk."""
        self.queue_data["last_updated"] = datetime.now(timezone.utc).isoformat()
        os.makedirs(os.path.dirname(self.queue_path), exist_ok=True)
        with open(self.queue_path, "w") as f:
            json.dump(self.queue_data, f, indent=2)

    def add_call(
        self,
        state_abbrev: str,
        state_name: str,
        phone_number: str,
        agency_name: str,
        questions: list[str],
        priority: str = "normal",
        script_reference: Optional[str] = None,
    ) -> dict:
        """
        Add a call to the queue.

        Args:
            state_abbrev: Two-letter state abbreviation
            state_name: Full state name
            phone_number: Target phone number
            agency_name: Name of the agency
            questions: List of questions to ask
            priority: "high", "normal", or "low"
            script_reference: Path to the full call script file

        Returns:
            The created call queue entry
        """
        entry = {
            "id": f"{state_abbrev}_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}",
            "state": state_abbrev,
            "state_name": state_name,
            "phone_number": phone_number,
            "agency_name": agency_name,
            "questions": questions,
            "priority": priority,
            "script_reference": script_reference,
            "status": "pending_approval",
            "retry_count": 0,
            "max_retries": 2,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "approved_at": None,
            "last_attempt_at": None,
            "completed_at": None,
            "outcome": None,
            "notes": "",
        }
        self.queue_data["calls"].append(entry)
        self._save_queue()
        return entry

    def is_within_business_hours(self, state_abbrev: str) -> bool:
        """Check if it's currently within business hours for the given state."""
        tz_name = STATE_TIMEZONES.get(state_abbrev)
        if not tz_name:
            return False

        tz = ZoneInfo(tz_name)
        local_now = datetime.now(tz)

        # Check weekday (Monday=0, Friday=4)
        if local_now.weekday() > 4:
            return False

        # Check time bounds
        start = local_now.replace(
            hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0
        )
        end = local_now.replace(
            hour=BUSINESS_HOURS_END_HOUR,
            minute=BUSINESS_HOURS_END_MINUTE,
            second=0,
            microsecond=0,
        )

        return start <= local_now <= end

    def get_next_business_window(self, state_abbrev: str) -> Optional[datetime]:
        """Get the next business hours window start for a state."""
        tz_name = STATE_TIMEZONES.get(state_abbrev)
        if not tz_name:
            return None

        tz = ZoneInfo(tz_name)
        local_now = datetime.now(tz)

        # If currently in business hours, return now
        if self.is_within_business_hours(state_abbrev):
            return local_now

        # Find next weekday at 9 AM
        candidate = local_now.replace(
            hour=BUSINESS_HOURS_START, minute=0, second=0, microsecond=0
        )
        if candidate <= local_now:
            candidate += timedelta(days=1)

        while candidate.weekday() > 4:
            candidate += timedelta(days=1)

        return candidate

    def get_approved_calls_ready(self) -> list[dict]:
        """Get all approved calls that are ready to execute (within business hours, respecting rate limits)."""
        ready = []
        states_called_today = set()

        # Check which states have already been called today
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        for call in self.queue_data["calls"]:
            if call.get("last_attempt_at") and call["last_attempt_at"].startswith(today):
                states_called_today.add(call["state"])

        for call in self.queue_data["calls"]:
            if call["status"] != "approved":
                continue
            if call["state"] in states_called_today:
                continue  # Rate limit: 1 call per agency per day
            if not self.is_within_business_hours(call["state"]):
                continue
            ready.append(call)

        # Sort by priority
        priority_order = {"high": 0, "normal": 1, "low": 2}
        ready.sort(key=lambda c: priority_order.get(c.get("priority", "normal"), 1))

        return ready

    def mark_approved(self, call_id: str):
        """Mark a call as approved for execution."""
        for call in self.queue_data["calls"]:
            if call["id"] == call_id:
                call["status"] = "approved"
                call["approved_at"] = datetime.now(timezone.utc).isoformat()
                break
        self._save_queue()

    def mark_attempted(self, call_id: str, outcome: str, notes: str = ""):
        """Record a call attempt."""
        for call in self.queue_data["calls"]:
            if call["id"] == call_id:
                call["last_attempt_at"] = datetime.now(timezone.utc).isoformat()
                call["retry_count"] += 1

                if outcome in ("completed", "successful"):
                    call["status"] = "completed"
                    call["completed_at"] = datetime.now(timezone.utc).isoformat()
                elif call["retry_count"] >= call["max_retries"]:
                    call["status"] = "failed_escalated"
                else:
                    call["status"] = "approved"  # Will be retried

                call["outcome"] = outcome
                call["notes"] = notes
                break
        self._save_queue()

    def get_queue_summary(self) -> dict:
        """Get a summary of the current call queue."""
        summary = {
            "total": len(self.queue_data["calls"]),
            "pending_approval": 0,
            "approved": 0,
            "completed": 0,
            "failed_escalated": 0,
        }
        for call in self.queue_data["calls"]:
            status = call.get("status", "unknown")
            if status in summary:
                summary[status] += 1
        return summary


if __name__ == "__main__":
    print("CallScheduler module loaded successfully.")
    scheduler = CallScheduler()
    print(f"Queue summary: {scheduler.get_queue_summary()}")
