"""The Draft Desk — unified Streamlit dashboard for the AI ghostwriter pipeline.

Phases: Inbox & Triage → Draft Generation → Approval Gate → Export Proof
"""

import json
import os
from datetime import datetime
from typing import Any

import streamlit as st
from dotenv import load_dotenv

load_dotenv()

def load_cloud_secrets():
    try:
        # Securely load files from Streamlit Cloud secrets to local disk for the Node.js MCP server
        base_dir = os.path.dirname(os.path.abspath(__file__))
        global_dir = os.path.expanduser("~/.gmail-mcp")
        os.makedirs(global_dir, exist_ok=True)
        
        if hasattr(st, "secrets"):
            if "GCP_OAUTH_KEYS" in st.secrets:
                content = st.secrets["GCP_OAUTH_KEYS"]
                with open(os.path.join(base_dir, "gcp-oauth.keys.json"), "w") as f:
                    f.write(content)
                with open(os.path.join(global_dir, "gcp-oauth.keys.json"), "w") as f:
                    f.write(content)
            
            if "GCP_CREDENTIALS" in st.secrets:
                content = st.secrets["GCP_CREDENTIALS"]
                with open(os.path.join(base_dir, "credentials.json"), "w") as f:
                    f.write(content)
                with open(os.path.join(global_dir, "credentials.json"), "w") as f:
                    f.write(content)
    except Exception:
        pass

load_cloud_secrets()

# ── Local imports ─────────────────────────────────────────────────────────
from triage import triage_inbox
from draft_machine import draft_reply
from task_logger import log_action

# ══════════════════════════════════════════════════════════════════════════
# Page Config
# ══════════════════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="The Draft Desk",
    page_icon="✍️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ══════════════════════════════════════════════════════════════════════════
