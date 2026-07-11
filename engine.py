import asyncio
import re
import os
import json
from datetime import datetime, timezone
from typing import List, Dict

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

from triage import triage_inbox

MCP_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "Gmail-MCP-Server")
MCP_SERVER_PATH = os.path.join(MCP_DIR, "dist", "index.js")

if not os.path.exists(MCP_SERVER_PATH):
    import subprocess
    print("Building MCP Server...")
    subprocess.run(["npm", "install"], cwd=MCP_DIR, check=True)
    subprocess.run(["npm", "run", "build"], cwd=MCP_DIR, check=True)

async def fetch_threads_async() -> List[Dict]:
    """
    Asynchronous function to fetch the last 20 inbox threads via Gmail MCP Server.
    """
    server_params = StdioServerParameters(
        command="node",
        args=[MCP_SERVER_PATH]
    )
    
    threads = []
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Step 1: Search for the last 5 emails
            search_result = await session.call_tool("search_emails", {"query": "in:inbox", "maxResults": 5})
            
            # Extract message IDs from the text result
            # Expected format: ID: 19ecb0d4d17eaef3
            search_text = search_result.content[0].text
            message_ids = re.findall(r"ID:\s*([a-zA-Z0-9]+)", search_text)
            
            # Step 2: Fetch details for each message
            for msg_id in message_ids:
                try:
                    email_result = await session.call_tool("read_email", {"messageId": msg_id})
                    email_text = email_result.content[0].text
                    
                    # Parse the fields
                    thread_id_match = re.search(r"Thread ID:\s*(.*)", email_text)
                    sender_match = re.search(r"From:\s*(.*)", email_text)
                    subject_match = re.search(r"Subject:\s*(.*)", email_text)
                    date_match = re.search(r"Date:\s*(.*)", email_text)
                    
                    # The body is everything after the header block (which ends with \n\n)
                    parts = email_text.split("\n\n", 1)
                    body = parts[1] if len(parts) > 1 else ""
                    
                    # Clean the body: remove the HTML warning
                    body = body.replace("[Note: This email is HTML-formatted. Plain text version not available.]", "")
                    
                    # Remove HTML tags using a simple regex
                    body = re.sub(r'<[^>]+>', ' ', body)
                    
                    # Create a snippet (clean whitespace, up to 500 chars)
                    snippet = " ".join(body.split())
                    snippet = snippet[:500] + ("..." if len(snippet) > 500 else "")
                    
                    thread_info = {
                        "thread id": thread_id_match.group(1).strip() if thread_id_match else msg_id,
                        "message_id": msg_id,
                        "sender": sender_match.group(1).strip() if sender_match else "Unknown",
                        "subject": subject_match.group(1).strip() if subject_match else "No Subject",
                        "snippet": snippet,
                        "date": date_match.group(1).strip() if date_match else "Unknown"
                    }
                    threads.append(thread_info)
                except Exception as e:
                    print(f"Error fetching message {msg_id}: {e}")
                    
    return threads

def fetch_threads() -> List[Dict]:
    """
    Synchronous wrapper to fetch the last 20 inbox threads using the Gmail MCP server.
    Each thread is a dictionary with: thread id, sender, subject, snippet, and date.
    """
    return asyncio.run(fetch_threads_async())

