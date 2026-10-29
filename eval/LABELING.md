# Labeling guide

Every email in the evaluation set gets exactly one of four labels. Follow these
definitions and edge rules so labels stay consistent across sessions.

## Labels

- **urgent** (`u`): needs the user's action within about a day, or is time-limited:
  verification codes and login links, a deadline due today or tomorrow, a person
  waiting on an answer, an interview or meeting that needs a response soon.
- **routine** (`r`): one-to-one correspondence from a real person, or a support or
  organizer address replying to the user; forwarded mail with a personal note;
  anything that needs a reply but is not time-critical.
- **notification** (`n`): automated mail about the user's own account or activity
  that needs no reply: order, ticket and booking confirmations, receipts, submission
  reminders, security alerts, LinkedIn invitations and "accepted your invitation",
  platform status updates.
- **newsletter** (`w`): bulk or promotional mail: marketing, digests, job-alert
  emails, course and hackathon promotions sent to many people, "last day" sales,
  even when addressed by name.

## Edge rules

- A bulk email with a deadline is still **newsletter**, except verification codes.
- A reply from a support address to the user's own message is **routine**.
- If torn between urgent and routine, ask whether a normal person would act today.
- If an email is truly unlabelable, skip it (`s`).

## Using the labeler

```
.\venv\Scripts\python.exe -m eval.relabel
```

- Keys: `u` urgent, `r` routine, `n` notification, `w` newsletter, `s` skip,
  `b` undo the last label or skip, `q` quit.
- Emails appear in a seeded random order, not by date. The stored urgency and any
  model prediction are never shown, so they cannot bias the label.
- Every keypress is saved to `eval/private/labeled_set_v2.jsonl` (skips go to
  `eval/private/skipped_v2.jsonl`). Quit at any time and run it again to resume.
- Everything under `eval/private/` contains real email text and is git-ignored.
  Never commit it.

## Sampling note

The set is the inbox in seeded random order, so labeling a prefix of it gives a
random sample. If extra emails are added on purpose to cover rare classes, the set
is **no longer a random sample**: class proportions, the majority baseline and
overall accuracy then describe the labeled set, not the real inbox. Note it in the
changelog when that happens.

## Changelog

- 2026-10-29: Labels were written under the rules above. If a rule changes after
  labeling starts, record the change and date here and re-check the affected labels.
