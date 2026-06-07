# Discovery Agent — Aivar Innovations
> Level 1 (Systems Discovery) + Level 2 (Integration Gap Analysis)
> Powered by **Groq AI — 100% FREE, ultra-fast**

---

## ⚡ Quick Start (3 minutes)

### 1. Get your FREE Groq API key (no credit card needed)
→ https://console.groq.com  → Sign up → API Keys → Create key

### 2. Install dependencies
```bash
pip install -r requirements.txt
```

### 3. Set API key + run

**Mac / Linux**
```bash
export GROQ_API_KEY=gsk_xxxxxxxxxxxx
python app.py
```

**Windows CMD**
```cmd
set GROQ_API_KEY=gsk_xxxxxxxxxxxx
python app.py
```

**Windows PowerShell**
```powershell
$env:GROQ_API_KEY="gsk_xxxxxxxxxxxx"
python app.py
```

### 4. Open browser
```
http://localhost:5000
```

---

## 🤖 Model Used
`llama-3.3-70b-versatile` via Groq — completely free on the free tier.
Ultra fast: responses in 1-3 seconds. Change `GROQ_MODEL` in app.py to switch models:
- `llama-3.3-70b-versatile` — best quality (default)
- `llama-3.1-8b-instant`    — fastest responses
- `mixtral-8x7b-32768`      — largest context window

---

## 🔍 Level 1 — Systems Discovery

Upload company documents (or paste text) and the agent extracts every software system:

| Field | Description |
|---|---|
| Name | Exact system name |
| Category | CRM, ERP, Finance, HR, Analytics… |
| Auth Method | OAuth2, API Key, SAML, Basic Auth… |
| Key Entities | Contacts, Invoices, Orders… |
| Business Processes | Workflows this system supports |
| Criticality | Critical / High / Medium / Low |
| Confidence Score | 95%+ explicit · 70-94% inferred · <70% flagged |

**Supported formats:** PDF · TXT · Markdown · CSV · JSON · Excel · PNG · JPG

---

## 🗺 Level 2 — Integration Gap Analysis

Describe your automation goals in plain English. The agent:
- Maps each use case to systems it needs
- Traces data flows (source → destination, trigger, entity type)
- Marks integrations as EXISTING or MISSING
- Estimates effort: Small / Medium / Large / XL
- Prioritizes by frequency × business impact × downstream blocking
- Produces a phased implementation roadmap
- Exports structured JSON for planning/ticketing tools

---

## 📁 Project Structure
```
discovery-agent/
├── app.py              ← Flask backend + Groq API logic
├── requirements.txt    ← Python dependencies
├── README.md           ← This file
├── uploads/            ← Temp file storage (auto-created)
└── templates/
    └── index.html      ← Full frontend UI
```

---

## 💰 Cost: $0.00
Groq free tier includes:
- 14,400 requests/day on llama-3.3-70b
- No credit card required
- Resets daily
