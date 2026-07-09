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