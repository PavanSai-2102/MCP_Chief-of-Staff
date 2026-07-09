"""Build prompt context for an email reply drafting agent.

This module loads a tone profile and past reply examples, formats an
incoming email thread, and assembles system/user prompts for an agent that
drafts replies in a specific person's writing style.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_tone_profile(path: str = "tone_profile.json") -> dict[str, Any]:
    """Read and return the tone profile dictionary from a JSON file."""
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def load_past_replies(path: str = "past_replies.json") -> list[dict[str, Any]]:
    """Read and return the list of past reply examples from a JSON file."""
    with Path(path).open("r", encoding="utf-8") as file:
        return json.load(file)


def format_thread_history(thread: dict[str, Any]) -> str:
    """Format a thread dict into a readable chronological email history.

    Expected thread shape:
        {
            "subject": "...",
            "messages": [
                {"from": "...", "date": "...", "body": "..."},
                ...
            ]
        }
    """
    subject = thread.get("subject", "(No subject)")
    messages = thread.get("messages", [])

    lines = [f"Subject: {subject}", "", "Thread history:"]

    if not messages:
        lines.append("No prior messages provided.")
        return "\n".join(lines)

    for index, message in enumerate(messages, start=1):
        sender = message.get("from", "Unknown sender")
        date = message.get("date", "Unknown date")
        body = message.get("body", "").strip()

        lines.extend(
            [
                "",
                f"Message {index}",
                f"From: {sender}",
                f"Date: {date}",
                "Body:",
                body or "(No body)",
            ]
        )

    return "\n".join(lines)


def build_system_prompt(
    tone_profile: dict[str, Any], past_replies: list[dict[str, Any]]
) -> str:
    """Build the system prompt from persona details, rules, and examples."""
    name = tone_profile.get("name", "the user")
    role = tone_profile.get("role", "professional")
    company = tone_profile.get("company", "")
    tone = tone_profile.get("tone", "clear and helpful")
    voice_description = tone_profile.get("voice_description", "")
    traits = tone_profile.get("traits", [])
    do_list = tone_profile.get("do", [])
    dont_list = tone_profile.get("dont", [])

    role_company = f"{role} at {company}" if company else role

    prompt_parts = [
        "You are an email reply drafting agent.",
        f"Write replies as {name}, a {role_company}.",
        f"Persona: {name} writes in a {tone} tone.",
        "Match the person's voice closely while keeping the reply useful and context-aware.",
    ]

    if voice_description:
        prompt_parts.append(f"Voice Description: {voice_description}")

    if traits:
        prompt_parts.append(f"Key Traits: {', '.join(traits)}")

    if do_list:
        do_str = "\n".join(f"- {item}" for item in do_list)
        prompt_parts.append(f"Do:\n{do_str}")

    if dont_list:
        dont_str = "\n".join(f"- {item}" for item in dont_list)
        prompt_parts.append(f"Don't:\n{dont_str}")

    examples_to_include = past_replies[:3]
    if examples_to_include:
        examples_text = f"Here's how {name} writes:\n\n"
        example_blocks = []
        for index, reply_obj in enumerate(examples_to_include, start=1):
            context = reply_obj.get("context")
            incoming_subject = reply_obj.get("incoming_subject")
            reply = reply_obj.get("reply", "").strip()

            example_lines = [f"Example {index}:"]
            if context:
                example_lines.append(f"Context: {context}")
            if incoming_subject:
                example_lines.append(f"Incoming Subject: {incoming_subject}")
            example_lines.append(f"Reply:\n{reply}")
            example_blocks.append("\n".join(example_lines))
            
        examples_text += "\n\n".join(example_blocks)
        prompt_parts.append(examples_text)

    prompt_parts.append(
        "When drafting the reply, produce only the email draft. Do not include analysis."
    )

    return "\n\n".join(prompt_parts)


def build_user_prompt(thread_formatted: str) -> str:
    """Build the user prompt asking the agent to draft a reply."""
    return (
        "Please draft a reply to the latest email in this thread. "
        "Use the full thread for context and match the writing style described in the system prompt.\n\n"
        f"{thread_formatted}"
    )


def assemble_context(
    thread: dict[str, Any],
    tone_path: str = "tone_profile.json",
    replies_path: str = "past_replies.json",
) -> dict[str, str]:
    """Load profile/examples, format thread, and return system/user prompts."""
    tone_profile = load_tone_profile(tone_path)
    past_replies = load_past_replies(replies_path)
    thread_formatted = format_thread_history(thread)

    return {
        "system": build_system_prompt(tone_profile, past_replies),
        "user": build_user_prompt(thread_formatted),
    }


if __name__ == "__main__":
    sample_thread = {
        "subject": "Q3 roadmap alignment",
        "messages": [
            {
                "from": "Ananya <ananya@example.com>",
                "date": "2026-06-15 10:15 AM",
                "body": "Hi Rahul,\n\nCould you share your view on whether we should prioritize onboarding improvements or the analytics refresh for Q3?\n\nThanks,\nAnanya",
            },
            {
                "from": "Vikram <vikram@example.com>",
                "date": "2026-06-15 11:02 AM",
                "body": "Adding Rahul here. My vote is onboarding, but it would be helpful to get product's perspective before planning closes.",
            },
        ],
    }

    context = assemble_context(sample_thread)
    print("=== SYSTEM PROMPT ===")
    print(context["system"])
    print("\n=== USER PROMPT ===")
    print(context["user"])