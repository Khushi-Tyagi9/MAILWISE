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