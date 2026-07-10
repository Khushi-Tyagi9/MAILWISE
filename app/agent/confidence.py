def score_confidence(similar_results):
    if not similar_results or not similar_results.get('distances') or not similar_results['distances'][0]:
        return 0.0

    distances = similar_results['distances'][0]
    closest_distance = distances[0]

    confidence = max(0.0, 1.0 - (closest_distance / 2.0))
    return round(confidence, 2)


def should_auto_save(confidence, threshold=0.5):
    return confidence >= threshold


if __name__ == "__main__":
    from app.retrieval.vector_store import find_similar
    results = find_similar("Can you update me on my refund status?")
    print(f"Raw distances: {results['distances']}")
    conf = score_confidence(results)
    print(f"Confidence: {conf}")
    print(f"Auto-save: {should_auto_save(conf)}")