# Custom CSS
# ══════════════════════════════════════════════════════════════════════════
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap');

    .stApp {
        background-color: #0f0f1a;
        font-family: 'Inter', sans-serif;
    }

    /* ── Sidebar ─────────────────────────────────────── */
    section[data-testid="stSidebar"] {
        background: linear-gradient(180deg, #1a1a2e 0%, #16213e 100%);
    }

    /* ── Thread card ─────────────────────────────────── */
    .thread-card {
        background: linear-gradient(135deg, #1e1e36 0%, #1a1a2e 100%);
        border: 1px solid #2d2d50;
        border-radius: 10px;
        padding: 1.2rem 1.4rem;
        margin-bottom: 0.8rem;
        transition: border-color 0.2s ease;
    }
    .thread-card:hover {
        border-color: #6c63ff;
    }
    .thread-subject {
        font-size: 1.05rem;
        font-weight: 600;
        color: #e8e8ff;
        margin-bottom: 0.3rem;
    }
    .thread-meta {
        font-size: 0.82rem;
        color: #8888aa;
    }
    .thread-snippet {
        font-size: 0.9rem;
        color: #b0b0cc;
        margin-top: 0.5rem;
        line-height: 1.5;
        white-space: pre-wrap;
    }

    /* ── Priority badges ─────────────────────────────── */
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 12px;
        font-size: 0.75rem;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }
    .badge-urgent    { background: #ff4d4d22; color: #ff6b6b; border: 1px solid #ff4d4d44; }
    .badge-needs-reply { background: #ffa50022; color: #ffb347; border: 1px solid #ffa50044; }
    .badge-fyi       { background: #4dabf722; color: #74c0fc; border: 1px solid #4dabf744; }
    .badge-later     { background: #51cf6622; color: #69db7c; border: 1px solid #51cf6644; }

    /* ── Phase header ────────────────────────────────── */
    .phase-header {
        font-size: 1.6rem;
        font-weight: 700;
        color: #e8e8ff;
        margin-bottom: 0.3rem;
    }
    .phase-sub {
        font-size: 0.95rem;
        color: #8888aa;
        margin-bottom: 1.5rem;
    }

    /* ── Nav button helper ────────────────────────────── */
    div[data-testid="stButton"] button {
        border-radius: 8px;
    }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════════════════
# Session State
# ══════════════════════════════════════════════════════════════════════════
DEFAULTS: dict[str, Any] = {
    "threads": [],           # raw threads loaded from JSON or Gmail
    "triaged": {},           # dict keyed by priority: urgent, needs reply, fyi, later
    "drafts": {},            # thread_id → draft text
    "approved": {},          # thread_id → approved draft dict
    "rejected": set(),       # thread_ids that were rejected
    "sent": set(),           # thread_ids that were successfully sent
    "booked": {},            # thread_id → booking details / event dict
    "current_phase": "inbox",  # inbox | draft | approve | export
    "source": "Sample threads",
    "pipeline_running": False,
    "pipeline_log": [],
}

for key, default in DEFAULTS.items():
    if key not in st.session_state:
        st.session_state[key] = default


# ══════════════════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════════════════
PRIORITY_BADGE = {
    "urgent": "badge-urgent",
    "needs reply": "badge-needs-reply",
    "fyi": "badge-fyi",
    "later": "badge-later",
}

def load_sample_threads() -> list[dict]:
    with open("sample_threads.json", "r", encoding="utf-8") as f:
        return json.load(f)

def group_by_priority(triaged: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for t in triaged:
        p = t.get("priority", "later")
        groups.setdefault(p, []).append(t)
    return groups

def get_last_sender(thread: dict) -> str:
    msgs = thread.get("messages", [])
    if msgs:
        return msgs[-1].get("from", "Unknown")
    return thread.get("sender", "Unknown")

def get_snippet(thread: dict) -> str:
    msgs = thread.get("messages", [])
    if msgs:
        body = msgs[-1].get("body", "")
        clean = " ".join(body.split())
        return clean[:180] + ("…" if len(clean) > 180 else "")
    return thread.get("snippet", "")

def get_send_reply():
    import engine
    import importlib
    importlib.reload(engine)
    return engine.send_reply

def _get_calendar_engine():
    import calendar_engine
    import importlib
    importlib.reload(calendar_engine)
    return calendar_engine

def _get_draft_reply():
    import draft_machine
    import importlib
    importlib.reload(draft_machine)
    return draft_machine.draft_reply

def save_approved_draft(thread: dict, draft_text: str, source: str, model: str = "gemini-3.5-flash"):
    """Save the approved draft to a JSON file."""
    record = {
        "timestamp": datetime.now().isoformat(),
        "source": source,
        "thread_subject": thread.get("subject", ""),
        "reply_to": get_last_sender(thread),
        "model": model,
        "char_count": len(draft_text),
        "draft": draft_text
    }
    file_name = "approved_drafts.json"
    
    data = []
    if os.path.exists(file_name):
        try:
            with open(file_name, "r") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            pass
            
    data.append(record)
    with open(file_name, "w") as f:
        json.dump(data, f, indent=2)

def generate_proof_markdown(approved: dict) -> str:
    lines = ["# ✍️ My AI Chief of Staff — Draft Proof\n\n"]
    lines.append(f"**Date Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n")
    
    for tid, data in approved.items():
        subject = data.get("subject", "No Subject")
        thread = data.get("thread", {})
        draft = data.get("draft", "")
        
        lines.append(f"## Thread: {subject}\n\n")
        lines.append("### Original Messages\n")
        for msg in thread.get("messages", []):
            lines.append(f"> **From:** {msg.get('from', 'Unknown')} | **Date:** {msg.get('date', '')}\n")
            body = msg.get('body', '').replace('\n', '\n> ')
            lines.append(f"> \n> {body}\n>\n")
            
        lines.append("\n### Approved Draft\n")
        lines.append(f"```\n{draft}\n```\n\n")
        lines.append("---\n\n")
        
    return "".join(lines)

def generate_proof_html(approved: dict) -> str:
    html = f"""
    <html>
    <head>
    <style>
        body {{ background-color: #0f0f1a; color: #e8e8ff; font-family: 'Inter', sans-serif; padding: 2rem; }}
        h1 {{ color: #ffffff; text-align: center; }}
        .thread-container {{ display: grid; grid-template-columns: 1fr 1fr; gap: 2rem; margin-bottom: 3rem; background: #1a1a2e; padding: 1.5rem; border-radius: 12px; }}
        .original-side {{ border-left: 4px solid #ff9f43; padding-left: 1rem; }}
        .draft-side {{ border-left: 4px solid #10ac84; padding-left: 1rem; }}
        .msg {{ background: #1e1e36; padding: 1rem; border-radius: 8px; margin-bottom: 1rem; }}
        .draft-box {{ background: #10ac8422; padding: 1rem; border-radius: 8px; white-space: pre-wrap; font-family: monospace; font-size: 1.1em; border: 1px solid #10ac8444; }}
        .meta {{ font-size: 0.85em; color: #a8a8a8; margin-bottom: 0.5rem; }}
    </style>
    </head>
    <body>
    <h1>✍️ My AI Chief of Staff — Draft Proof</h1>
    <p style="text-align: center; color: #a8a8a8;">Generated on {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</p>
    """
    
    for tid, data in approved.items():
        subject = data.get("subject", "No Subject")
        thread = data.get("thread", {})
        draft = data.get("draft", "")
        
        html += f"<h2>{subject}</h2>"
        html += "<div class='thread-container'>"
        
        # Left: Original
        html += "<div class='original-side'><h3>📩 Original Messages</h3>"
        for msg in thread.get("messages", []):
            sender = msg.get("from", "Unknown")
            date = msg.get("date", "")
            body = msg.get("body", "").replace("\n", "<br>")
            html += f"<div class='msg'><div class='meta'>From: {sender} | Date: {date}</div><div>{body}</div></div>"
        html += "</div>"
        
        # Right: Draft
        html += "<div class='draft-side'><h3>🤖 Approved Draft</h3>"
        html += f"<div class='draft-box'>{draft}</div>"
        html += "</div>"
        
        html += "</div>"
        
    html += "<hr style='border:1px solid #333; margin: 3rem 0;'>"
    html += "<h2>📋 Action Log</h2>"
    from task_logger import get_action_log
    actions = get_action_log()
    if not actions:
        html += "<p style='color: #a8a8a8;'>No actions logged yet.</p>"
    else:
        html += "<table style='width: 100%; border-collapse: collapse; margin-top: 1rem;'>"
        html += "<tr style='border-bottom: 2px solid #333; text-align: left;'><th style='padding: 10px;'>Action</th><th style='padding: 10px;'>Subject</th><th style='padding: 10px;'>Detail</th><th style='padding: 10px;'>Timestamp</th></tr>"
        for action in actions:
            is_sent = action.get("action_type") == "sent"
            icon = "➡️" if is_sent else "📆"
            action_type_str = action.get("action_type", "unknown").upper()
            act_subject = action.get('thread_subject', 'No Subject')
            detail = action.get("detail", "")
            
            ts_str = action.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts_str)
                formatted_ts = dt.strftime("%b %d %I:%M %p")
            except Exception:
                formatted_ts = ts_str

            html += f"<tr style='border-bottom: 1px solid #333;'><td style='padding: 10px;'>{icon} <b>{action_type_str}</b></td><td style='padding: 10px;'><b>{act_subject}</b></td><td style='padding: 10px;'><code style='background:#1e1e36;padding:4px 8px;border-radius:4px;'>{detail}</code></td><td style='padding: 10px; color: #a8a8a8;'>{formatted_ts}</td></tr>"
        html += "</table>"
        
    html += "</body></html>"
    return html


def run_full_pipeline() -> list[str]:
    logs = []
    try:
        source = st.session_state.source
        logs.append(f"Starting full pipeline. Source: {source}")
        
        if source == "Sample threads":
            raw = load_sample_threads()
            logs.append("Loaded sample threads.")
        else:
            from engine import fetch_threads
            fetched = fetch_threads()
            raw = []
            for item in fetched:
                raw.append({
                    "id": item.get("thread id", ""),
                    "message_id": item.get("message_id", ""),
                    "subject": item.get("subject", "No Subject"),
                    "messages": [
                        {
                            "from": item.get("sender", "Unknown"),
                            "date": item.get("date", ""),
                            "body": item.get("snippet", ""),
                        }
                    ],
                })
            logs.append(f"Fetched {len(raw)} threads from engine.")
            
        triaged = triage_inbox(raw)
        st.session_state.threads = triaged
        st.session_state.triaged = group_by_priority(triaged)
        logs.append(f"Triaged {len(triaged)} threads.")
        
        st.session_state.drafts = {}
        st.session_state.approved = {}
        st.session_state.rejected = set()
        st.session_state.sent = set()
        st.session_state.booked = {}
        logs.append("Reset downstream session state.")
        
        draft_reply_func = _get_draft_reply()
        urgent_needs = st.session_state.triaged.get("urgent", []) + st.session_state.triaged.get("needs reply", [])
        logs.append(f"Found {len(urgent_needs)} threads requiring drafts.")
        
        for thread in urgent_needs:
            tid = thread.get("id")
            try:
                draft_text = draft_reply_func(thread)
                st.session_state.drafts[tid] = {
                    "draft": draft_text,
                    "char_count": len(draft_text),
                    "subject": thread.get("subject", ""),
                    "thread": thread
                }
                logs.append(f"Successfully drafted reply for thread {tid}.")
            except Exception as e:
                logs.append(f"Error drafting reply for thread {tid}: {str(e)}")
                
        st.session_state.current_phase = "approve"
        logs.append("Pipeline complete. Transitioning to Approval Gate.")
        
    except Exception as e:
        logs.append(f"Pipeline failed: {str(e)}")
        
    return logs


def _render_pipeline_execution():
    pipeline_log = []
    
    with st.status("Running full pipeline...", expanded=True) as status:
        # Step 1: Fetch
        status.update(label="Step 1: Fetching threads...")
        source = st.session_state.source
        pipeline_log.append(f"Starting pipeline with source: {source}")
        try:
            if source == "Sample threads":
                raw = load_sample_threads()
                pipeline_log.append("Loaded sample threads.")
            else:
                from engine import fetch_threads
                fetched = fetch_threads()
                raw = []
                for item in fetched:
                    raw.append({
                        "id": item.get("thread id", ""),
                        "message_id": item.get("message_id", ""),
                        "subject": item.get("subject", "No Subject"),
                        "messages": [
                            {
                                "from": item.get("sender", "Unknown"),
                                "date": item.get("date", ""),
                                "body": item.get("snippet", ""),
                            }
                        ],
                    })
                pipeline_log.append(f"Fetched {len(raw)} threads from engine.")
            st.write(f"✅ Fetched {len(raw)} threads ({source})")
        except Exception as e:
            pipeline_log.append(f"Pipeline failed at fetch: {str(e)}")
            st.write(f"❌ Failed to fetch threads: {e}")
            status.update(label="Pipeline failed", state="error")
            return

        # Step 2: Triage
        status.update(label="Step 2: Triaging threads...")
        try:
            triaged = triage_inbox(raw)
            st.session_state.threads = triaged
            st.session_state.triaged = group_by_priority(triaged)
            pipeline_log.append(f"Triaged {len(triaged)} threads.")
            st.write(f"✅ Triaged {len(triaged)} threads")
            
            st.session_state.drafts = {}
            st.session_state.approved = {}
            st.session_state.rejected = set()
            st.session_state.sent = set()
            st.session_state.booked = {}
            pipeline_log.append("Reset downstream session state.")
        except Exception as e:
            pipeline_log.append(f"Pipeline failed at triage: {str(e)}")
            st.write(f"❌ Failed during triage: {e}")
            status.update(label="Pipeline failed", state="error")
            return

        # Step 3: Draft loop
        status.update(label="Step 3: Drafting replies...")
        urgent_needs = st.session_state.triaged.get("urgent", []) + st.session_state.triaged.get("needs reply", [])
        pipeline_log.append(f"Found {len(urgent_needs)} threads requiring drafts.")
        
        if len(urgent_needs) == 0:
            st.write("✅ No drafts required.")
        else:
            draft_reply_func = _get_draft_reply()
            for i, thread in enumerate(urgent_needs, start=1):
                tid = thread.get("id")
                try:
                    status.update(label=f"Step 3: Drafting replies ({i}/{len(urgent_needs)})...")
                    draft_text = draft_reply_func(thread)
                    st.session_state.drafts[tid] = {
                        "draft": draft_text,
                        "char_count": len(draft_text),
                        "subject": thread.get("subject", ""),
                        "thread": thread
                    }
                    pipeline_log.append(f"Successfully drafted reply for thread {tid}.")
                    st.write(f"✅ Drafted reply for: {thread.get('subject', 'No Subject')}")
                except Exception as e:
                    pipeline_log.append(f"Error drafting reply for thread {tid}: {str(e)}")
                    st.write(f"❌ Failed draft for {thread.get('subject', 'No Subject')}: {e}")
        
        status.update(label="Pipeline complete!", state="complete")
        pipeline_log.append("Pipeline complete. Transitioning to Approval Gate.")

    st.session_state.pipeline_log = pipeline_log
    st.session_state.current_phase = "approve"
    st.session_state.pipeline_running = False
    st.rerun()


def _render_thread_card(t: dict, idx: int, badge_cls: str, priority: str):
    """Render a single thread card with an Open Full Thread expander."""
    sender = get_last_sender(t)
    subject = t.get("subject", "(No subject)")
    reason = t.get("reason", "")
    snippet = get_snippet(t)
    thread_id = t.get("id", f"thread_{idx}")
    msgs = t.get("messages", [])
    date = msgs[-1].get("date", "") if msgs else t.get("date", "")
    msg_count = len(msgs)

    st.markdown(f"""
    <div class="thread-card">
        <div style="display:flex;justify-content:space-between;align-items:start;">
            <div class="thread-subject">{subject}</div>
            <div style="display:flex;gap:0.6rem;align-items:center;">
                <span class="badge {badge_cls}">{priority}</span>
                <span style="font-size:0.78rem;color:#6c6c8a;">ID: <code style="color:#74c0fc;">{thread_id}</code></span>
            </div>
        </div>
        <div class="thread-meta">From: {sender} &nbsp;•&nbsp; {date} &nbsp;•&nbsp; {msg_count} message{"s" if msg_count != 1 else ""}</div>
        <div class="thread-snippet">{snippet}</div>
        <div style="margin-top:0.5rem;font-size:0.82rem;color:#9999bb;">💡 {reason}</div>
    </div>
    """, unsafe_allow_html=True)

    with st.expander(f"Open full thread — {subject}", expanded=False):
        for m_idx, msg in enumerate(msgs, start=1):
            m_sender = msg.get("from", "Unknown")
            m_date = msg.get("date", "")
            m_body = msg.get("body", "")

            st.markdown(f"**Message {m_idx}**")
            st.markdown(f"**From:** {m_sender}  \n**Date:** {m_date}")
            st.markdown(f"```\n{m_body}\n```")
            if m_idx < len(msgs):
                st.divider()


# ══════════════════════════════════════════════════════════════════════════
# Sidebar
# ══════════════════════════════════════════════════════════════════════════
with st.sidebar:
    st.markdown("## ✍️ The Draft Desk")
    st.caption("AI-powered email ghostwriter with human approval.")

    st.divider()
    # ── Source selector ──────────────────────────────────────────────
    st.session_state.source = st.radio(
        "Email source",
        ["Sample threads", "Gmail via engine.py"],
        index=0 if st.session_state.get("source", "Sample threads") == "Sample threads" else 1,
    )

    st.divider()

    if st.button("🚀 Run Full Pipeline", type="primary", use_container_width=True):
        st.session_state.pipeline_running = True
        st.rerun()
    st.caption("Fetches, triages, and drafts -- stops at Approval Gate.")

    st.divider()

    # ── Navigation ───────────────────────────────────────────────────
    st.markdown("**Navigation**")

    nav_items = [
        ("📥 Inbox & Triage", "inbox"),
        ("📝 Draft Generation", "draft"),
        ("✅ Approval Gate", "approve"),
        ("📤 Export Proof", "export"),
    ]

    for label, phase in nav_items:
        btn_type = "primary" if st.session_state.current_phase == phase else "secondary"
        if st.button(label, key=f"nav_{phase}", use_container_width=True, type=btn_type):
            st.session_state.current_phase = phase
            st.rerun()

    st.divider()

    # ── Session stats ────────────────────────────────────────────────
    st.markdown("📊 **Session stats**")
    st.markdown(f"- Threads loaded: **{len(st.session_state.threads)}**")
    triaged_count = sum(len(g) for g in st.session_state.triaged.values()) if st.session_state.triaged else 0
    st.markdown(f"- Triaged: **{triaged_count}**")
    st.markdown(f"- Drafts generated: **{len(st.session_state.drafts)}**")
    st.markdown(f"- Approved: **{len(st.session_state.approved)}**")
    st.markdown(f"- Rejected: **{len(st.session_state.rejected)}**")
    st.markdown(f"- Phase: `{st.session_state.current_phase}`")

    if st.button("🔄 Reset session", use_container_width=True):
        for key, default in DEFAULTS.items():
            st.session_state[key] = type(default)() if isinstance(default, (dict, list, set)) else default
        st.rerun()


# ══════════════════════════════════════════════════════════════════════════
# PHASE 1 — Inbox & Triage
# ══════════════════════════════════════════════════════════════════════════
if st.session_state.pipeline_running:
    _render_pipeline_execution()
elif st.session_state.current_phase == "inbox":
    st.markdown('<div class="phase-header">📥 Inbox & Triage</div>', unsafe_allow_html=True)
    st.markdown('<div class="phase-sub">Pull emails, auto-classify by priority, and decide what needs a reply.</div>', unsafe_allow_html=True)

    # ── Action buttons ────────────────────────────────────────────────
    btn_left, btn_right, _ = st.columns([1, 1, 4])

    with btn_left:
        if st.button("⚡ Pull & Triage", type="primary", use_container_width=True):
            with st.spinner("Loading threads and triaging with Gemini…"):
                try:
                    if st.session_state.source == "Sample threads":
                        raw = load_sample_threads()
                    else:
                        from engine import fetch_threads
                        fetched = fetch_threads()
                        # Convert Gmail format → our standard thread format
                        raw = []
                        for item in fetched:
                            raw.append({
                                "id": item.get("thread id", ""),
                                "message_id": item.get("message_id", ""),
                                "subject": item.get("subject", "No Subject"),
                                "messages": [
                                    {
                                        "from": item.get("sender", "Unknown"),
                                        "date": item.get("date", ""),
                                        "body": item.get("snippet", ""),
                                    }
                                ],
                            })

                    triaged = triage_inbox(raw)
                    st.session_state.threads = triaged
                    st.session_state.triaged = group_by_priority(triaged)
                    st.rerun()
                except Exception as e:
                    st.error(f"Error during triage: {e}")

    with btn_right:
        if st.button("🧹 Clear", use_container_width=True):
            st.session_state.threads = []
            st.session_state.triaged = {}
            st.rerun()

    # ── Display triaged threads ──────────────────────────────────────
    if st.session_state.threads:
        st.divider()

        # ── Sort control ─────────────────────────────────────────────
        sort_option = st.selectbox(
            "Sort by",
            ["Priority", "Most recent first", "Oldest first"],
            index=0,
        )

        # ── Build display order ──────────────────────────────────────
        PRIORITY_EMOJI = {
            "urgent":      "🔴 Urgent",
            "needs reply":  "🟠 Needs Reply",
            "fyi":          "🔵 FYI",
            "ignore":       "⚪ Ignore",
            "later":        "🟢 Later",
        }
        PRIORITY_ORDER = ["urgent", "needs reply", "fyi", "ignore", "later"]

        if sort_option == "Priority":
            # Render grouped by priority
            needs_reply_count = 0

            for priority in PRIORITY_ORDER:
                group = st.session_state.triaged.get(priority, [])
                if not group:
                    continue

                emoji_label = PRIORITY_EMOJI.get(priority, f"⬜ {priority.title()}")
                badge_cls = PRIORITY_BADGE.get(priority, "badge-later")

                st.markdown(f"### {emoji_label} ({len(group)})")

                if priority in ("urgent", "needs reply"):
                    needs_reply_count += len(group)

                for idx, t in enumerate(group):
                    _render_thread_card(t, idx, badge_cls, priority)

            # ── Call-to-action ────────────────────────────────────────
            if needs_reply_count > 0:
                st.divider()
                st.success(f"📝 **{needs_reply_count} thread{'s' if needs_reply_count != 1 else ''} need a reply** → go to **Draft Generation**")
                if st.button("➡️ Go to Draft Generation", type="primary"):
                    st.session_state.current_phase = "draft"
                    st.rerun()

        else:
            # Flat list sorted by date
            threads_display = list(st.session_state.threads)
            threads_display = sorted(
                threads_display,
                key=lambda t: (t.get("messages", [{}])[-1].get("date", "") if t.get("messages") else t.get("date", "")),
                reverse=(sort_option == "Most recent first"),
            )

            total = len(threads_display)
            st.markdown(f"### Threads ({total})")

            needs_reply_count = 0
            for idx, t in enumerate(threads_display):
                priority = t.get("priority", "later")
                badge_cls = PRIORITY_BADGE.get(priority, "badge-later")
                if priority in ("urgent", "needs reply"):
                    needs_reply_count += 1
                _render_thread_card(t, idx, badge_cls, priority)

            if needs_reply_count > 0:
                st.divider()
                st.success(f"📝 **{needs_reply_count} thread{'s' if needs_reply_count != 1 else ''} need a reply** → go to **Draft Generation**")
                if st.button("➡️ Go to Draft Generation", type="primary", key="goto_draft_flat"):
                    st.session_state.current_phase = "draft"
                    st.rerun()

    elif not st.session_state.threads:
        st.info("👆 Click **Pull & Triage** to load and classify email threads.")


# ══════════════════════════════════════════════════════════════════════════
# PHASE 2 — Draft Generation
# ══════════════════════════════════════════════════════════════════════════
elif st.session_state.current_phase == "draft":
    st.markdown('<div class="phase-header">📝 Draft Generation</div>', unsafe_allow_html=True)
    st.markdown('<div class="phase-sub">Generate AI reply drafts for actionable threads (urgent + needs reply).</div>', unsafe_allow_html=True)

    # ── Collect actionable threads ────────────────────────────────────
    actionable = []
    for priority in ("urgent", "needs reply"):
        actionable.extend(st.session_state.triaged.get(priority, []))

    if not actionable:
        st.warning("No actionable threads found. Go to **Inbox & Triage** first and pull some threads.")
        if st.button("⬅️ Go to Inbox & Triage"):
            st.session_state.current_phase = "inbox"
            st.rerun()
    else:
        st.markdown(f"**{len(actionable)} actionable thread{'s' if len(actionable) != 1 else ''}** (urgent + needs reply)")

        # ── Count how many already have drafts ────────────────────────
        already_drafted = sum(1 for t in actionable if t.get("id", "") in st.session_state.drafts)
        remaining = len(actionable) - already_drafted

        # ── Generate All Drafts button ────────────────────────────────
        btn_gen, btn_clear, _ = st.columns([1, 1, 4])

        with btn_gen:
            generate_clicked = st.button(
                f"⚡ Generate All Drafts ({remaining} left)" if remaining > 0 else "✅ All Drafted",
                type="primary",
                use_container_width=True,
                disabled=(remaining == 0),
            )

        with btn_clear:
            if st.button("🧹 Clear Drafts", use_container_width=True):
                st.session_state.drafts = {}
                st.rerun()

        if generate_clicked:
            progress_bar = st.progress(0, text="Starting draft generation…")
            threads_to_draft = [t for t in actionable if t.get("id", "") not in st.session_state.drafts]

            for i, thread in enumerate(threads_to_draft):
                thread_id = thread.get("id", thread.get("thread id", f"thread_{i}"))
                subject = thread.get("subject", "(No subject)")
                progress_bar.progress(
                    (i) / len(threads_to_draft),
                    text=f"Drafting reply for: {subject}…",
                )

                try:
                    draft_text = draft_reply(thread)
                    st.session_state.drafts[thread_id] = {
                        "draft": draft_text,
                        "subject": subject,
                        "thread": thread,
                        "char_count": len(draft_text),
                    }
                except Exception as e:
                    st.error(f"Failed to draft reply for '{subject}': {e}")

            progress_bar.progress(1.0, text="✅ All drafts generated!")
            st.rerun()

        # ── Display drafted threads ───────────────────────────────────
        st.divider()

        for thread in actionable:
            thread_id = thread.get("id", thread.get("thread id", ""))
            subject = thread.get("subject", "(No subject)")
            priority = thread.get("priority", "later")
            badge_cls = PRIORITY_BADGE.get(priority, "badge-later")
            msgs = thread.get("messages", [])
            draft_data = st.session_state.drafts.get(thread_id)

            status_icon = "✅" if draft_data else "⏳"

            with st.expander(f"{status_icon} {subject}", expanded=bool(draft_data)):
                col_thread, col_draft = st.columns(2, gap="large")

                with col_thread:
                    st.markdown("#### 📩 Latest Message")
                    if msgs:
                        last_msg = msgs[-1]
                        st.markdown(f"**From:** {last_msg.get('from', 'Unknown')}")
                        st.markdown(f"**Date:** {last_msg.get('date', '')}")
                        st.markdown(f"""<div class="thread-card" style="margin-top:0.5rem;">
<div style="white-space:pre-wrap;font-size:0.92rem;color:#b0b0cc;line-height:1.6;">{last_msg.get('body', '')}</div>
</div>""", unsafe_allow_html=True)
                    else:
                        st.info("No messages in this thread.")

                with col_draft:
                    st.markdown("#### 🤖 AI Draft")
                    if draft_data:
                        st.markdown(f"<span style='font-size:0.82rem;color:#8888aa;'>Char count: {draft_data['char_count']}</span>", unsafe_allow_html=True)
                        edited_text = st.text_area(
                            "Draft Content",
                            value=draft_data['draft'],
                            height=200,
                            label_visibility="collapsed",
                            key=f"edit_draft_phase_{thread_id}"
                        )
                        if edited_text != draft_data['draft']:
                            st.session_state.drafts[thread_id]['draft'] = edited_text
                            st.session_state.drafts[thread_id]['char_count'] = len(edited_text)
                    else:
                        st.info("Not yet drafted. Click **Generate All Drafts**.")

        # ── Call-to-action ────────────────────────────────────────────
        if already_drafted == len(actionable) and already_drafted > 0:
            st.divider()
            st.success(f"✅ **{already_drafted} draft{'s' if already_drafted != 1 else ''} ready** → go to **Approval Gate**")
            if st.button("➡️ Go to Approval Gate", type="primary"):
                st.session_state.current_phase = "approve"
                st.rerun()


# ══════════════════════════════════════════════════════════════════════════
# PHASE 3 — Approval Gate
# ══════════════════════════════════════════════════════════════════════════
elif st.session_state.current_phase == "approve":
    st.markdown('<div class="phase-header">✅ Approval Gate</div>', unsafe_allow_html=True)
    st.markdown('<div class="phase-sub">Review each AI draft. Approve (optionally edited), regenerate, or reject. Nothing moves to Export until you explicitly approve it.</div>', unsafe_allow_html=True)

    if st.session_state.get("pipeline_log"):
        with st.expander("Pipeline Execution Log"):
            for log_entry in st.session_state.pipeline_log:
                if "ERROR" in log_entry.upper() or "FAILED" in log_entry.upper():
                    st.write(f"❌ {log_entry}")
                else:
                    st.write(f"✅ {log_entry}")
            if st.button("Clear log"):
                st.session_state.pipeline_log = []
                st.rerun()
        st.divider()

    active_drafts = [
        (tid, data) for tid, data in st.session_state.drafts.items()
        if tid not in st.session_state.rejected
    ]
    unapproved_count = len(st.session_state.drafts) - len(st.session_state.approved) - len(st.session_state.rejected)

    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Total drafts", len(st.session_state.drafts))
    m2.metric("✅ Approved", len(st.session_state.approved))
    m3.metric("❌ Rejected", len(st.session_state.rejected))
    m4.metric("⏳ Pending", unapproved_count)
    st.divider()

    if unapproved_count == 0 and len(st.session_state.drafts) > 0:
        st.success("🎉 All drafted threads have been reviewed! You can now send them or proceed to Export.")
        st.balloons()
        if len(st.session_state.approved) > 0:
            if st.button("➡️ Go to Export Proof", type="primary"):
                st.session_state.current_phase = "export"
                st.rerun()
        st.divider()
    elif len(st.session_state.drafts) == 0:
        st.info("No drafts have been generated yet. Go to **Draft Generation** first.")

    if active_drafts:
        if unapproved_count > 0:
            st.markdown(f"**{unapproved_count} draft{'s' if unapproved_count != 1 else ''} pending approval**")
        else:
            st.markdown(f"**{len(active_drafts)} approved draft{'s' if len(active_drafts) != 1 else ''} ready for sending**")

        for tid, draft_data in active_drafts:
            subject = draft_data.get("subject", "(No subject)")
            original_draft = draft_data.get("draft", "")
            thread = draft_data.get("thread", {})

            is_sent = tid in st.session_state.sent
            status_badge = "🚀 SENT" if is_sent else "📝 Review"
            
            with st.expander(f"{status_badge}: {subject}", expanded=not is_sent):
                col_thread, col_draft = st.columns([1, 1], gap="large")

                with col_thread:
                    st.markdown("#### 📩 Full Thread")
                    for m_idx, msg in enumerate(thread.get("messages", []), start=1):
                        st.markdown(f"**From:** {msg.get('from', 'Unknown')} | **Date:** {msg.get('date', '')}")
                        st.info(msg.get("body", ""))

                with col_draft:
                    st.markdown("#### 🤖 Review & Edit")
                    edited_draft = st.text_area(
                        "Modify the draft below before approving or sending:",
                        value=original_draft,
                        height=250,
                        key=f"edit_{tid}",
                        disabled=is_sent
                    )

                    if is_sent:
                        st.success("This draft has been sent successfully!")
                    else:
                        # Actions
                        is_meeting = thread.get("category") == "meeting-request"
                        is_booked = tid in st.session_state.booked
                        is_approved = tid in st.session_state.approved
                        
                        if not is_approved:
                            col_approve, col_regen, col_reject = st.columns([1, 1, 1])
                            send_container = None
                            book_container = None
                        else:
                            col_approve = None
                            if is_meeting:
                                send_container, book_container, col_regen, col_reject = st.columns([1, 1, 1, 1])
                            else:
                                send_container, col_regen, col_reject = st.columns([1, 1, 1])
                                book_container = None
                            
                        if col_approve is not None:
                            with col_approve:
                                if st.button("✅ Approve", key=f"approve_{tid}", type="secondary", use_container_width=True):
                                    source = "ai" if edited_draft.strip() == original_draft.strip() else "edited"
                                    st.session_state.approved[tid] = {
                                        "draft": edited_draft,
                                        "source": source,
                                        "subject": subject,
                                        "thread": thread
                                    }
                                    save_approved_draft(thread, edited_draft, source)
                                    st.rerun()
                            
                        if send_container is not None:
                            with send_container:
                                if st.button("🚀 Send", key=f"send_{tid}", type="primary", use_container_width=True):
                                    # Extract recipient email
                                    sender_str = get_last_sender(thread)
                                    recipient = sender_str
                                    import re
                                    match = re.search(r'<(.*?)>', sender_str)
                                    if match:
                                        recipient = match.group(1).strip()
                                    
                                    msg_id = thread.get("message_id")
                                    send_reply_fn = get_send_reply()
                                    with st.spinner("Sending email..."):
                                        result = send_reply_fn(
                                            thread_id=tid,
                                            to=recipient,
                                            subject=subject,
                                            body=edited_draft,
                                            message_id=msg_id
                                        )
                                        if result.get("status") == "sent":
                                            st.session_state.sent.add(tid)
                                            # Also auto-approve if sent
                                            source = "ai" if edited_draft.strip() == original_draft.strip() else "edited"
                                            st.session_state.approved[tid] = {
                                                "draft": edited_draft,
                                                "source": source,
                                                "subject": subject,
                                                "thread": thread
                                            }
                                            save_approved_draft(thread, edited_draft, source)
                                            st.success("Email sent successfully!")
                                            log_action(
                                                action_type="sent",
                                                thread_subject=thread.get("subject", "No Subject"),
                                                detail=recipient,
                                                action_id=result.get("id", "Unknown_ID"),
                                            )
                                            st.rerun()
                                        else:
                                            st.error(f"Failed to send email: {result.get('error', 'Unknown error')}")
                                    
                        if book_container is not None:
                            with book_container:
                                if is_booked:
                                    html_link = st.session_state.booked[tid].get("htmlLink", "#")
                                    st.info(f"**Meeting booked.** [Open in Calendar]({html_link})", icon="📅")
                                else:
                                    if st.button("📅 Book", key=f"book_{tid}", type="primary", use_container_width=True):
                                        cal_engine = _get_calendar_engine()
                                        with st.spinner("Parsing meeting details..."):
                                            parsed = cal_engine.parse_meeting_request(thread)
                                        
                                        if "parsing_error" in parsed:
                                            st.error(f"Parsing error: {parsed['parsing_error']}")
                                        else:
                                            p_times = parsed.get('proposed_times', [])
                                            f_times = ", ".join(p_times) if isinstance(p_times, list) else str(p_times)
                                            p_att = parsed.get('attendees', [])
                                            f_att = ", ".join(p_att) if isinstance(p_att, list) and p_att else str(p_att)
                                            if not f_att: f_att = "[]"
                                            
                                            st.info(f"**Topic:** {parsed.get('topic')}\n\n**Duration:** {parsed.get('duration_minutes', 30)} min\n\n**Proposed times:** {f_times}\n\n**Attendees:** {f_att}")
                                            
                                            with st.spinner("Finding free slot..."):
                                                slot = cal_engine.find_free_slot(
                                                    parsed.get("proposed_times", []),
                                                    parsed.get("duration_minutes", 30)
                                                )
                                            
                                            if not slot:
                                                st.error("No free slot found!")
                                            elif "error" in slot:
                                                st.error(slot["error"])
                                            else:
                                                with st.spinner("Booking event..."):
                                                    try:
                                                        import re
                                                        sender_str = get_last_sender(thread)
                                                        recipient = sender_str
                                                        match = re.search(r'<(.*?)>', sender_str)
                                                        if match:
                                                            recipient = match.group(1).strip()
                                                        
                                                        actual_attendees = [
                                                            email for email in parsed.get("attendees", [])
                                                            if "pavan@example.com" not in email.lower()
                                                        ]
                                                        if recipient and recipient not in actual_attendees:
                                                            actual_attendees.append(recipient)
                                                            
                                                        event = cal_engine.create_event(
                                                            summary=parsed.get("topic", "Meeting"),
                                                            start_time=slot["start"],
                                                            duration_minutes=parsed.get("duration_minutes", 30),
                                                            attendees=actual_attendees,
                                                            description="Automatically booked via Chief of Staff"
                                                        )
                                                        st.session_state.booked[tid] = event
                                                        st.success("Booked successfully!")
                                                        log_action(
                                                            action_type="booked",
                                                            thread_subject=thread.get("subject", "No Subject"),
                                                            detail=parsed.get("topic", thread.get("subject", "No Subject")),
                                                            action_id=event["id"],
                                                        )
                                                        st.rerun()
                                                    except Exception as e:
                                                        st.error(f"Booking error: {e}")
                        
                        with col_regen:
                            if st.button("🔄 Regen", key=f"regen_{tid}", use_container_width=True):
                                with st.spinner("Regenerating draft..."):
                                    try:
                                        new_draft = draft_reply(thread)
                                        st.session_state.drafts[tid]["draft"] = new_draft
                                        if tid in st.session_state.approved:
                                            del st.session_state.approved[tid]
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Failed to regenerate: {e}")
        
                        with col_reject:
                            if st.button("🗑️ Reject", key=f"reject_{tid}", use_container_width=True):
                                st.session_state.rejected.add(tid)
                                st.rerun()


# ══════════════════════════════════════════════════════════════════════════
# PHASE 4 — Export Proof
# ══════════════════════════════════════════════════════════════════════════
elif st.session_state.current_phase == "export":
    st.markdown('<div class="phase-header">📤 Export Proof</div>', unsafe_allow_html=True)
    st.markdown('<div class="phase-sub">View and export all approved drafts with full audit trail.</div>', unsafe_allow_html=True)
    
    if not st.session_state.approved:
        st.info("No approved drafts yet. Go to **Approval Gate** to approve some drafts first.")
    else:
        st.markdown(f"### 🎉 {len(st.session_state.approved)} Approved Drafts")
        st.success("Share with #MyAIChiefOfStaff to earn your Ghostwriter badge!")

        md_content = generate_proof_markdown(st.session_state.approved)
        html_content = generate_proof_html(st.session_state.approved)

        col_md, col_html, _ = st.columns([1, 1, 3])
        with col_md:
            st.download_button(
                label="📄 Download Proof (Markdown)",
                data=md_content,
                file_name=f"ghostwriter_proof_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
                mime="text/markdown",
                type="primary"
            )
        with col_html:
            st.download_button(
                label="🌐 Download Proof (HTML)",
                data=html_content,
                file_name=f"ghostwriter_proof_{datetime.now().strftime('%Y%m%d_%H%M')}.html",
                mime="text/html",
                type="secondary"
            )

        st.divider()
        st.markdown("### Preview")
        
        for tid, data in st.session_state.approved.items():
            subject = data.get("subject", "(No subject)")
            thread = data.get("thread", {})
            draft = data.get("draft", "")

            with st.expander(f"✅ {subject}", expanded=False):
                col_thread, col_draft = st.columns([1, 1], gap="large")
                with col_thread:
                    st.markdown("#### 📩 Original Messages")
                    for msg in thread.get("messages", []):
                        st.markdown(f"**From:** {msg.get('from', 'Unknown')}")
                        st.info(msg.get("body", ""))
                with col_draft:
                    st.markdown("#### 🤖 Approved Draft")
                    st.markdown(f"""<div class="draft-box" style="background:#10ac8422;padding:1.2rem;border-radius:8px;border:1px solid #10ac8444;white-space:pre-wrap;font-size:0.95rem;color:#e8e8ff;line-height:1.6;">{draft}</div>""", unsafe_allow_html=True)
        
        st.divider()
        st.subheader("Action Log")
        from task_logger import get_action_log
        
        actions = get_action_log()
        if not actions:
            st.info("No actions logged yet.")
        else:
            for action in actions:
                c1, c2, c3, c4 = st.columns([1, 2, 2, 1])
                
                is_sent = action.get("action_type") == "sent"
                icon = "➡️" if is_sent else "📆"
                action_type_str = action.get("action_type", "unknown").upper()
                c1.markdown(f"{icon} **{action_type_str}**")
                
                c2.markdown(f"**{action.get('thread_subject', 'No Subject')}**")
                
                detail = action.get("detail", "")
                c3.markdown(f"`{detail}`")
                
                ts_str = action.get("timestamp", "")
                try:
                    dt = datetime.fromisoformat(ts_str)
                    formatted_ts = dt.strftime("%b %d %I:%M %p")
                except Exception:
                    formatted_ts = ts_str
                c4.caption(formatted_ts)
