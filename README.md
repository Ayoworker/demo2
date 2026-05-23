# 🏺 Chiedza Crafts — AI Business Website
**AI-powered lead capture, FAQ answering, and WhatsApp handoff for Zimbabwean SMEs**

---

## 📁 File Structure

```
project/
├── index.html          ← Frontend (open in browser)
├── main.py             ← FastAPI backend (AI + lead API)
├── knowledge_base.json ← Business info / FAQ (edit this!)
├── requirements.txt    ← Python dependencies
├── leads.json          ← Auto-created when leads are captured
└── README.md
```

---

## 🚀 Setup & Run (Step by Step)

### Step 1 — Install Ollama (the local AI engine)

```bash
# macOS / Linux
curl -fsSL https://ollama.com/install.sh | sh

# Windows: download from https://ollama.com/download
```

### Step 2 — Pull the AI model (choose one)

```bash
# Recommended (fast, good quality)
ollama pull mistral

# Alternative (larger, more capable)
ollama pull llama3
```

### Step 3 — Start the Ollama server

```bash
ollama serve
# Keep this running in a terminal tab
```

### Step 4 — Install Python dependencies

```bash
pip install -r requirements.txt
```

### Step 5 — Start the FastAPI backend

```bash
uvicorn main:app --reload --port 8000
```

You should see:
```
INFO:     Uvicorn running on http://0.0.0.0:8000
```

### Step 6 — Open the website

Simply open `index.html` in your browser. The AI chat widget in the bottom-right corner will connect automatically.

---

## ⚙️ Configuration

### Change business info (frontend)
Edit the `BUSINESS_INFO` object at the top of `index.html`:
```js
const BUSINESS_INFO = {
  name: "Your Business Name",
  phone: "263771234567",
  email: "you@example.co.zw",
  ...
};
```

### Change AI model
In `main.py`, change:
```python
OLLAMA_MODEL = "mistral"  # or "llama3", "gemma2", etc.
```

### Change the knowledge base
Edit `knowledge_base.json` — the AI will only answer based on this file. Update services, prices, FAQ, and hours as needed.

---

## 📧 Optional: Email Notifications for New Leads

Set these environment variables to get emailed when a HOT lead comes in:

```bash
# Linux / macOS
export SMTP_FROM="yourgmail@gmail.com"
export SMTP_PASS="your-app-password"   # Gmail App Password (not your main password)
export SMTP_TO="owner@yourbusiness.com"

# Windows
set SMTP_FROM=yourgmail@gmail.com
set SMTP_PASS=your-app-password
set SMTP_TO=owner@yourbusiness.com
```

> **Get a Gmail App Password**: Google Account → Security → 2-Step Verification → App Passwords

---

## 🔌 API Endpoints

| Method | Endpoint   | Description                          |
|--------|------------|--------------------------------------|
| GET    | /          | API status check                     |
| GET    | /health    | Check Ollama connectivity            |
| POST   | /chat      | Send message, get AI reply           |
| POST   | /lead      | Save a qualified lead                |
| GET    | /leads     | List all captured leads (JSON)       |

---

## 🏷️ Lead Tagging Logic

| Tag       | Criteria                                              |
|-----------|-------------------------------------------------------|
| 🔥 HOT   | Has contact number + budget + urgent timeline         |
| ☀️ WARM  | Has contact number + budget OR urgency                |
| 🧊 COLD  | Has contact number only                               |

---

## 💡 How the AI Works

1. User opens chat widget → greets them warmly
2. User asks questions → AI answers using `knowledge_base.json` ONLY
3. User shows buying intent (e.g. "I need a quote") → AI asks qualifying questions one at a time
4. User provides phone number → lead is automatically submitted to `/lead`
5. AI-generated summary is shown + **WhatsApp handoff button** pre-filled with their details

---

## 🔄 Reusing for Other Clients

To deploy for a new SME:
1. Copy the entire project folder
2. Edit `knowledge_base.json` with their business info
3. Edit `BUSINESS_INFO` in `index.html`
4. Done! 🎉

---

## 🛠️ Troubleshooting

| Problem | Solution |
|---------|----------|
| Chat widget shows "AI Offline" | Run `ollama serve` and restart `uvicorn` |
| "Model not found" error | Run `ollama pull mistral` |
| CORS error in browser | Make sure backend is running on port 8000 |
| Slow AI responses | Normal for first message — model loads then speeds up |
| No leads in leads.json | Make sure user provides a phone number in chat |
