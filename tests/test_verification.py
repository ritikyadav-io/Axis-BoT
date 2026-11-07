import py_compile
import unittest
from pathlib import Path

from job_agent.notifications import is_verified_listing as exported_helper
from job_agent.notifications import notify
from job_agent.tracker import STATUSES, upcoming_follow_ups
from job_agent.verification import is_verified_listing


ROOT = Path(__file__).resolve().parent.parent


class VerificationTests(unittest.TestCase):
    def test_sample_listing_is_not_verified(self) -> None:
        job = {
            "source": "sample",
            "title": "Junior Data Engineer",
            "apply_url": "https://example.com/jobs/1",
        }
        self.assertFalse(is_verified_listing(job))
        self.assertFalse(exported_helper(job))

    def test_public_listing_is_verified(self) -> None:
        job = {
            "source": "remotive",
            "title": "Junior Data Engineer",
            "apply_url": "https://remotive.com/remote-jobs/123",
        }
        self.assertTrue(is_verified_listing(job))

    def test_missing_url_is_not_verified(self) -> None:
        self.assertFalse(is_verified_listing({"source": "remotive", "title": "Engineer", "apply_url": ""}))

    def test_tracker_exports(self) -> None:
        from job_agent.database import JobStore

        self.assertIn("Discovered", STATUSES)
        self.assertTrue(callable(upcoming_follow_ups))
        self.assertTrue(callable(notify))
        self.assertTrue(hasattr(JobStore, "list_follow_ups"))
        self.assertEqual(upcoming_follow_ups.__name__, "upcoming_follow_ups")

    def test_dashboard_app_compiles(self) -> None:
        py_compile.compile(str(ROOT / "dashboard" / "app.py"), doraise=True)

    def test_alert_includes_apply_link(self) -> None:
        from job_agent.notifications import format_job_alert

        text = format_job_alert(
            {
                "title": "Junior Data Engineer",
                "company": "Acme",
                "location": "India",
                "match_percent": 88,
                "grade": "Excellent",
                "apply_url": "https://remotive.com/remote-jobs/123",
                "source": "remotive",
            }
        )
        self.assertIn("Apply here:", text)
        self.assertIn("https://remotive.com/remote-jobs/123", text)
        self.assertIn("Junior Data Engineer", text)


if __name__ == "__main__":
    unittest.main()
