import streamlit as st
import requests
import re
import urllib.parse

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Mailwise", page_icon="📬", layout="wide")
st.title("📬 Mailwise")
st.caption("AI-powered inbox triage")

col1, col2 = st.columns(2)
with col1:
    if st.button("🔄 Sync new emails"):
        try:
            with st.spinner("Syncing..."):
                r = requests.post(f"{API_URL}/sync")
                st.success(f"Synced {r.json()['synced']} emails")
        except Exception:
            st.error("Gmail session expired. Please reconnect your account.")
with col2:
    if st.button("⚙️ Process all pending"):
        with st.spinner("Classifying, retrieving, and drafting..."):
            from app.agent.batch_processor import process_all_pending
            process_all_pending()
        st.success("Done")
        st.rerun()

emails = requests.get(f"{API_URL}/emails?folder=inbox").json()

urgent = [e for e in emails if e.get('urgency') == 'urgent']
routine = [e for e in emails if e.get('urgency') == 'routine']
archived = [e for e in emails if e.get('urgency') in ('newsletter', 'notification')]
unprocessed = [e for e in emails if e.get('urgency') is None]

st.markdown(f"### Summary: **{len(urgent)}** urgent · **{len(routine)}** routine · **{len(archived)}** auto-archived · **{len(unprocessed)}** not yet processed")

def strip_quoted(text):
    for marker in [r'\nOn .+ wrote:', r'\n>']:
        m = re.search(marker, text or "")
        if m:
            return text[:m.start()]
    return text or ""

def gmail_compose_link(to, subject, body):
    to_clean = re.sub(r'^.*<(.+)>$', r'\1', to or "")
    params = {"view": "cm", "fs": "1", "to": to_clean, "su": f"Re: {subject}", "body": body or ""}
    return "https://mail.google.com/mail/?" + urllib.parse.urlencode(params)

def render_section(title, emails, show_draft=True):
    st.subheader(title)
    if not emails:
        st.caption("Nothing here.")
        return
    for email in emails:
        with st.expander(email['subject']):
            st.caption(f"From: {email.get('sender', 'unknown')}")
            st.text(strip_quoted(email.get('body'))[:400])
            if show_draft and email.get('draft'):
                st.write(f"**Confidence:** {email.get('confidence')}  |  **Status:** {email.get('draft_status')}")
                st.text_area("Draft", email['draft'], height=120, key=f"d_{email['id']}")
                link = gmail_compose_link(email.get('sender'), email['subject'], email['draft'])
                st.link_button("✉️ Open in Gmail to send", link)
            elif show_draft:
                st.info("No draft — processed but no reply needed, or not yet processed.")

render_section("🔴 Urgent", urgent)
render_section("🔵 Routine", routine)
render_section("⚪ Auto-archived (no action needed)", archived, show_draft=False)
if unprocessed:
    render_section("⚙️ Not yet processed", unprocessed, show_draft=False)