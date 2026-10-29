import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Config:
    groq_api_key: str
    groq_model: str


def require_api_key(env=None):
    env = os.environ if env is None else env
    key = (env.get("GROQ_API_KEY") or "").strip()
    if not key:
        raise ConfigError(
            "GROQ_API_KEY is not set. Add GROQ_API_KEY=<your key> to the .env file in the project root."
        )
    return key


def load_config(env=None):
    env = os.environ if env is None else env
    key = require_api_key(env)

    model = (env.get("GROQ_MODEL") or "").strip()
    if not model:
        raise ConfigError(
            "GROQ_MODEL is not set. Run `python scripts/list_models.py` to see the models your key "
            "can use, then add GROQ_MODEL=<model id> to the .env file in the project root."
        )
    if any(ch.isspace() for ch in model):
        raise ConfigError(f"GROQ_MODEL looks malformed (contains whitespace): {model!r}")

    return Config(groq_api_key=key, groq_model=model)
