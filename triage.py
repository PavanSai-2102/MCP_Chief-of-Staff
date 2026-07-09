import os
import google.generativeai as genai
from dotenv import load_dotenv

load_dotenv()

genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

model = genai.GenerativeModel('gemini-2.5-flash')

import json

def triage_inbox(threads: list)-> list:
    prompt = """
You are an intelligent email assistant helping triage an inbox.

Given the following list of email threads as a JSON array, classify each one.
For each email, provide:
1. priority: "urgent", "needs reply", "FYI", or "later"
2. category: one short tag like "meeting-request", "follow up", "personal", "newsletter", "billing", "job-app", "social", or "other"
3. reason: one sentence explaining why

Return the result as a JSON array of objects in the EXACT same order as the input threads. Each object must have exactly three keys: "priority", "category", "reason".
"""
    prompt += "\n\n" + json.dumps(threads, indent=2)
    
    import time
    from google.api_core.exceptions import ResourceExhausted, TooManyRequests

    max_retries = 3
    response = None
    for attempt in range(max_retries):
        try:
            response = model.generate_content(
                prompt,
                generation_config={"response_mime_type": "application/json"}
            )
            break
        except (ResourceExhausted, TooManyRequests) as e:
            if attempt < max_retries - 1:
                print(f"Rate limited during triage, sleeping for 30s... (Attempt {attempt+1}/{max_retries})")
                time.sleep(30)
            else:
                raise e
    
    try:
        labels = json.loads(response.text)
    except json.JSONDecodeError:
        labels = [{"priority": "later", "category": "other", "reason": "Failed to parse API response"} for _ in threads]
        
    triaged = []
    for thread, label in zip(threads, labels):
        # Ensure default values if the model missed some keys
        safe_label = {
            "priority": str(label.get("priority", "later")).lower(),
            "category": str(label.get("category", "other")).lower(),
            "reason": str(label.get("reason", ""))
        }
        triaged.append({**thread, **safe_label})

    priority_order = {"urgent" : 0, "needs reply" : 1, "fyi" : 2, "ignore" : 3, "later": 4, "unknown" : 5}

    triaged.sort(key = lambda t : priority_order.get(t["priority"], 5))
    return triaged


