"""Regenerate backend/.env.example from the FIELDS table in app/config.py.

    python scripts/gen_env_example.py          # write the file
    python scripts/gen_env_example.py --check  # exit 1 if the file is stale (used by the tests)
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import render_env_example  # noqa: E402

TARGET = ROOT / ".env.example"

if __name__ == "__main__":
    text = render_env_example()
    if "--check" in sys.argv:
        sys.exit(0 if TARGET.exists() and TARGET.read_text() == text else 1)
    TARGET.write_text(text)
    print(f"Wrote {TARGET} ({text.count(chr(10))} lines)")
