import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from groq import Groq
from app.config import require_api_key, ConfigError


def main():
    try:
        api_key = require_api_key()
    except ConfigError as exc:
        print(exc)
        sys.exit(1)

    client = Groq(api_key=api_key)
    models = sorted(m.id for m in client.models.list().data)
    print(f"{len(models)} models available to this key:")
    for model_id in models:
        print(f"  {model_id}")
    print("\nPut your choice in .env as GROQ_MODEL=<model id>")


if __name__ == "__main__":
    main()
