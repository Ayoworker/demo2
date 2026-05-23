"""
Chiedza Crafts — AI Sales Assistant Backend
FastAPI + Ollama (mistral / llama3)

Run:
  pip install fastapi uvicorn httpx python-dotenv
  uvicorn main:app --reload --port 8000
"""

import json
import logging
import os
import re
import smtplib
import uuid
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger(__name__)

# ── Config ────────────────────────────────────────────────────────────────────
OLLAMA_URL   = os.getenv("OLLAMA_URL",   "http://localhost:11434/api/chat")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "mistral")          # or llama3

LEADS_FILE   = Path("leads.json")
KB_FILE      = Path("knowledge_base.json")

# Optional SMTP (Gmail). Set env vars to enable.
SMTP_FROM    = os.getenv("SMTP_FROM",    "")
SMTP_PASS    = os.getenv("SMTP_PASS",    "")
SMTP_TO      = os.getenv("SMTP_TO",      "")   # business owner email

# ── Load knowledge base ───────────────────────────────────────────────────────
def load_kb() -> dict:
    if KB_FILE.exists():
        return json.loads(KB_FILE.read_text())
    raise RuntimeError(f"knowledge_base.json not found at {KB_FILE.resolve()}")

KB = load_kb()

def kb_summary() -> str:
    """Convert knowledge base to a compact prompt-friendly string."""
    lines = [
        f"Business: {KB['business_name']}",
        f"Tagline: {KB['tagline']}",
        f"Location: {KB['location']}",
        f"Hours: {KB['hours']}",
        f"Phone: {KB['phone']}",
        f"Email: {KB['email']}",
        "",
        "=== SERVICES ===",
    ]
    for s in KB["services"]:
        lines.append(f"- {s['name']}: {s['description']} (Lead time: {s['lead_time']})")
    lines.append("")
    lines.append("=== PRICING ===")
    for p in KB["pricing"]:
        lines.append(f"- {p['item']}: {p['price']}")
    lines.append("")
    lines.append("=== FAQ ===")
    for f in KB["faq"]:
        lines.append(f"Q: {f['question']}\nA: {f['answer']}")
    return "\n".join(lines)

SYSTEM_PROMPT = f"""You are a friendly and helpful virtual sales assistant for {KB['business_name']}, a Zimbabwean craft business.

Your job is to:
1. Welcome visitors warmly
2. Answer questions ONLY using the business information below — never make up prices, services, or facts
3. When a user shows buying interest (e.g. "I want to order", "I need a quote", "how much for..."), gently guide them through these qualifying questions ONE AT A TIME:
   - What product or service are you interested in?
   - When do you need it by?
   - Do you have a budget in mind? (optional — say it's fine to skip)
   - What is the best contact number to reach them on?
4. Once you have their contact number, tell them: "Perfect! I've noted your details. Our team will reach out to you shortly. You can also click the WhatsApp button to connect directly."
5. Keep responses SHORT (2–4 sentences max). Use friendly, simple English.
6. Never discuss competitors, politics, or anything unrelated to the business.
7. If asked something you don't know, say: "I'm not sure about that — please contact us directly on WhatsApp or call {KB['phone']}."

=== BUSINESS INFORMATION ===
{kb_summary()}
=== END OF BUSINESS INFORMATION ===

Remember: You ONLY know what is written above. Do not invent information."""

# ── FastAPI app ───────────────────────────────────────────────────────────────
app = FastAPI(title="Chiedza Crafts AI Assistant", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],   # Tighten in production
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────────────────────
class Message(BaseModel):
    role: str   # "user" | "assistant"
    content: str

class ChatRequest(BaseModel):
    session_id: str
    message: str
    history: list[Message] = []

class LeadData(BaseModel):
    session_id: str
    name: str | None = None
    service: str | None = None
    urgency: str | None = None
    budget: str | None = None
    contact: str | None = None
    notes: str | None = None
    conversation: list[Message] = []

class ChatResponse(BaseModel):
    reply: str
    intent_detected: bool = False

