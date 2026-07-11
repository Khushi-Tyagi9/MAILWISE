from app.agent.confidence import score_confidence, should_auto_save

def test_score_confidence_no_results():
    assert score_confidence({}) == 0.0

def test_should_auto_save_threshold():
    assert should_auto_save(0.6) is True
    assert should_auto_save(0.4) is False