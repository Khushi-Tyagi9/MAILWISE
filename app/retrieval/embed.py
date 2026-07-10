from sentence_transformers import SentenceTransformer

_model = None

def get_embedding_model():
    global _model
    if _model is None:
        _model = SentenceTransformer('all-MiniLM-L6-v2')
    return _model

def embed_text(text):
    model = get_embedding_model()
    return model.encode(text).tolist()


if __name__ == "__main__":
    vec = embed_text("Can we reschedule the call?")
    print(f"Embedding length: {len(vec)}")
    print(f"First 5 values: {vec[:5]}")