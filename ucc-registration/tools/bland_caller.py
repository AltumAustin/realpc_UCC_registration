#!/usr/bin/env python3
"""
Bland.ai API Integration Module for UCC Registration Outreach

This module handles automated phone outreach to state agencies via the Bland.ai API.
It places calls, polls for completion, retrieves transcripts, and returns structured results.

Usage:
    from bland_caller import BlandCaller
    caller = BlandCaller()
    result = caller.place_call(
        phone_number="+15124637274",
        prompt="You are calling the Texas Secretary of State...",
        metadata={"state": "TX", "agency": "Secretary of State"}
    )
"""

import os
import json
import time
import logging
from datetime import datetime, timezone
from typing import Optional

try:
    import requests
except ImportError:
    raise ImportError("Please install the requests library: pip install requests")

logger = logging.getLogger(__name__)

BLAND_API_BASE = "https://api.bland.ai/v1"


class BlandCaller:
    """Handles Bland.ai API interactions for automated phone outreach."""

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.environ.get("BLAND_API_KEY")
        if not self.api_key:
            raise ValueError(
                "BLAND_API_KEY not found. Set it as an environment variable or pass it directly."
            )
        self.headers = {
            "Authorization": self.api_key,
            "Content-Type": "application/json",
        }

    def place_call(
        self,
        phone_number: str,
        prompt: str,
        metadata: Optional[dict] = None,
        voice: str = "nat",
        max_duration: int = 300,
        wait_for_greeting: bool = True,
        first_sentence: Optional[str] = None,
        record: bool = True,
    ) -> dict:
        """
        Place an outbound call via Bland.ai.

        Args:
            phone_number: Target phone number in E.164 format (e.g., +15124637274)
            prompt: The agent prompt/script for the call
            metadata: Optional dict with state, agency, and other context
            voice: Bland.ai voice ID to use
            max_duration: Maximum call duration in seconds
            wait_for_greeting: Whether to wait for the recipient to speak first
            first_sentence: Optional opening sentence for the agent
            record: Whether to record the call

        Returns:
            dict with call_id, status, and initial response data
        """
        payload = {
            "phone_number": phone_number,
            "task": prompt,
            "voice": voice,
            "max_duration": max_duration,
            "wait_for_greeting": wait_for_greeting,
            "record": record,
            "metadata": metadata or {},
        }

        if first_sentence:
            payload["first_sentence"] = first_sentence

        try:
            response = requests.post(
                f"{BLAND_API_BASE}/calls",
                json=payload,
                headers=self.headers,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            return {
                "success": True,
                "call_id": data.get("call_id"),
                "status": data.get("status", "queued"),
                "raw_response": data,
                "metadata": metadata,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

        except requests.exceptions.HTTPError as e:
            logger.error(f"Bland.ai API HTTP error: {e}")
            return {
                "success": False,
                "error": f"HTTP {e.response.status_code}: {e.response.text}",
                "metadata": metadata,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Bland.ai API request error: {e}")
            return {
                "success": False,
                "error": str(e),
                "metadata": metadata,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            }

    def get_call_status(self, call_id: str) -> dict:
        """Check the status of a call."""
        try:
            response = requests.get(
                f"{BLAND_API_BASE}/calls/{call_id}",
                headers=self.headers,
                timeout=30,
            )
            response.raise_for_status()
            return {"success": True, "data": response.json()}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error checking call status: {e}")
            return {"success": False, "error": str(e)}

    def get_transcript(self, call_id: str) -> dict:
        """Retrieve the transcript for a completed call."""
        try:
            response = requests.get(
                f"{BLAND_API_BASE}/calls/{call_id}",
                headers=self.headers,
                timeout=30,
            )
            response.raise_for_status()
            data = response.json()

            return {
                "success": True,
                "call_id": call_id,
                "transcript": data.get("transcripts", []),
                "concatenated_transcript": data.get("concatenated_transcript", ""),
                "duration": data.get("call_length"),
                "status": data.get("status"),
                "completed": data.get("completed", False),
                "raw_data": data,
            }
        except requests.exceptions.RequestException as e:
            logger.error(f"Error retrieving transcript: {e}")
            return {"success": False, "error": str(e)}

    def wait_for_completion(
        self, call_id: str, poll_interval: int = 10, max_wait: int = 600
    ) -> dict:
        """
        Poll until a call is completed or max_wait is exceeded.

        Args:
            call_id: The Bland.ai call ID
            poll_interval: Seconds between status checks
            max_wait: Maximum seconds to wait before timing out

        Returns:
            dict with final call status and transcript
        """
        elapsed = 0
        while elapsed < max_wait:
            status = self.get_call_status(call_id)
            if not status["success"]:
                return status

            call_data = status["data"]
            call_status = call_data.get("status", "")

            if call_status in ("completed", "failed", "error", "no-answer", "busy"):
                return self.get_transcript(call_id)

            if call_data.get("completed"):
                return self.get_transcript(call_id)

            time.sleep(poll_interval)
            elapsed += poll_interval

        return {
            "success": False,
            "error": f"Call did not complete within {max_wait} seconds",
            "call_id": call_id,
        }

    def place_call_and_wait(
        self,
        phone_number: str,
        prompt: str,
        metadata: Optional[dict] = None,
        **kwargs,
    ) -> dict:
        """
        Place a call and wait for it to complete, returning the full result.

        This is a convenience method that combines place_call and wait_for_completion.
        """
        call_result = self.place_call(phone_number, prompt, metadata, **kwargs)

        if not call_result["success"]:
            return call_result

        call_id = call_result["call_id"]
        logger.info(f"Call placed successfully. Call ID: {call_id}. Waiting for completion...")

        completion = self.wait_for_completion(call_id)
        completion["metadata"] = metadata
        completion["phone_number"] = phone_number
        return completion


def build_agent_prompt(
    state: str,
    agency_name: str,
    questions: list[str],
    is_two_party_consent: bool = False,
) -> str:
    """
    Build a Bland.ai agent prompt for calling a state agency about UCC searcher registration.

    Args:
        state: State name
        agency_name: Name of the agency being called
        questions: List of specific questions to ask
        is_two_party_consent: Whether the state requires two-party recording consent
    """
    recording_disclosure = ""
    if is_two_party_consent:
        recording_disclosure = (
            "After introducing yourself, say: 'This call may be recorded for our records. "
            "Is that okay with you?' If they decline recording, say: 'No problem, I will not "
            "record this call. I just have a few questions if that is alright.'"
        )

    questions_text = "\n".join(f"  {i+1}. {q}" for i, q in enumerate(questions))

    return f"""You are calling on behalf of Real Finance's legal department. You are an AI assistant making this call.

IDENTITY AND DISCLOSURE:
- At the start of the call, say: "Hello, this is an automated call from Real Finance's legal department. My name is Alex. Is it okay if I ask a few questions about your UCC searcher registration process?"
- If they ask, confirm you are an AI assistant gathering information on behalf of Real Finance.
- If they decline to speak with an AI, politely say: "I completely understand. Could I get the best phone number and contact name for someone on our team to call back?" Then end the call politely.
{recording_disclosure}

OBJECTIVE:
You are calling {agency_name} in {state} to gather information about becoming an authorized UCC searcher or obtaining access to conduct UCC lien searches.

QUESTIONS TO ASK (in order of priority):
{questions_text}

BEHAVIOR GUIDELINES:
- Be professional, polite, and patient at all times
- If placed on hold, wait patiently
- If transferred, re-introduce yourself briefly to the new person
- If you reach voicemail, leave a brief message: "Hello, this is a call from Real Finance's legal department regarding UCC searcher registration. We would appreciate a callback at 949-887-5775. Thank you."
- Listen carefully and capture specific details like form names, form numbers, URLs, fee amounts, and processing times
- Ask clarifying follow-up questions if an answer is vague

STRICT GUARDRAILS - NEVER DO THE FOLLOWING:
- Never agree to any terms or conditions
- Never authorize any payments or commitments
- Never provide sensitive company information (EIN, SSN, financial details)
- Never represent yourself as an attorney or lawyer
- Never make promises about filings or applications
- You are ONLY gathering information
"""


if __name__ == "__main__":
    # Quick connectivity test (does not place a call)
    import sys

    api_key = os.environ.get("BLAND_API_KEY")
    if not api_key:
        print("ERROR: BLAND_API_KEY environment variable not set.")
        print("Set it with: export BLAND_API_KEY=your_key_here")
        sys.exit(1)

    print("BLAND_API_KEY is set. Module loaded successfully.")
    print("Use BlandCaller class to place calls.")
    print("Example:")
    print('  caller = BlandCaller()')
    print('  result = caller.place_call("+15551234567", "Your prompt here")')
