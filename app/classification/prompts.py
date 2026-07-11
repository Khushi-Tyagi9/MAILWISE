URGENCY_CLASSIFICATION_PROMPT = """You are an email triage assistant. Classify the following email into exactly one category: urgent, routine, notification, or newsletter.

Definitions:
- urgent: requires a response or action within 24 hours (deadlines, direct questions, time-sensitive requests, verification codes, login links)
- routine: normal personal correspondence from a real person that needs a reply eventually, but no immediate deadline
- notification: automated confirmation, reminder, or status update that requires no reply (e.g. "your submission is pending", "your order was received", "you shared data with X") - even if personally addressed
- newsletter: automated/bulk/marketing email, no personal reply expected. Includes fake personalization (addressing you by name) that is actually mass marketing, job alerts, or promotional offers.

Examples:
Email: "Can you send me the report by end of day today?"
Category: urgent

Email: "Your verification code is 482913. Expires in 10 minutes."
Category: urgent

Email: "Hey, wanted to check if you're free for coffee next week."
Category: routine

Email: "Reminder! Your submission is pending for Round 1. Complete it to be eligible."
Category: notification

Email: "You shared some Google Account data with Claude."
Category: notification

Email: "Your weekly newsletter: Top 10 AI trends this week."
Category: newsletter

Email: "John, apply now to this job that matches your profile!"
Category: newsletter

Now classify this email. Respond with ONLY valid JSON in this exact format, nothing else:
{{"urgency": "urgent" | "routine" | "notification" | "newsletter"}}

Email subject: {subject}
Email body: {body}
"""
TASK_EXTRACTION_PROMPT = """You are an assistant that extracts actionable tasks from emails.

Read the email below and identify genuine action items - things the recipient personally needs to do, like replying to a specific person, submitting a document by a deadline, or using a time-limited verification code.

Do NOT extract marketing calls-to-action as tasks. Ignore things like "click to try [product]", "apply now" links inside job/internship digests, "read this article", or any promotional prompt urging engagement with a product or platform. These are not real obligations, even though the email phrases them as actions.

If there are no genuine action items, return an empty list.

Respond with ONLY valid JSON in this exact format, nothing else:
{{"tasks": ["task description 1", "task description 2"]}}

If no tasks: {{"tasks": []}}

Email subject: {subject}
Email body: {body}
"""
DRAFT_REPLY_PROMPT = """You are helping the email account owner draft a reply to an email they RECEIVED.

Below are examples of emails this person has SENT in the past (their own writing style/voice - use these only to match tone, word choice, and sign-off style):

{examples}

Now draft a reply to this NEW incoming email, sent to the account owner by: {sender}

Important context: the account owner is a private individual, NOT a company or support team. They are always the one REPLYING as themselves, a normal person - never as a business, customer support agent, or company representative, regardless of what the incoming email is about.

Incoming email:
Subject: {subject}
Body: {body}

Respond with ONLY valid JSON in this exact format, nothing else:
{{"draft": "the drafted reply text here"}}
"""