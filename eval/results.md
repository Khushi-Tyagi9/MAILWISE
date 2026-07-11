# Classifier Evaluation Results

**Dataset:** 36 hand-labeled real emails from personal Gmail inbox
**Model:** Llama 3.1 8B (via Groq)
**Task:** 3-way urgency classification (urgent / routine / newsletter)

## Results

| Version | Accuracy |
|---|---|
| Initial prompt (generic definitions + minimal examples) | 50.0% (18/36) |
| Improved prompt (explicit fake-personalization handling) | 75.0% (27/36) |

## Key finding

The largest error source in v1 was marketing emails using fake personalization 
(e.g. "Khushi, apply now to...") being misclassified as `routine` instead of 
`newsletter`. Adding explicit few-shot examples covering this pattern improved 
accuracy by 25 percentage points without any code changes - purely prompt engineering.

## Known limitation

Remaining errors cluster around automated-but-personally-relevant notifications 
(e.g. LinkedIn "X accepted your invitation") which sit ambiguously between 
`routine` and `newsletter`. A future iteration could split these into a 
dedicated `notification` category.

## Task extraction

**Initial version:** extracted marketing calls-to-action as if they were genuine 
obligations (e.g. "Click to try LinkedIn Premium", "apply before they close!" 
repeated for every internship in a digest email).

**Fix:** added explicit negative examples to the prompt distinguishing genuine 
personal obligations from promotional CTAs.

**Result:** across 40 real inbox emails, the improved prompt correctly extracted 
only 1 genuine task (a time-limited verification code) and returned an empty 
list for all 39 marketing/notification emails - matching manual inspection.
## Retrieval and confidence scoring

**Bug found:** initial confidence scoring formula assumed Chroma's cosine distance 
ranges 0-1, producing artificially low confidence scores (e.g. 0.29 for a genuinely 
strong match). Inspecting raw distance output revealed the true range is 0-2 
(a mathematical consequence of cosine distance = 1 - cosine similarity, where 
similarity itself ranges -1 to 1). Recalibrated the formula accordingly, 
correcting the same match's score from 0.29 to 0.65.

## Draft generation

**Working:** RAG-grounded draft generation retrieves similar past sent emails 
and produces drafts matching the user's real writing style and tone.

**Bug found and fixed:** initial version sometimes drafted replies from the 
wrong party's perspective (e.g. writing as a company instead of as the account 
owner) when the incoming email's topic closely matched retrieved examples. 
Fixed by explicitly stating the account owner's role and adding sender context 
to the prompt.

## Taxonomy update: added 'notification' category

Found automated notifications (e.g. "your submission is pending") were being 
misrouted into `routine`, triggering unnecessary draft generation. Added a 4th 
category, `notification`, and updated the orchestrator to skip drafting for it, 
same as newsletters. (Note: original 36-email eval set predates this change and 
would need relabeling to reflect the new category - noted as future work.)

## Containerization

Dockerfile builds successfully - base image, dependencies, app code, exposed 
port 8000, uvicorn entrypoint.

## Running the UI

With the backend running (`uvicorn app.main:app --reload`), in a separate terminal:
```bash
streamlit run frontend/dashboard.py
```
Opens a browser UI to sync emails, classify them, and generate drafts — no manual API calls needed.