async def send_reply_async(thread_id: str, to: str, subject: str, body: str, message_id: str = None) -> dict:
    """
    Asynchronous function to send an email reply via Gmail MCP Server.
    """
    if not subject.lower().startswith("re:"):
        subject = f"Re: {subject}"

    server_params = StdioServerParameters(
        command="node",
        args=[MCP_SERVER_PATH]
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            payload = {
                "to": [to],
                "subject": subject,
                "body": body,
                "threadId": thread_id
            }
            if message_id:
                payload["inReplyTo"] = message_id
                
            try:
                result = await session.call_tool("send_email", payload)
                content = result.content[0].text if result.content else ""
                
                if result.isError or content.startswith("Error:"):
                    return {"status": "error", "error": content}
                    
                id_match = re.search(r"ID:\s*(.*)", content)
                new_id = id_match.group(1).strip() if id_match else "unknown"

                return {
                    "id": new_id,
                    "message_id": message_id or "unknown",
                    "thread_id": thread_id,
                    "status": "sent"
                }
            except Exception as e:
                print(f"Error sending email: {e}")
                return {"status": "error", "error": str(e)}

def send_reply(thread_id: str, to: str, subject: str, body: str, message_id: str = None) -> dict:
    """
    Synchronous wrapper to send an email reply using the Gmail MCP server.
    """
    return asyncio.run(send_reply_async(thread_id, to, subject, body, message_id))

# ---------------------------------------------------------------------------
# Google Calendar Direct API Integration
# ---------------------------------------------------------------------------

def get_calendar_service():
    """
    Initializes and returns the Google Calendar v3 API service using local token.json.
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

def fetch_upcoming_events(max_results: int = 10) -> List[Dict]:
    """
    Fetches the upcoming events from the user's primary calendar.
    """
    service = get_calendar_service()
    # Get current time in RFC3339 format
    now = datetime.now(timezone.utc).isoformat()
    
    events_result = service.events().list(
        calendarId='primary', timeMin=now,
        maxResults=max_results, singleEvents=True,
        orderBy='startTime').execute()
        
    events = events_result.get('items', [])
    return events

def create_calendar_event(title: str, start_time: str, end_time: str, attendees: List[str] = None) -> Dict:
    """
    Creates a new calendar event. 
    start_time and end_time should be ISO 8601 strings (e.g. '2023-10-15T09:00:00-07:00').
    """
    service = get_calendar_service()
    
    event = {
        'summary': title,
        'start': {
            'dateTime': start_time,
            'timeZone': 'UTC',
        },
        'end': {
            'dateTime': end_time,
            'timeZone': 'UTC',
        },
    }
    
    if attendees:
        event['attendees'] = [{'email': email} for email in attendees]
        
    created_event = service.events().insert(calendarId='primary', body=event).execute()
    return created_event

def update_calendar_event(event_id: str, updates: dict) -> Dict:
    """
    Updates an existing calendar event. 
    updates is a dict with keys to update (e.g. {'summary': 'New Title'})
    """
    service = get_calendar_service()
    
    # First fetch the existing event
    event = service.events().get(calendarId='primary', eventId=event_id).execute()
    
    # Apply updates
    for key, value in updates.items():
        event[key] = value
        
    updated_event = service.events().update(calendarId='primary', eventId=event_id, body=event).execute()
    return updated_event

def respond_to_meeting(event_id: str, response: str) -> Dict:
    """
    Responds to a meeting invitation.
    response must be one of: 'accepted', 'declined', 'tentative'
    """
    service = get_calendar_service()
    
    # First fetch the existing event
    event = service.events().get(calendarId='primary', eventId=event_id).execute()
    
    # In order to respond, we must find ourselves in the attendees list and update our responseStatus
    # Since we are using the primary calendar, 'primary' usually maps to the authenticated user's email.
    
    # Get the user's email to find themselves in the attendee list
    calendar_list = service.calendarList().get(calendarId='primary').execute()
    user_email = calendar_list.get('id')
    
    attendees = event.get('attendees', [])
    for attendee in attendees:
        if attendee.get('email') == user_email or attendee.get('self'):
            attendee['responseStatus'] = response
            break
            
    event['attendees'] = attendees
    
    updated_event = service.events().update(
        calendarId='primary', 
        eventId=event_id, 
        body=event,
        sendUpdates='all'  # notifies the organizer
    ).execute()
    
    return updated_event

def format_digest(results: List[Dict]):
    """
    Prints a clean, readable digest to the terminal grouped by priority.
    """
    today = datetime.now().strftime("%B %d, %Y")
    print(f"\n=======================================================")
    print(f"INBOX DIGEST - {today}")
    print(f"Total Threads: {len(results)}")
    print(f"=======================================================\n")
    
    current_priority = None
    
    for t in results:
        priority = str(t.get('priority', 'UNKNOWN')).upper()
        
        # Add a separator line when priority group changes
        if priority != current_priority:
            if current_priority is not None:
                print("-" * 55)
            print(f"=== {priority} ===")
            current_priority = priority
            
        sender = t.get('sender', 'Unknown')
        subject = t.get('subject', 'No Subject')
        reason = t.get('reason', '')
        
        print(f"[{priority}] {sender} | {subject} - {reason}")
        
if __name__ == "__main__":
    # Test the function by fetching and printing the results
    print("Fetching last 20 inbox threads via Gmail MCP...")
    fetched_threads = fetch_threads()
    
    print(f"Successfully fetched {len(fetched_threads)} threads.\n")
    print("Triaging threads... This may take a few seconds...\n")
    
    # Classify the threads using triage_inbox
    results = triage_inbox(fetched_threads)
    
    # Print the formatted digest
    format_digest(results)
