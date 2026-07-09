import json
import os
from datetime import datetime
from typing import Any

import streamlit as st

# We import the required tools from the previous step
from context_builder import format_thread_history
from draft_machine import SAMPLE_THREADS, draft_reply_with_metadata

st.set_page_config(
    page_title="AI Ghostwriter Gate",
    page_icon="📧",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for dark theme and styling
st.markdown("""
<style>
    .stApp {
        background-color: #1a1a2e;
        color: #e6e6e6;
    }
    .thread-msg {
        background-color: #16213e;
        padding: 1rem;
        border-radius: 8px;
        margin-bottom: 1rem;
        border-left: 4px solid #0f3460;
    }
    .thread-meta {
        font-size: 0.85em;
        color: #a8a8a8;
        margin-bottom: 0.5rem;
    }
    .draft-box {
        background-color: #2a2a4a;
        padding: 1.5rem;
        border-radius: 8px;
        border: 1px solid #4a4e69;
        font-family: 'Georgia', serif;
        font-size: 1.1em;
        line-height: 1.6;
        white-space: pre-wrap;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# State Management
# ---------------------------------------------------------------------------
if "draft_meta" not in st.session_state:
    st.session_state.draft_meta = None
if "status" not in st.session_state:
    st.session_state.status = "none"  # "none", "approved", "editing", "rejected"
if "generation_count" not in st.session_state:
    st.session_state.generation_count = 0


# ---------------------------------------------------------------------------
# API Key Management
# ---------------------------------------------------------------------------
def get_api_key() -> str | None:
    from dotenv import load_dotenv
    load_dotenv()
    
    # 1. Try os environment (.env)
    if "GEMINI_API_KEY" in os.environ:
        return os.environ["GEMINI_API_KEY"]
        
    # 2. Try streamlit secrets safely
    try:
        if "GEMINI_API_KEY" in st.secrets:
            return st.secrets["GEMINI_API_KEY"]
    except Exception:
        pass
    
    return None

api_key = get_api_key()


# ---------------------------------------------------------------------------
# Core Functions
# ---------------------------------------------------------------------------
def generate_draft(thread_data: dict[str, Any]):
    """Generate a draft using the draft machine."""
    with st.spinner("Generating draft with Gemini 2.5 Flash..."):
        try:
            result = draft_reply_with_metadata(thread_data)
            st.session_state.draft_meta = result
            st.session_state.status = "none"
            st.session_state.generation_count += 1
        except Exception as e:
            st.error(f"Error generating draft: {e}")

def save_approved_draft(thread: dict, draft_text: str, draft_meta: dict):
    """Save the approved draft to a JSON file."""
    record = {
        "timestamp": datetime.now().isoformat(),
        "source": "ai",
        "thread_subject": thread.get("subject", ""),
        "reply_to": draft_meta.get("replying_to", ""),
        "model": draft_meta.get("model", ""),
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

# ---------------------------------------------------------------------------
# Sidebar Settings
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("⚙️ Configuration")
    
    if not api_key:
        st.warning("GEMINI_API_KEY not found in secrets or env.")
        user_key = st.text_input("Enter GEMINI_API_KEY:", type="password")
        if user_key:
            os.environ["GEMINI_API_KEY"] = user_key
            st.success("API Key saved for this session!")
    else:
        # Make sure it's in env so draft_machine can pick it up
        os.environ["GEMINI_API_KEY"] = api_key
        st.success("✅ API Key configured")

    st.divider()
    
    st.header("📩 Select Thread")
    
    # Let user pick a sample or custom JSON
    thread_options = {f"Sample {i+1}: {t['subject']}": t for i, t in enumerate(SAMPLE_THREADS)}
    thread_options["Custom JSON"] = None
    
    selected_option = st.selectbox("Choose a thread to reply to:", list(thread_options.keys()))
    
    if selected_option == "Custom JSON":
        custom_json_str = st.text_area("Paste thread JSON here:", height=200)
        try:
            current_thread = json.loads(custom_json_str) if custom_json_str else None
        except json.JSONDecodeError:
            st.error("Invalid JSON")
            current_thread = None
    else:
        current_thread = thread_options[selected_option]

    st.divider()
    
    # Generate Button
    if st.button("Generate Draft", type="primary", use_container_width=True):
        if current_thread:
            if "GEMINI_API_KEY" not in os.environ:
                st.error("Please provide an API key first.")
            else:
                generate_draft(current_thread)
        else:
            st.error("Please select or provide a valid thread.")
            
    st.divider()
    
    st.markdown("📊 **Session stats**")
    st.markdown(f"- Drafts generated: {st.session_state.generation_count}")
    st.markdown(f"- Current status: {st.session_state.status}")
    
    if st.button("🔄 Reset session", use_container_width=True):
        st.session_state.draft_meta = None
        st.session_state.status = "none"
        st.session_state.generation_count = 0
        st.rerun()


# ---------------------------------------------------------------------------
# Main UI Layout
# ---------------------------------------------------------------------------
st.title("🛡️ Human-in-the-Loop Approval Gate")
st.caption("Review the AI-generated draft below, then APPROVE, EDIT, or REJECT it. Nothing is sent without your explicit approval.")

with st.expander("ℹ️ How this gate works"):
    st.markdown("""
### The safety contract

1. **The AI** (`draft_machine.py` + Gemini) generates a draft reply.
2. **Nothing is ever sent automatically.** You must explicitly click **APPROVE**.
3. You can **EDIT** the draft first - your edited version (not the AI's) is what gets saved.
4. You can **REJECT** a draft and ask for a new one - rejected drafts are discarded (not saved).
5. **APPROVE** writes the draft to `approved_drafts.json` with a timestamp. That file is the queue your downstream "send" step (if any) should consume from - and it should still be a human-triggered step.

### Session state

- `current_draft` - the text on screen
- `draft_meta` - model / recipient / length metadata
- `status` - `none` | `approved` | `editing` | `rejected`
- `generation_count` - how many drafts this session has produced
- `edit_buffer` - working text inside the EDIT text area

### Run

```bash
streamlit run approval_gate.py
```
    """)

col1, col2 = st.columns([1, 1], gap="large")

# -- LEFT COLUMN: Thread History --
with col1:
    st.subheader("Thread History")
    if current_thread:
        subject = current_thread.get("subject", "(No Subject)")
        st.markdown(f"**Subject:** {subject}")
        st.divider()
        
        messages = current_thread.get("messages", [])
        if not messages:
            st.info("No messages in this thread.")
            
        for msg in messages:
            sender = msg.get("from", "Unknown")
            date = msg.get("date", "")
            body = msg.get("body", "")
            
            st.markdown(f"""
            <div class="thread-msg">
                <div class="thread-meta"><b>From:</b> {sender} &nbsp;|&nbsp; <b>Date:</b> {date}</div>
                <div style="white-space: pre-wrap;">{body}</div>
            </div>
            """, unsafe_allow_html=True)
    else:
        st.info("Select a thread from the sidebar to view history.")


# -- RIGHT COLUMN: Draft Action --
with col2:
    st.subheader("AI Draft Output")
    
    if not st.session_state.draft_meta:
        st.info("Click 'Generate Draft' in the sidebar to create a reply.")
    else:
        meta = st.session_state.draft_meta
        draft_text = meta["draft"]
        
        # Display Status
        if st.session_state.status == "approved":
            st.success("✅ Draft Approved and Saved! Ready to send.")
        elif st.session_state.status == "rejected":
            st.error("❌ Draft Rejected. Please generate a new one.")
        
        # Display metadata
        st.caption(f"Model: {meta['model']} | Char count: {meta['char_count']} | Generates: {st.session_state.generation_count}")
        
        # Edit mode vs Normal mode
        if st.session_state.status == "editing":
            edited_draft = st.text_area("Edit Draft:", value=draft_text, height=250)
            
            col_save, col_cancel = st.columns(2)
            with col_save:
                if st.button("Confirm Edit & Approve", type="primary", use_container_width=True):
                    # Save it back to meta
                    st.session_state.draft_meta["draft"] = edited_draft
                    st.session_state.status = "approved"
                    save_approved_draft(current_thread, edited_draft, st.session_state.draft_meta)
                    st.rerun()
            with col_cancel:
                if st.button("Cancel Edit", use_container_width=True):
                    st.session_state.status = "none"
                    st.rerun()
                    
        else:
            # Display draft block
            st.markdown(f'<div class="draft-box">{draft_text}</div>', unsafe_allow_html=True)
            
            # Show Action Buttons if not already approved or rejected
            if st.session_state.status == "none":
                st.markdown("<br/>", unsafe_allow_html=True)
                btn_col1, btn_col2, btn_col3 = st.columns(3)
                
                with btn_col1:
                    if st.button("✅ Approve", use_container_width=True):
                        st.session_state.status = "approved"
                        save_approved_draft(current_thread, draft_text, st.session_state.draft_meta)
                        st.rerun()
                
                with btn_col2:
                    if st.button("✏️ Edit", use_container_width=True):
                        st.session_state.status = "editing"
                        st.rerun()
                
                with btn_col3:
                    if st.button("🗑️ Reject", use_container_width=True):
                        st.session_state.status = "rejected"
                        st.rerun()
