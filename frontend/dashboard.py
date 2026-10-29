import html

import requests
import streamlit as st

from frontend.utils import (
    AVATAR_COLORS,
    DEFAULT_AVATAR_COLOR,
    FOLDERS,
    LABEL_COLORS,
    LABEL_FILTERS,
    LINKS_SHOWN,
    avatar_initial,
    filter_emails,
    full_date,
    gmail_compose_link,
    is_safe_url,
    label_counts,
    label_key,
    link_button_label,
    parse_links,
    parse_tasks,
    split_links,
    sender_name,
    short_date,
    snippet,
    split_quoted,
)

API_URL = "http://127.0.0.1:8000"
COMPOSE_URL_LIMIT = 1800
TOKEN_HINT = (
    "If your Gmail login expired, delete `credentials\\token.pickle` "
    "and run `python -m app.auth.gmail_auth`."
)

st.set_page_config(page_title="Mailwise", page_icon="📬", layout="wide")

# Static CSS only. No email content is ever rendered as HTML.
st.markdown("""
<style>
#MainMenu, footer, [data-testid="stToolbar"] { visibility: hidden; }
.block-container { padding-top: 2rem; }
.mw-avatar {
    width: 38px; height: 38px; border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-weight: 600; color: white;
}
div[class*="st-key-row_"] [data-testid="stText"] {
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
div[class*="st-key-sender_"] [data-testid="stText"] { font-weight: 600; }
div[class*="st-key-snip_"] [data-testid="stText"] { opacity: 0.65; font-size: 0.85em; }
div[class*="st-key-subject_"] [data-testid="stText"] { font-size: 1.4em; font-weight: 600; }
div[class*="st-key-quotedbox_"] [data-testid="stText"] { opacity: 0.65; }
</style>
""", unsafe_allow_html=True)


# ---------- API ----------

@st.cache_data(ttl=30, show_spinner=False)
def fetch_emails(folder):
    r = requests.get(f"{API_URL}/emails", params={"folder": folder}, timeout=10)
    r.raise_for_status()
    return r.json()


def response_detail(resp):
    try:
        data = resp.json()
        detail = data.get("detail") if isinstance(data, dict) else None
    except ValueError:
        detail = None
    return str(detail or resp.text[:300] or resp.reason)


def api_error_message(exc):
    if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
        return f"Can't reach the Mailwise API at {API_URL}. Is the backend running?"
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        return f"API error {exc.response.status_code}: {response_detail(exc.response)}"
    return f"Request to {API_URL} failed: {exc}"


def load(folder):
    try:
        return fetch_emails(folder), None
    except requests.RequestException as exc:
        return [], api_error_message(exc)


def run_sync():
    try:
        with st.spinner("Syncing..."):
            r = requests.post(f"{API_URL}/sync", timeout=120)
            r.raise_for_status()
    except requests.HTTPError as exc:
        st.error(f"Sync failed: {response_detail(exc.response)}\n\n{TOKEN_HINT}")
        return
    except requests.RequestException as exc:
        st.error(api_error_message(exc))
        return
    fetch_emails.clear()
    st.session_state["flash"] = f"Synced {r.json().get('synced', 0)} new emails"
    st.rerun()


def run_process():
    with st.spinner("This can take a few minutes"):
        from app.agent.batch_processor import process_all_pending
        process_all_pending()
    fetch_emails.clear()
    st.session_state["flash"] = "Processing finished"
    st.rerun()


# ---------- list pane ----------

def select_email(folder, email_id):
    st.session_state[f"selected_{folder}"] = email_id


def display_name(email, folder):
    return sender_name(email.get("sender")) if folder == "inbox" else "Me"


def show_label(label):
    if label in LABEL_COLORS:
        st.badge(label.capitalize(), color=LABEL_COLORS[label])
    elif label:
        st.badge("Other", color="gray")


def avatar(name, label):
    color = AVATAR_COLORS.get(label, DEFAULT_AVATAR_COLOR)
    st.markdown(
        f'<div class="mw-avatar" style="background:{html.escape(color)}">'
        f'{html.escape(avatar_initial(name))}</div>',
        unsafe_allow_html=True,
    )


def highlight_row(folder, email_id):
    # Selector built only from a known folder and an integer id
    if folder not in FOLDERS:
        return
    try:
        eid = int(email_id)
    except (TypeError, ValueError):
        return
    st.markdown(
        f"<style>.st-key-row_{folder}_{eid} {{ border-color: #6366f1 !important; "
        f"background: rgba(99, 102, 241, 0.12); box-shadow: inset 3px 0 0 #6366f1; }}</style>",
        unsafe_allow_html=True,
    )


def render_row(folder, email, is_selected):
    eid = email["id"]
    name = display_name(email, folder)
    label = label_key(email, folder)
    with st.container(border=True, key=f"row_{folder}_{eid}"):
        a, b, c = st.columns([1, 7, 3], vertical_alignment="center")
        with a:
            avatar(name, label)
        with b:
            with st.container(key=f"sender_{folder}_{eid}"):
                st.text(name)
            st.text(email.get("subject") or "(no subject)")
            snip = snippet(email.get("body"))
            if snip:
                with st.container(key=f"snip_{folder}_{eid}"):
                    st.text(snip)
        with c:
            date = short_date(email.get("received_at"))
            if date:
                st.text(date)
            show_label(label)
            st.button(
                "Open",
                key=f"open_{folder}_{eid}",
                on_click=select_email,
                args=(folder, eid),
                type="primary" if is_selected else "secondary",
                width="stretch",
            )