class LeadResponse(BaseModel):
    success: bool
    lead_id: str
    tag: str          # HOT | WARM | COLD
    summary: str

# ── Ollama helper ─────────────────────────────────────────────────────────────
async def call_ollama(messages: list[dict]) -> str:
    payload = {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": False,
        "options": {
            "temperature": 0.4,
            "top_p": 0.9,
            "num_predict": 300,
        },
    }
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(OLLAMA_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
            return data["message"]["content"].strip()
    except httpx.ConnectError:
        log.error("Cannot connect to Ollama. Is it running? Run: ollama serve")
        raise HTTPException(
            status_code=503,
            detail=(
                "AI service unavailable. Make sure Ollama is running "
                f"(`ollama serve`) and the model is pulled "
                f"(`ollama pull {OLLAMA_MODEL}`)."
            ),
        )
    except Exception as exc:
        log.exception("Ollama error")
        raise HTTPException(status_code=500, detail=str(exc))

# ── Intent detection ──────────────────────────────────────────────────────────
INTENT_KEYWORDS = [
    "quote", "order", "buy", "purchase", "price", "how much", "cost",
    "need", "want", "interested", "enquire", "enquiry", "book", "urgent",
    "delivery", "custom", "bulk", "wholesale",
]

def detect_intent(text: str) -> bool:
    t = text.lower()
    return any(k in t for k in INTENT_KEYWORDS)

# ── Lead tagging ──────────────────────────────────────────────────────────────
def tag_lead(lead: LeadData) -> str:
    has_contact = bool(lead.contact and lead.contact.strip())
    has_budget  = bool(lead.budget  and lead.budget.strip()
                       and lead.budget.lower() not in ("none", "n/a", "no", "skip", "not sure"))
    is_urgent   = bool(lead.urgency and any(
        w in lead.urgency.lower()
        for w in ["today", "tomorrow", "asap", "urgent", "this week", "now"]
    ))
    if has_contact and has_budget and is_urgent:
        return "HOT 🔥"
    if has_contact and (has_budget or is_urgent):
        return "WARM ☀️"
    return "COLD 🧊"

# ── Lead summary generator ────────────────────────────────────────────────────
async def generate_summary(lead: LeadData) -> str:
    conversation_text = "\n".join(
        f"{m.role.upper()}: {m.content}" for m in lead.conversation[-12:]
    )
    prompt = f"""You are a lead qualification assistant. Based on the conversation below, write a 2–3 sentence business lead summary for the owner of {KB['business_name']}.

Include: what product/service the customer wants, their urgency, budget (if mentioned), and contact details.
Be factual — only use what is in the conversation. Do not invent anything.

CONVERSATION:
{conversation_text}

LEAD DETAILS:
- Name: {lead.name or 'Not provided'}
- Service: {lead.service or 'Not specified'}
- Urgency: {lead.urgency or 'Not specified'}
- Budget: {lead.budget or 'Not specified'}
- Contact: {lead.contact or 'Not provided'}

Write the summary now (2–3 sentences, plain text, no bullet points):"""

    messages = [{"role": "user", "content": prompt}]
    try:
        return await call_ollama(messages)
    except Exception:
        # Fallback manual summary
        return (
            f"Lead for {lead.service or 'unspecified service'}. "
            f"Urgency: {lead.urgency or 'unknown'}. "
            f"Budget: {lead.budget or 'not provided'}. "
            f"Contact: {lead.contact or 'not provided'}."
        )

# ── Save lead ─────────────────────────────────────────────────────────────────
def save_lead(record: dict) -> None:
    existing: list = []
    if LEADS_FILE.exists():
        try:
            existing = json.loads(LEADS_FILE.read_text())
        except json.JSONDecodeError:
            existing = []
    existing.append(record)
    LEADS_FILE.write_text(json.dumps(existing, indent=2, ensure_ascii=False))
    log.info("Lead saved → leads.json  [id=%s]", record["lead_id"])

# ── Send email notification (optional) ───────────────────────────────────────
def send_email_notification(record: dict) -> None:
    if not all([SMTP_FROM, SMTP_PASS, SMTP_TO]):
        return
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = f"[{record['tag']}] New Lead — {record.get('service', 'Unknown service')}"
        msg["From"]    = SMTP_FROM
        msg["To"]      = SMTP_TO

        body = f"""
New lead from {KB['business_name']} AI Assistant

Lead ID  : {record['lead_id']}
Tag      : {record['tag']}
Time     : {record['timestamp']}

--- DETAILS ---
Name     : {record.get('name', 'N/A')}
Service  : {record.get('service', 'N/A')}
Urgency  : {record.get('urgency', 'N/A')}
Budget   : {record.get('budget', 'N/A')}
Contact  : {record.get('contact', 'N/A')}

--- SUMMARY ---
{record['summary']}
        """.strip()

        msg.attach(MIMEText(body, "plain"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(SMTP_FROM, SMTP_PASS)
            server.sendmail(SMTP_FROM, SMTP_TO, msg.as_string())
        log.info("Email notification sent to %s", SMTP_TO)
    except Exception:
        log.exception("Failed to send email notification (non-fatal)")

# ── ROUTES ────────────────────────────────────────────────────────────────────

@app.get("/")
async def root():
    return {
        "status": "running",
        "business": KB["business_name"],
        "model": OLLAMA_MODEL,
    }

@app.get("/health")
async def health():
    """Quick health check — also tests Ollama connectivity."""
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get("http://localhost:11434/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:
        ollama_ok = False
    return {
        "api": "ok",
        "ollama": "ok" if ollama_ok else "unreachable — run `ollama serve`",
        "model": OLLAMA_MODEL,
        "knowledge_base": KB["business_name"],
    }

@app.post("/chat", response_model=ChatResponse)
async def chat(req: ChatRequest):
    """Main chat endpoint. Receives user message + history, returns AI reply."""
    log.info("[%s] USER: %s", req.session_id[:8], req.message[:80])

    # Build Ollama messages array
    ollama_messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT}
    ]
    for m in req.history[-14:]:   # keep last 14 turns to stay in context
        ollama_messages.append({"role": m.role, "content": m.content})
    ollama_messages.append({"role": "user", "content": req.message})

    reply = await call_ollama(ollama_messages)
    intent = detect_intent(req.message)

    log.info("[%s] ASSISTANT: %s", req.session_id[:8], reply[:80])
    return ChatResponse(reply=reply, intent_detected=intent)

@app.post("/lead", response_model=LeadResponse)
async def capture_lead(lead: LeadData):
    """Stores a qualified lead with AI-generated summary and tag."""
    log.info("[%s] Capturing lead: service=%s contact=%s",
             lead.session_id[:8], lead.service, lead.contact)

    tag     = tag_lead(lead)
    summary = await generate_summary(lead)
    lead_id = str(uuid.uuid4())[:8].upper()

    record = {
        "lead_id":   lead_id,
        "tag":       tag,
        "timestamp": datetime.now().isoformat(),
        "session_id": lead.session_id,
        "name":      lead.name,
        "service":   lead.service,
        "urgency":   lead.urgency,
        "budget":    lead.budget,
        "contact":   lead.contact,
        "notes":     lead.notes,
        "summary":   summary,
        "conversation": [m.model_dump() for m in lead.conversation],
    }

    save_lead(record)
    send_email_notification(record)

    log.info("Lead %s tagged as %s", lead_id, tag)
    return LeadResponse(success=True, lead_id=lead_id, tag=tag, summary=summary)

@app.get("/leads")
async def list_leads(limit: int = 20):
    """Returns the latest leads (for a simple owner dashboard)."""
    if not LEADS_FILE.exists():
        return {"leads": [], "total": 0}
    try:
        leads = json.loads(LEADS_FILE.read_text())
    except json.JSONDecodeError:
        leads = []
    leads_sorted = sorted(leads, key=lambda x: x.get("timestamp", ""), reverse=True)
    return {"leads": leads_sorted[:limit], "total": len(leads)}
