import chromadb
from app.retrieval.embed import embed_text
from app.db.session import SessionLocal
from app.db.models import Email

_client = None
_collection = None

def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path="chroma_data")
        _collection = _client.get_or_create_collection(name="sent_emails")
    return _collection

def add_sent_email(email_id, subject, body):
    collection = get_collection()
    text = f"{subject}\n{body}"
    embedding = embed_text(text)

    collection.upsert(
        ids=[str(email_id)],
        embeddings=[embedding],
        documents=[text],
        metadatas=[{"subject": subject}]
    )

def find_similar(query_text, top_k=3):
    collection = get_collection()
    query_embedding = embed_text(query_text)

    results = collection.query(
        query_embeddings=[query_embedding],
        n_results=top_k
    )
    return results

def index_all_sent_emails():
    session = SessionLocal()
    try:
        sent_emails = session.query(Email).filter(Email.folder == "sent").all()
        print(f"Indexing {len(sent_emails)} sent emails into Chroma...")

        for email in sent_emails:
            if not email.body or not email.body.strip():
                continue  # skip empty bodies - nothing meaningful to embed
            add_sent_email(email.id, email.subject or "", email.body)

        print("Done indexing.")
    finally:
        session.close()


if __name__ == "__main__":
    index_all_sent_emails()

    results = find_similar("Can you tell me the status of my refund?")
    print(results['documents'])