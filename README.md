# 📬 MCP Chief of Staff

**The Draft Desk** – An AI-powered email ghostwriter with human approval. 

This project acts as an automated "Chief of Staff" for your Gmail inbox. It seamlessly pulls unread threads, uses AI to automatically triage and draft replies based on a customized tone profile, and presents them in a beautiful Streamlit dashboard for your final human approval before dispatch.

## ✨ Features
- **Automated Triage & Drafting:** Uses Google Gemini (`gemini-2.5-flash`) to instantly analyze inbox threads and draft context-aware replies.
- **Gmail MCP Server Integration:** Utilizes a custom local Model Context Protocol (MCP) server to securely interface with your Gmail account without exposing raw API keys directly to the frontend.
- **Approval Gate:** A robust Streamlit dashboard that lets you review, manually edit, reject, or approve AI drafts before any email is actually sent.
- **Calendar Integration:** (Experimental) Capabilities to detect and schedule meetings directly into Google Calendar based on email context.
- **Action Logging:** Transparent tracking of all AI actions, preserving sent emails and booked events directly into local JSON logs and HTML exports.

## 🚀 Quick Setup

### 1. Prerequisites
- Python 3.10+
- Node.js (for the Gmail MCP Server)
- A Google Cloud Project with the **Gmail API** and **Google Calendar API** enabled.

### 2. Installation
Clone the repository and install the Python dependencies:
```bash
git clone https://github.com/PavanSai-2102/MCP_Chief-of-Staff.git
cd MCP_Chief-of-Staff
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt  # (or install streamlit, google-generativeai, mcp, etc.)
```

Next, build the Gmail MCP Server:
```bash
cd Gmail-MCP-Server
npm install
npm run build
cd ..
```

### 3. Configuration
Create a `.env` file in the root directory and add your Google Gemini API key:
```env
GEMINI_API_KEY=your_gemini_api_key_here
```

Place your Google Cloud OAuth client credentials in a file named `gcp-oauth.keys.json` in the project root.

### 4. Running the App
Start the Streamlit dashboard:
```bash
streamlit run app.py
```

On your first run, the app will automatically prompt you to authenticate your Google Account via your web browser to securely grant Gmail and Calendar permissions.

## 🛠️ Architecture
- `app.py`: The main Streamlit dashboard UI and pipeline coordinator.
- `engine.py`: Interfaces with the Gmail MCP Server over standard I/O (JSON-RPC) to fetch threads and send emails.
- `draft_machine.py` & `triage.py`: Core AI logic for analyzing threads and generating customized responses.
- `Gmail-MCP-Server/`: The standalone TypeScript server implementing the Model Context Protocol for Gmail API access.
