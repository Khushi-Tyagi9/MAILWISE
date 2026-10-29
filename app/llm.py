import random
import time

import groq
from groq import Groq

from app.config import load_config

config = load_config()

# The SDK's own retries are turned off so the backoff below is the only retry layer.
client = Groq(api_key=config.groq_api_key, max_retries=0)

MAX_ATTEMPTS = 5
BASE_DELAY = 1.0
MAX_DELAY = 30.0


class LLMError(RuntimeError):
    pass


def _sleep(seconds):
    time.sleep(seconds)


def _retry_after(exc):
    response = getattr(exc, "response", None)
    if response is None:
        return None
    try:
        return max(0.0, float(response.headers.get("retry-after")))
    except (TypeError, ValueError):
        return None


def _backoff(attempt, exc):
    delay = min(MAX_DELAY, BASE_DELAY * (2 ** attempt))
    delay = delay / 2 + random.uniform(0, delay / 2)
    hinted = _retry_after(exc)
    if hinted is not None:
        delay = max(delay, min(hinted, MAX_DELAY))
    return delay


def chat(prompt):
    last_error = None
    for attempt in range(MAX_ATTEMPTS):
        try:
            response = client.chat.completions.create(
                model=config.groq_model,
                messages=[{"role": "user", "content": prompt}],
            )
            return response.choices[0].message.content
        except groq.APIStatusError as exc:
            status = exc.status_code
            if status == 404:
                msg = (
                    f"Groq returned 404 for model {config.groq_model!r}. It may be retired or not "
                    "available to your key. Run `python scripts/list_models.py` and update GROQ_MODEL in .env."
                )
                print(msg)
                raise LLMError(msg) from exc
            if status != 429 and status < 500:
                raise LLMError(f"Groq request failed with status {status}: {exc}") from exc
            last_error = exc
        except groq.APIConnectionError as exc:
            last_error = exc

        if attempt < MAX_ATTEMPTS - 1:
            _sleep(_backoff(attempt, last_error))

    raise LLMError(f"Groq request failed after {MAX_ATTEMPTS} attempts: {last_error}") from last_error
