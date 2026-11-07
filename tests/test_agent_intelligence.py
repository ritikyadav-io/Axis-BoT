import unittest

from agent.nl import normalize_instruction
from agent.recovery import FailureTracker, action_fingerprint
from job_agent.discovery import dedupe_jobs, job_fingerprint
from job_agent.matching import role_title_score


class NaturalLanguageTests(unittest.TestCase):
    def test_open_google_lowercase(self) -> None:
        task = normalize_instruction("open google")
        self.assertEqual(task.kind, "open_site")
        self.assertTrue(task.simple)
        self.assertIn("google.com", task.expanded.lower())

    def test_youtube_typo(self) -> None:
        task = normalize_instruction("open yotube")
        self.assertEqual(task.kind, "open_site")
        self.assertIn("youtube.com", task.expanded.lower())

    def test_play_youtube(self) -> None:
        task = normalize_instruction("play youtube")
        self.assertIn("youtube.com", task.expanded.lower())

    def test_multi_step_job_search(self) -> None:
        task = normalize_instruction("search junior data engineer jobs in india and give me five results")
        self.assertEqual(task.kind, "job_search")
        self.assertFalse(task.simple)
        self.assertGreaterEqual(len(task.plan_steps), 3)

    def test_data_engineer_typo(self) -> None:
        task = normalize_instruction("find data enginer jobs")
        self.assertIn("engineer", task.cleaned.lower())
        self.assertEqual(task.kind, "job_search")

    def test_google_search_phrase(self) -> None:
        task = normalize_instruction("open google and search sql interview questions")
        self.assertEqual(task.kind, "google_search")
        self.assertIn("sql interview questions", task.expanded.lower())


class RecoveryTests(unittest.TestCase):
    def test_identical_failure_stops_on_second_try(self) -> None:
        tracker = FailureTracker(max_identical=2)
        first_stop, _, _ = tracker.record("click", "Element not found: Search")
        second_stop, _, message = tracker.record("click", "Element not found: Search")
        self.assertFalse(first_stop)
        self.assertTrue(second_stop)
        self.assertIn("stopped", message.lower())

    def test_different_errors_are_not_the_same_action(self) -> None:
        self.assertNotEqual(
            action_fingerprint("click", "element not found"),
            action_fingerprint("navigate", "timeout"),
        )

    def test_quota_stops_immediately(self) -> None:
        tracker = FailureTracker(max_identical=2)
        stop, kind, _ = tracker.record("llm", "RESOURCE_EXHAUSTED: daily quota")
        self.assertTrue(stop)
        self.assertEqual(kind, "quota")

    def test_credits_stop_immediately_not_as_rate_limit(self) -> None:
        tracker = FailureTracker(max_identical=2)
        stop, kind, message = tracker.record("llm", "Error code: 402 - Insufficient credits")
        self.assertTrue(stop)
        self.assertEqual(kind, "credits")
        self.assertNotEqual(kind, "rate_limit")
        self.assertIn("insufficient", message.lower())


class MatchingTests(unittest.TestCase):
    def test_software_developer_is_not_data_engineer(self) -> None:
        score = role_title_score("Software Developer", ["Junior Data Engineer"])
        self.assertLess(score, 40)

    def test_data_engineer_title_matches(self) -> None:
        score = role_title_score("Junior Data Engineer", ["Junior Data Engineer", "Data Analyst"])
        self.assertGreaterEqual(score, 90)

    def test_analyst_is_not_engineer(self) -> None:
        score = role_title_score("Data Analyst", ["Junior Data Engineer"])
        self.assertLess(score, 40)


class DedupeTests(unittest.TestCase):
    def test_duplicate_urls_are_removed(self) -> None:
        jobs = [
            {"title": "DE", "company": "A", "location": "India", "apply_url": "https://jobs.example.org/1"},
            {"title": "DE copy", "company": "A", "location": "India", "apply_url": "https://jobs.example.org/1"},
        ]
        for job in jobs:
            job["fingerprint"] = job_fingerprint(job)
        unique = dedupe_jobs(jobs)
        self.assertEqual(len(unique), 1)


if __name__ == "__main__":
    unittest.main()
