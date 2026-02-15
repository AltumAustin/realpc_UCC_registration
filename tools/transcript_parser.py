#!/usr/bin/env python3
"""
Transcript Parser for Bland.ai Call Transcripts

Parses raw Bland.ai transcripts into structured data, extracts answers
to specific questions, and updates the UCC requirements database.
"""

import json
import os
import re
from datetime import datetime, timezone
from typing import Optional


class TranscriptParser:
    """Parses Bland.ai call transcripts and extracts structured information."""

    def __init__(self, data_dir: str = "data", transcripts_dir: str = "outreach/call_transcripts"):
        self.data_dir = data_dir
        self.transcripts_dir = transcripts_dir

    def save_raw_transcript(self, state_abbrev: str, call_data: dict) -> str:
        """
        Save raw transcript data from Bland.ai to a JSON file.

        Args:
            state_abbrev: Two-letter state abbreviation
            call_data: Raw call data from Bland.ai API

        Returns:
            Path to saved transcript file
        """
        date_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        filename = f"{state_abbrev}_{date_str}_transcript.json"
        filepath = os.path.join(self.transcripts_dir, filename)

        os.makedirs(os.path.dirname(filepath), exist_ok=True)

        transcript_record = {
            "state": state_abbrev,
            "date": date_str,
            "call_id": call_data.get("call_id"),
            "duration": call_data.get("duration"),
            "status": call_data.get("status"),
            "transcript": call_data.get("transcript", []),
            "concatenated_transcript": call_data.get("concatenated_transcript", ""),
            "raw_data": call_data.get("raw_data", {}),
            "saved_at": datetime.now(timezone.utc).isoformat(),
        }

        with open(filepath, "w") as f:
            json.dump(transcript_record, f, indent=2)

        return filepath

    def extract_answers(
        self, transcript_text: str, questions: list[str]
    ) -> dict[str, Optional[str]]:
        """
        Extract answers to specific questions from a transcript.

        This performs basic keyword matching and proximity analysis.
        For production use, consider integrating an LLM for better extraction.

        Args:
            transcript_text: The concatenated transcript text
            questions: List of questions that were asked

        Returns:
            Dict mapping question keywords to extracted answer snippets
        """
        answers = {}

        # Split transcript into turns
        lines = transcript_text.split("\n")

        for question in questions:
            # Create a simplified key from the question
            key = self._question_to_key(question)
            answers[key] = None

            # Look for agent lines containing question keywords, then capture the next response
            question_words = set(question.lower().split()) - {
                "what", "is", "the", "to", "a", "an", "are", "how", "do", "does",
                "for", "of", "in", "and", "or", "can", "we", "i", "you",
            }

            for i, line in enumerate(lines):
                line_lower = line.lower()
                # Check if this line (from the agent) contains question keywords
                matching_words = sum(1 for w in question_words if w in line_lower)
                if matching_words >= len(question_words) * 0.5:
                    # Collect subsequent lines as the answer (from the human)
                    answer_lines = []
                    for j in range(i + 1, min(i + 5, len(lines))):
                        if lines[j].strip():
                            answer_lines.append(lines[j].strip())
                    if answer_lines:
                        answers[key] = " ".join(answer_lines)
                    break

        return answers

    def _question_to_key(self, question: str) -> str:
        """Convert a question to a short key for the answers dict."""
        # Remove common question words and create a slug
        stop_words = {
            "what", "is", "the", "to", "a", "an", "are", "how", "do", "does",
            "for", "of", "in", "and", "or", "can", "we", "i", "you", "your",
            "about", "from", "this", "that", "there", "their",
        }
        words = re.sub(r"[^\w\s]", "", question.lower()).split()
        key_words = [w for w in words if w not in stop_words][:4]
        return "_".join(key_words) if key_words else "unknown"

    def parse_call_result(
        self, state_abbrev: str, state_name: str, call_data: dict, questions: list[str]
    ) -> dict:
        """
        Full processing pipeline for a completed call.

        1. Save raw transcript
        2. Extract answers
        3. Build structured result

        Args:
            state_abbrev: Two-letter state abbreviation
            state_name: Full state name
            call_data: Raw data from Bland.ai
            questions: Questions that were asked during the call

        Returns:
            Structured result dict ready for logging and database updates
        """
        # Save raw transcript
        transcript_path = self.save_raw_transcript(state_abbrev, call_data)

        # Extract answers
        transcript_text = call_data.get("concatenated_transcript", "")
        answers = self.extract_answers(transcript_text, questions)

        # Determine call outcome
        human_reached = bool(transcript_text and len(transcript_text) > 50)
        call_successful = call_data.get("completed", False) and human_reached

        result = {
            "state": state_abbrev,
            "state_name": state_name,
            "call_id": call_data.get("call_id"),
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "duration_seconds": call_data.get("duration"),
            "human_reached": human_reached,
            "call_successful": call_successful,
            "transcript_file": transcript_path,
            "questions_asked": questions,
            "answers_extracted": answers,
            "needs_follow_up": not call_successful,
            "raw_status": call_data.get("status"),
        }

        return result

    def update_requirements_db(
        self, state_abbrev: str, answers: dict, requirements_path: str = "data/ucc_requirements.json"
    ):
        """
        Update the UCC requirements JSON database with new information from a call.

        Args:
            state_abbrev: Two-letter state abbreviation
            answers: Extracted answers dict
            requirements_path: Path to the requirements JSON file
        """
        if not os.path.exists(requirements_path):
            return

        with open(requirements_path, "r") as f:
            db = json.load(f)

        # Find the state entry
        for state in db.get("states", []):
            if state.get("abbreviation") == state_abbrev:
                # Update with call-derived information
                if "phone_outreach_data" not in state:
                    state["phone_outreach_data"] = {}
                state["phone_outreach_data"].update(answers)
                state["phone_outreach_data"]["last_call_date"] = datetime.now(
                    timezone.utc
                ).strftime("%Y-%m-%d")
                state["data_confidence"] = "medium"  # Upgraded from low since we made contact
                break

        with open(requirements_path, "w") as f:
            json.dump(db, f, indent=2)


if __name__ == "__main__":
    print("TranscriptParser module loaded successfully.")
    print("Use TranscriptParser class to process Bland.ai call transcripts.")
