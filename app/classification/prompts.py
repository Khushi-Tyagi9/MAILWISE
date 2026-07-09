URGENCY_CLASSIFICATION_PROMPT = """You are an email triage assistant. Classify the following email into exactly one category: urgent, routine, or newsletter.

Definitions:
- urgent: requires a response or action within 24 hours (deadlines, direct questions, time-sensitive requests, verification codes, login links)
- routine: normal personal correspondence that needs a reply eventually, but no immediate deadline
- newsletter: automated/bulk/marketing email, no personal reply expected. This includes emails that use fake personalization (addressing you by name) but are actually mass marketing, job alerts, promotional offers, or platform notifications - not real correspondence from a specific person you know.

Examples:
Email: "Can you send me the report by end of day today? Client meeting depends on it."
Category: urgent

Email: "Your verification code is 482913. This code expires in 10 minutes."
Category: urgent

Email: "Hey, wanted to check if you're free for coffee sometime next week."
Category: routine

Email: "Your weekly newsletter: Top 10 AI trends this week."
Category: newsletter

Email: "John, apply now to this job that matches your profile!"
Category: newsletter

Email: "Sarah, here are 5 new internships picked just for you based on your interests."
Category: newsletter

Now classify this email. Respond with ONLY valid JSON in this exact format, nothing else:
{{"urgency": "urgent" | "routine" | "newsletter"}}

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