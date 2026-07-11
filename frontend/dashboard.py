import streamlit as st
import requests
import re
import urllib.parse

API_URL = "http://127.0.0.1:8000"

st.set_page_config(page_title="Mailwise", page_icon="📬", layout="wide")
st.markdown("""
<style>
.stExpander {
    border: 1px solid #2a2d3a;
    border-radius: 10px;
    margin-bottom: 8px;
}
div[data-testid="stMetricValue"] {
    font-size: 24px;
}
</style>
""", unsafe_allow_html=True)
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

c1, c2, c3, c4 = st.columns(4)
c1.metric("🔴 Urgent", len(urgent))
c2.metric("🔵 Routine", len(routine))
c3.metric("⚪ Archived", len(archived))
c4.metric("⚙️ Pending", len(unprocessed))

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

def avatar(name):
    initial = (name or "?")[0].upper()
    return initial

def render_section(title, color, emails, show_draft=True):
    st.markdown(f"<h3 style='margin-top:24px'>{title}</h3>", unsafe_allow_html=True)
    if not emails:
        st.caption("Nothing here.")
        return
    for email in emails:
        sender_name = (email.get('sender') or "Unknown").split('<')[0].strip()
        st.markdown(f"""
        <div style="display:flex;align-items:center;gap:14px;padding:12px 16px;
                    border:1px solid #2a2d3a;border-radius:10px;margin-bottom:6px;
                    background:#161822;">
            <div style="width:38px;height:38px;border-radius:50%;background:{color};
                        display:flex;align-items:center;justify-content:center;
                        font-weight:600;color:white;flex-shrink:0;">
                {avatar(sender_name)}
            </div>
            <div style="flex-grow:1;overflow:hidden;">
                <div style="font-weight:600;font-size:15px;">{sender_name}</div>
                <div style="color:#9ca3af;font-size:13px;">{email['subject']}</div>
            </div>
        </div>
        """, unsafe_allow_html=True)

        with st.expander("View details"):
            st.caption(f"From: {email.get('sender', 'unknown')}")
            st.text(strip_quoted(email.get('body'))[:400])
            if show_draft and email.get('draft'):
                st.write(f"**Confidence:** {email.get('confidence')} | **Status:** {email.get('draft_status')}")
                st.text_area("Draft", email['draft'], height=120, key=f"d_{email['id']}")
                link = gmail_compose_link(email.get('sender'), email['subject'], email['draft'])
                st.link_button("✉️ Open in Gmail to send", link)
            elif show_draft:
                st.info("No draft — no reply needed.")

render_section("🔴 Urgent", "#ef4444", urgent)
render_section("🔵 Routine", "#3b82f6", routine)
newsletters = [e for e in archived if e.get('urgency') == 'newsletter']
notifications = [e for e in archived if e.get('urgency') == 'notification']
render_section("🟡 Newsletters", "#eab308", newsletters, show_draft=False)
render_section("⚪ Notifications", "#6b7280", notifications, show_draft=False)
if unprocessed:
    render_section("⚙️ Not yet processed", "#f59e0b", unprocessed, show_draft=False)