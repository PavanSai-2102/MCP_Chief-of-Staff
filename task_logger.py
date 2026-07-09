import json
import os
from datetime import datetime

LOG_FILE = "action_log.json"

def get_action_log():
    if not os.path.exists(LOG_FILE):
        return []
    try:
        with open(LOG_FILE, "r") as f:
            data = json.load(f)
            if isinstance(data, list):
                return data
            return []
    except (json.JSONDecodeError, IOError):
        return []

def log_action(action_type, thread_subject, detail, action_id):
    records = get_action_log()
    
    record = {
        "timestamp": datetime.now().isoformat(),
        "action_type": action_type,
        "thread_subject": thread_subject,
        "detail": detail,
        "id": action_id
    }
    
    records.append(record)
    
    with open(LOG_FILE, "w") as f:
        json.dump(records, f, indent=2)

def clear_log():
    with open(LOG_FILE, "w") as f:
        json.dump([], f, indent=2)
