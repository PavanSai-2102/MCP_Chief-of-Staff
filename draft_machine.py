"""Generate email reply drafts using Gemini 2.5 Flash.

This module uses the context assembled by context_builder.py and sends it
to Google's Gemini model to produce email reply drafts that match the
user's writing style and tone.
"""

from __future__ import annotations

import os
import sys
from typing import Any

import google.generativeai as genai
from dotenv import load_dotenv

from context_builder import assemble_context

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MODEL_NAME = "gemini-2.5-flash"

DRAFTING_RULES = """
STRICT DRAFTING RULES — follow these without exception:

1. ONE-ASK RULE
   - Every email must contain exactly ONE clear question OR ONE clear response.
   - Never bury multiple asks in a single email.

2. LENGTH CONTROL
   - Match the energy of the thread — short thread = short reply.
   - Maximum 5 sentences in the body (excluding greeting and sign-off).
   - Use numbered points only when listing more than 2 items.

3. NO AI FILLER
   - NEVER use any of these phrases:
     • "I hope this email finds you well"
     • "Thank you for reaching out"
     • "I wanted to follow up"
     • "Per our conversation"
     • "As discussed"
     • "I hope you're doing well"
   - Sound like a real human, not a language model.

4. STRUCTURE
   - Acknowledge briefly (1 sentence max) → Give your response → End with ONE clear next step or question.
   - Do NOT add a subject line.
   - Do NOT add any explanation or commentary outside the email body.
   - Output ONLY the email draft text, nothing else.
"""


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------


def _configure_api() -> None:
    """Load the API key from .env and configure the Gemini client."""
    load_dotenv()
    api_key = os.getenv("GEMINI_API_KEY")

    if not api_key:
        raise EnvironmentError(
            "GEMINI_API_KEY not found.\n"
            "Fix: Create a .env file in this directory with:\n"
            "  GEMINI_API_KEY=your_key_here\n"
            "Get a key at https://aistudio.google.com/apikey"
        )

    genai.configure(api_key=api_key)


def draft_reply(thread: dict[str, Any]) -> str:
    """Generate an email reply draft for the given thread.

    Args:
        thread: A dict with "subject" and "messages" keys, where messages
                is a list of {"from", "date", "body"} dicts.

    Returns:
        The draft email text as a plain string — no subject line,
        no explanation, just the reply body.
    """
    context = assemble_context(thread)

    system_prompt = context["system"] + "\n\n" + DRAFTING_RULES
    user_prompt = context["user"]

    _configure_api()
    model = genai.GenerativeModel(
        model_name=MODEL_NAME,
        system_instruction=system_prompt,
        generation_config=genai.types.GenerationConfig(
            temperature=0.7,
            max_output_tokens=8192,
        ),
    )

    import time
    from google.api_core.exceptions import ResourceExhausted, TooManyRequests

    max_retries = 3
    response = None
    for attempt in range(max_retries):
        try:
            response = model.generate_content(user_prompt)
            break
        except (ResourceExhausted, TooManyRequests) as e:
            if attempt < max_retries - 1:
                print(f"Rate limited during draft generation, sleeping for 30s... (Attempt {attempt+1}/{max_retries})")
                time.sleep(30)
            else:
                raise e

    return response.text.strip()


def draft_reply_with_metadata(thread: dict[str, Any]) -> dict[str, str]:
    """Generate a reply draft and return it alongside useful metadata.

    Args:
        thread: Same thread dict as draft_reply().

    Returns:
        A dict with keys:
            - "draft": the generated email reply text
            - "model": the Gemini model name used
            - "subject": the thread subject line
            - "replying_to": the sender of the last message in the thread
    """
    draft = draft_reply(thread)

    messages = thread.get("messages", [])
    last_sender = messages[-1].get("from", "Unknown") if messages else "Unknown"

    return {
        "draft": draft,
        "model": MODEL_NAME,
        "subject": thread.get("subject", "(No subject)"),
        "replying_to": last_sender,
        "char_count": len(draft),
    }


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------

SAMPLE_THREADS = [
    {
        "subject": "Q3 Budget Review",
        "messages": [
            {
                "from": "Ananya <ananya@example.com>",
                "date": "2026-06-15 10:15 AM",
                "body": (
                    "Hi Pavan,\n\n"
                    "Could you share your view on whether we should prioritize "
                    "the data lake migration or the analytics dashboard refresh "
                    "for Q3?\n\n"
                    "Thanks,\nAnanya"
                ),
            },
            {
                "from": "Vikram <vikram@example.com>",
                "date": "2026-06-15 11:02 AM",
                "body": (
                    "Adding Pavan here. My vote is the data lake migration, but "
                    "it would be helpful to get engineering's perspective before "
                    "planning closes."
                ),
            },
        ],
    },
    {
        "subject": "API Deprecation Notice",
        "messages": [
            {
                "from": "Platform Team <platform@example.com>",
                "date": "2026-06-16 09:00 AM",
                "body": (
                    "Hello team,\n\n"
                    "Please note that the v1 user endpoints will be fully deprecated "
                    "by the end of this month. All clients must migrate to v2.\n\n"
                    "Let us know if you need an extension."
                ),
            },
        ],
    },
    {
        "subject": "Re: Sync on new UI designs",
        "messages": [
            {
                "from": "Design Team <design@example.com>",
                "date": "2026-06-17 02:30 PM",
                "body": (
                    "Hey Pavan,\n\n"
                    "We've attached the latest Figma mockups for the new settings page. "
                    "Let us know if the new layout works with the backend data structure."
                ),
            },
        ],
    }
]

if __name__ == "__main__":
    sample_thread = SAMPLE_THREADS[0]

    # ── Pre-flight check ──────────────────────────────────────────────
    load_dotenv()
    if not os.getenv("GEMINI_API_KEY"):
        print("❌ GEMINI_API_KEY not found in .env")
        print("   Create a .env file in this directory with:")
        print("     GEMINI_API_KEY=your_key_here")
        print("   Get a key at https://aistudio.google.com/apikey")
        sys.exit(1)

    # ── Generate draft ────────────────────────────────────────────────
    print("⏳ Generating reply draft with Gemini 2.5 Flash...\n")

    try:
        result = draft_reply_with_metadata(sample_thread)
    except Exception as exc:
        print(f"❌ Error generating draft: {exc}")
        sys.exit(1)

    # ── Display results ───────────────────────────────────────────────
    print("=" * 60)
    print("GEMINI DRAFT")
    print("=" * 60)
    print(f"{'Model:':<18}{result['model']}")
    print(f"{'Thread subject:':<18}{result['subject']}")
    print(f"{'Replying to:':<18}{result['replying_to']}")
    print(f"{'Char count:':<18}{result['char_count']}")
    print("-" * 60)
    print(result["draft"])
    print("=" * 60)
