# Mailwise

An AI-powered email assistant that triages an entire inbox at once: classifies incoming emails, extracts action items, retrieves context from past correspondence using RAG, and drafts personalized replies in the user's own writing style — with confidence-based routing to decide what's safe to auto-draft versus what needs human review.

## Why

Most inboxes mix real correspondence with marketing noise and automated notifications. Mailwise processes the whole inbox in one pass and lands you on a triage view: what's urgent, what's routine with a draft ready, and what's noise already filtered out — instead of manually reading and replying to each email one at a time. Drafts open directly in Gmail for review and sending; nothing is ever sent automatically.

## Architecture

```
Gmail API → Incremental Sync (historyId) → Parser (HTML/plaintext cleaning)
                              │
                              ▼
                  Rule-based pre-filter (sender/keyword)
                              │ (uncertain cases only)
                              ▼
                     Urgency Classifier ──▶ Task Extractor
                    (urgent/routine/notification/newsletter)
                              │
              ┌───────────────┴────────────────┐
              ▼                                 ▼
      newsletter/notification              urgent/routine
      → auto-archived                            │
                                                  ▼
                                    Retriever (Chroma: similar sent mail)
                                                  │
                                                  ▼
                                   Draft Generator (RAG, sender-aware)
                                                  │
                                                  ▼
                                        Confidence Scorer
                                          │            │
                                    high conf.     low conf.
                                    draft_ready    needs_review
                                                  │
                                                  ▼
                                   Dashboard: triage view + Gmail compose link
```

## Stack

- **Backend:** FastAPI, SQLAlchemy, SQLite
- **LLM:** Groq (Llama 3.1 8B) — classification, task extraction, draft generation
- **Retrieval:** ChromaDB + sentence-transformers (local embeddings, no API cost)
- **Auth:** Google OAuth 2.0 (Gmail readonly scope)
- **Frontend:** Streamlit — bulk triage dashboard
- **Testing:** pytest
- **Containerization:** Docker

## Key engineering decisions

- **Bulk processing, not one-off drafting.** The dashboard doesn't ask you to open each email and click a button — it processes the whole inbox in one pass and presents a pre-computed triage view. This is the core differentiator from just pasting an email into a chatbot.
- **Eval-driven development:** every major component was tested against real labeled data before being trusted. See `eval/results.md` for the full debugging log, including a 50%→75% accuracy improvement from prompt iteration and a confidence-scoring bug found by inspecting raw output instead of assuming library defaults.
- **Read-only by design:** only `gmail.readonly` scope is requested. Nothing in this system sends email — drafts open in Gmail via a compose link for the user to review and send themselves.
- **4-category taxonomy:** added a `notification` category after discovering automated reminders were triggering unnecessary drafts under a 3-category system.
- **Rate-limit-aware architecture:** a cheap rule-based pre-filter (sender patterns, keyword matching) catches obvious newsletters/notifications before they reach the LLM, reducing API calls on Groq's rate-limited free tier.
- **Incremental sync:** uses Gmail's `historyId` to fetch only what changed since last sync, instead of refetching the inbox every time.

## Setup

```bash
git clone https://github.com/Khushi-Tyagi9/mailwise.git
cd mailwise
python -m venv venv
venv\Scripts\Activate   # Windows
pip install -r requirements.txt
```

Create `.env`:
```
GROQ_API_KEY=your_key_here
```

Add Google OAuth `credentials.json` to `credentials/` (see Google Cloud Console → Gmail API, readonly scope only).

**Run the backend:**
```bash
uvicorn app.main:app --reload
```
API docs at `http://127.0.0.1:8000/docs`

**Run the dashboard** (separate terminal):
```bash
python -m streamlit run frontend/dashboard.py
```
Click "Sync new emails" then "Process all pending" — lands on a triage view with urgent/routine/newsletter/notification counts and ready-to-send drafts, each with a one-click "Open in Gmail" link.

## Results

See [`eval/results.md`](eval/results.md) for full evaluation methodology, bugs found, and metrics.

**Highlights:**
- Urgency classification: 75% accuracy on 36 hand-labeled real emails (up from 50% baseline)
- Task extraction: correctly distinguishes genuine obligations from marketing CTAs
- Retrieval: verified semantic matching (not keyword matching) on real sent-mail corpus
- Found and fixed a real-world data bug: some senders mislabel HTML content as `text/plain`, which was corrupting classification until caught via eval testing

## Future work

- **Chrome extension**: read Gmail's DOM directly via content script instead of the Gmail API — avoids Google's OAuth verification requirement entirely, making the tool installable and usable by anyone with their real inbox.
- Multi-agent decomposition (separate urgency/calendar/reply agents)
- MCP-based Gmail integration
- Public multi-user deployment (pending Google OAuth verification)
- Gmail push notifications (Pub/Sub) for real-time processing instead of manual sync
- Re-label eval set to reflect 4-category taxonomy