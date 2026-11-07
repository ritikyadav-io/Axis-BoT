"""Compatibility entry point. Prefer: python -m streamlit run dashboard/app.py"""

from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).resolve().parents[1] / "dashboard" / "app.py"))
