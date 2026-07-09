import os
import json
import re
import socket
from datetime import datetime, timedelta
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
import google.generativeai as genai

# --- IPv4 Monkey-Patch ---
# Forces the socket to use IPv4, which can resolve hanging issues on some networks
if not hasattr(socket, '_ipv4_monkey_patched'):
    old_getaddrinfo = socket.getaddrinfo
    def new_getaddrinfo(*args, **kwargs):
        responses = old_getaddrinfo(*args, **kwargs)
        return [response for response in responses if response[0] == socket.AF_INET]
    socket.getaddrinfo = new_getaddrinfo
    socket._ipv4_monkey_patched = True

# ---------------------------------------------------------------------------
# Google Calendar Direct API Integration
# ---------------------------------------------------------------------------

def _build_calendar_service():
    """
    Initializes and returns the Google Calendar v3 API service using local token.json.
    Shares the same token.json and scopes as engine.py's auth pattern.
    """
    token_path = os.path.join(os.path.dirname(__file__), 'token.json')
    if not os.path.exists(token_path):
        raise FileNotFoundError("token.json not found. Please authenticate first.")
        
    creds = Credentials.from_authorized_user_file(token_path, scopes=[
        'https://www.googleapis.com/auth/calendar',
        'https://www.googleapis.com/auth/gmail.modify',
        'https://www.googleapis.com/auth/gmail.settings.basic'
    ])
    
    service = build('calendar', 'v3', credentials=creds)
    return service

def parse_meeting_request(thread):
    """
    Extracts meeting details from an email thread using Gemini.
    Returns a dict with proposed_times, attendees, topic, duration_minutes.
    On failure, returns {"parsing_error": "<error message>"}.
    """
    try:
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            return {"parsing_error": "GEMINI_API_KEY environment variable not set"}
            
        genai.configure(api_key=api_key)
        
        # Concatenate all messages in the thread
        messages = thread.get("messages", [])
        if not messages:
            text_content = thread.get("snippet", "")
        else:
            text_content = "\n\n---\n\n".join([msg.get("body", "") for msg in messages])
            
        today_date = datetime.now().strftime("%Y-%m-%d")
        
        prompt = f"""You are an assistant that extracts meeting details from email threads.
Today's date is {today_date}. Use this to properly resolve any relative dates (e.g. "tomorrow", "next Tuesday").

Extract the following information from the email thread:
- "proposed_times": A list of ISO-8601 datetime strings for the proposed meeting times. If a time range is provided (e.g., "2 PM to 5 PM"), generate hourly slots within that range.
- "attendees": A list of email addresses of the attendees.
- "topic": A concise one-line summary of the meeting.
- "duration_minutes": An integer representing the duration of the meeting in minutes (default 30 if not specified).

Return ONLY valid JSON with exactly these keys, and no other text or markdown.

Email Thread:
{text_content}"""

        model = genai.GenerativeModel("gemini-2.5-flash")
        
        import time
        from google.api_core.exceptions import ResourceExhausted, TooManyRequests

        max_retries = 3
        response = None
        for attempt in range(max_retries):
            try:
                response = model.generate_content(prompt)
                break
            except (ResourceExhausted, TooManyRequests) as e:
                if attempt < max_retries - 1:
                    print(f"Rate limited during calendar extraction, sleeping for 30s... (Attempt {attempt+1}/{max_retries})")
                    time.sleep(30)
                else:
                    raise e
        
        text = response.text.strip()
        # Strip markdown code fences before JSON parsing
        if text.startswith("```"):
            text = re.sub(r"^```(?:json)?\n?", "", text)
            text = re.sub(r"\n?```$", "", text)
            
        return json.loads(text)
        
    except Exception as e:
        return {"parsing_error": str(e)}

def check_availability(time_min: str, time_max: str) -> bool:
    """
    Calls the FreeBusy API on the user's primary calendar to check if the time slot is free.
    Returns True if free, False if busy. Raises exception on API errors.
    """
    service = _build_calendar_service()
    
    # Append "Z" if no timezone info is present
    if not time_min.endswith("Z") and "+" not in time_min:
        time_min += "Z"
    if not time_max.endswith("Z") and "+" not in time_max:
        time_max += "Z"
        
    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": "primary"}]
    }
    
    result = service.freebusy().query(body=body).execute()
    busy_slots = result.get("calendars", {}).get("primary", {}).get("busy", [])
    
    return len(busy_slots) == 0

def find_free_slot(proposed_times: list, duration_minutes: int):
    """
    Loops through proposed start times, calculates end time using duration,
    calls check_availability, and returns the first free slot.
    Skips malformed strings gracefully.
    """
    if not proposed_times:
        return {"error": "proposed_times list is empty"}
        
    errors = []
    for time_str in proposed_times:
        try:
            # Handle standard trailing "Z" for python's fromisoformat
            clean_time_str = time_str.replace("Z", "+00:00")
            start_dt = datetime.fromisoformat(clean_time_str)
            end_dt = start_dt + timedelta(minutes=int(duration_minutes))
            
            start_iso = start_dt.isoformat()
            end_iso = end_dt.isoformat()
            
            is_free = check_availability(start_iso, end_iso)
            if is_free:
                return {"start": start_iso, "end": end_iso}
            else:
                errors.append(f"{time_str} is busy")
        except Exception as e:
            errors.append(f"Error parsing {time_str}: {e}")
            continue
            
    return {"error": "All slots failed: " + ", ".join(errors)}

def create_event(summary: str, start_time: str, duration_minutes: int, attendees: list, description: str = ""):
    """
    Creates a Google Calendar event.
    Calculates end_time from start_time + duration_minutes.
    Only includes attendees with a valid email containing '@'.
    Uses sendUpdates='all' to notify attendees.
    Returns the created event dictionary.
    """
    service = _build_calendar_service()
    
    # Parse the start time and calculate end time
    clean_start_str = start_time.replace("Z", "+00:00")
    start_dt = datetime.fromisoformat(clean_start_str)
    end_dt = start_dt + timedelta(minutes=duration_minutes)
    
    event_body = {
        'summary': summary,
        'description': description,
        'start': {
            'dateTime': start_dt.isoformat(),
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': end_dt.isoformat(),
            'timeZone': 'UTC',
        }
    }
    
    # Only include attendees with valid email addresses
    valid_attendees = [{'email': email} for email in attendees if '@' in email]
    if valid_attendees:
        event_body['attendees'] = valid_attendees
        
    created_event = service.events().insert(
        calendarId='primary',
        body=event_body,
        sendUpdates='all'
    ).execute()
    
    return created_event
