import pytest

from app.config import load_config, require_api_key, ConfigError


def test_valid_config():
    cfg = load_config({"GROQ_API_KEY": "k", "GROQ_MODEL": "some-model"})
    assert cfg.groq_api_key == "k"
    assert cfg.groq_model == "some-model"


def test_missing_api_key():
    with pytest.raises(ConfigError, match="GROQ_API_KEY"):
        load_config({"GROQ_MODEL": "some-model"})


def test_missing_model_mentions_list_models():
    with pytest.raises(ConfigError, match="list_models.py"):
        load_config({"GROQ_API_KEY": "k"})


@pytest.mark.parametrize("model", ["", "   ", "two words"])
def test_blank_or_malformed_model(model):
    with pytest.raises(ConfigError, match="GROQ_MODEL"):
        load_config({"GROQ_API_KEY": "k", "GROQ_MODEL": model})


def test_require_api_key_does_not_need_model():
    assert require_api_key({"GROQ_API_KEY": " k "}) == "k"
