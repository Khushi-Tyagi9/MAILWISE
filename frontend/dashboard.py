import streamlit as st
import requests

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Mailwise", page_icon="📬", layout="wide")
st.title("📬 Mailwise")
st.caption("AI-powered inbox triage")

if st.button("🔄 Sync new emails", key="sync_btn"):
    try:
        with st.spinner("Syncing..."):
            r = requests.post(f"{API_URL}/sync")
            st.success(f"Synced {r.json()['synced']} emails")
    except Exception:
        st.error("Gmail session expired. Please reconnect your account.")

if st.button("🏷️ Classify all pending", key="classify_btn"):
    with st.spinner("Classifying..."):
        from app.classification.urgency_classifier import classify_all_pending
        from app.classification.task_extractor import extract_all_pending_tasks
        classify_all_pending()
        extract_all_pending_tasks()
    st.success("Classification done")
    st.rerun()

emails = requests.get(f"{API_URL}/emails").json()
emails = list(reversed(emails))

BADGE = {
    "urgent": "🔴 Urgent",
    "routine": "🔵 Routine",
    "notification": "⚪ Notification",
    "newsletter": "🟡 Newsletter",
    None: "⚙️ Not classified",
}

for email in emails:
    label = BADGE.get(email.get("urgency"), "⚙️ Not classified")
    title = f"{label} — {email['subject']}"

    with st.expander(title):
        st.caption(f"From: {email.get('sender', 'unknown')}")

        if st.button("Generate draft", key=f"btn_{email['id']}"):
            with st.spinner("Processing..."):
                draft_res = requests.get(f"{API_URL}/emails/{email['id']}/draft").json()

            st.write(f"**Status:** {draft_res['status']}")
            if draft_res['confidence'] is not None:
                st.progress(draft_res['confidence'])
                st.caption(f"Confidence: {draft_res['confidence']}")
            if draft_res['draft']:
                st.text_area("Draft reply", draft_res['draft'], height=150, key=f"draft_{email['id']}")
            else:
                st.info("No draft needed — auto-archived.")