def render_list(folder, emails):
    if folder == "inbox":
        s, f = st.columns([3, 2])
        query = s.text_input("Search", key=f"search_{folder}", placeholder="Search subject or sender",
                             label_visibility="collapsed")
        label = f.selectbox("Label", LABEL_FILTERS, key=f"label_{folder}", label_visibility="collapsed")
    else:
        query = st.text_input("Search", key=f"search_{folder}", placeholder="Search subject",
                              label_visibility="collapsed")
        label = "All"

    filtered = filter_emails(emails, query, label)
    ids = [e["id"] for e in filtered]
    sel_key = f"selected_{folder}"
    if st.session_state.get(sel_key) not in ids:
        st.session_state[sel_key] = ids[0] if ids else None
    selected_id = st.session_state[sel_key]

    st.caption(f"{len(filtered)} of {len(emails)} emails")
    with st.container(height=600, border=False):
        if not filtered:
            st.caption("No emails match.")
        for email in filtered:
            render_row(folder, email, email["id"] == selected_id)
    if selected_id is not None:
        highlight_row(folder, selected_id)

    return next((e for e in filtered if e["id"] == selected_id), None)


# ---------- reading pane ----------

def link_button(folder, eid, index, link):
    # parse_links already filtered these; checked again right before rendering
    if not is_safe_url(link["url"]):
        return
    label, mismatch = link_button_label(link)
    st.link_button(label, link["url"], key=f"link_{folder}_{eid}_{index}")
    if mismatch:
        st.caption("label does not match destination")


def render_links(folder, eid, links):
    if not links:
        return
    regular, unsubscribe = split_links(links)
    if regular:
        st.subheader("Links")
        for index, link in regular[:LINKS_SHOWN]:
            link_button(folder, eid, index, link)
        rest = regular[LINKS_SHOWN:]
        if rest and st.toggle(f"Show all {len(regular)} links", key=f"alllinks_{folder}_{eid}"):
            for index, link in rest:
                link_button(folder, eid, index, link)
    if unsubscribe:
        with st.expander("Unsubscribe and preferences", expanded=False, key=f"unsub_{folder}_{eid}"):
            st.caption("Opening an unsubscribe link may confirm to the sender that your address is active.")
            for index, link in unsubscribe:
                link_button(folder, eid, index, link)

def render_detail(folder, email):
    if email is None:
        st.info("Select an email to read it.")
        return

    eid = email["id"]
    label = label_key(email, folder)
    with st.container(border=True, key=f"detail_{folder}_{eid}"):
        with st.container(key=f"subject_{folder}_{eid}"):
            st.text(email.get("subject") or "(no subject)")
        meta, badge = st.columns([5, 1], vertical_alignment="center")
        with meta:
            st.text(email.get("sender") or display_name(email, folder))
            st.text(full_date(email.get("received_at")))
        with badge:
            show_label(label)
        st.divider()

        main, quoted = split_quoted(email.get("body"))
        st.text(main.strip() or "(empty body)")
        if quoted and st.toggle("Show quoted text", key=f"quoted_{folder}_{eid}"):
            with st.container(key=f"quotedbox_{folder}_{eid}"):
                st.text(quoted)

    render_links(folder, eid, parse_links(email.get("links")))

    if folder != "inbox":
        return

    tasks = parse_tasks(email.get("tasks"))
    if tasks:
        st.subheader("Tasks")
        for task in tasks:
            st.text(f"• {task}")

    if email.get("draft"):
        st.subheader("Draft reply")
        confidence = email.get("confidence") or "n/a"
        status = (email.get("draft_status") or "n/a").replace("_", " ")
        st.caption(f"Confidence: {confidence} · Status: {status}")
        draft_text = st.text_area("Draft", value=email["draft"], height=220,
                                  key=f"draft_{folder}_{eid}", label_visibility="collapsed")
        link = gmail_compose_link(email.get("sender"), email.get("subject") or "", draft_text)
        st.link_button("✉️ Open in Gmail compose", link, key=f"compose_{folder}_{eid}")
        if len(link) > COMPOSE_URL_LIMIT:
            st.caption("This draft is long, so Gmail may cut it off in the compose window. "
                       "The draft box above has the full text.")
    elif email.get("urgency") in ("newsletter", "notification"):
        st.info("No reply needed.")
    elif email.get("urgency") is None:
        st.info("Not processed yet. Use Process all pending to classify it and draft a reply.")
    else:
        st.info("No draft for this email.")


# ---------- page ----------

title_col, sync_col, process_col, chips_col = st.columns([3, 1.2, 2, 4], vertical_alignment="center")
title_col.title("📬 Mailwise")
sync_clicked = sync_col.button("🔄 Sync", key="sync", width="stretch")
process_clicked = process_col.button("⚙️ Process all pending", key="process", width="stretch")

if sync_clicked:
    run_sync()
if process_clicked:
    run_process()

if "flash" in st.session_state:
    st.success(st.session_state.pop("flash"))

inbox, inbox_error = load("inbox")
if inbox_error:
    st.error(inbox_error)
    st.stop()

counts = label_counts(inbox)
with chips_col:
    with st.container(horizontal=True):
        for name in ("urgent", "routine", "newsletter", "notification"):
            st.badge(f"{name.capitalize()} {counts[name]}", color=LABEL_COLORS[name])

left, right = st.columns([2, 3], gap="medium")
with left:
    inbox_tab, sent_tab = st.tabs(["Inbox", "Sent"], key="folder_tab", on_change="rerun")
    folder = "sent" if sent_tab.open else "inbox"
    with (sent_tab if folder == "sent" else inbox_tab):
        if folder == "inbox":
            emails, error = inbox, None
        else:
            emails, error = load("sent")
        if error:
            st.error(error)
        selected = render_list(folder, emails)
with right:
    render_detail(folder, selected)
