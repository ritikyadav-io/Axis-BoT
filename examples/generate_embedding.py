"""Optional embedding example. Does not run during browser navigation.

Usage:
  .\\.venv\\Scripts\\python.exe examples\\generate_embedding.py --dry-run
  .\\.venv\\Scripts\\python.exe examples\\generate_embedding.py --live
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import load_environment, openrouter_embedding_model, startup_summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true", help="Call OpenRouter embeddings API once")
    parser.add_argument("--dry-run", action="store_true", help="Print config only")
    args = parser.parse_args()
    load_environment()
    print("Embedding example (separate from Browser Use chat)")
    for line in startup_summary():
        print(line)
    print(f"Will embed with: {openrouter_embedding_model()}")
    if args.live:
        from llm.embeddings import embed_text

        vector = embed_text("junior data engineer resume matching")
        print(f"Embedding length: {len(vector)}")
        print(f"First 4 values: {vector[:4]}")
        return 0
    print("Dry run only. Pass --live to make one embedding API call.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
