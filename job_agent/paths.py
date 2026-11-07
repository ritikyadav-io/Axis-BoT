from pathlib import Path

PACKAGE_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = PACKAGE_DIR.parent
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
RESUMES_DIR = PROJECT_ROOT / "resumes"
MASTER_RESUMES_DIR = RESUMES_DIR / "master"
TAILORED_RESUMES_DIR = RESUMES_DIR / "tailored"
REPORTS_DIR = PROJECT_ROOT / "reports"
FIXTURES_DIR = PACKAGE_DIR / "fixtures"
PROFILE_PATH = CONFIG_DIR / "profile.json"
SCHEDULE_PATH = CONFIG_DIR / "schedule.json"
DB_PATH = DATA_DIR / "jobs.db"
PID_PATH = DATA_DIR / "scheduler.pid"
STOP_PATH = DATA_DIR / "scheduler.stop"


def ensure_runtime_dirs() -> None:
    for path in (CONFIG_DIR, DATA_DIR, RESUMES_DIR, MASTER_RESUMES_DIR, TAILORED_RESUMES_DIR, REPORTS_DIR):
        path.mkdir(parents=True, exist_ok=True)
