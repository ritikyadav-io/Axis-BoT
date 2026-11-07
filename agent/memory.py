"""Short-term memory for one browser task. Cleared when the task ends."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TaskMemory:
    objective: str
    kind: str = "browse"
    current_url: str = ""
    completed: list[str] = field(default_factory=list)
    failures: list[str] = field(default_factory=list)
    extracted: list[str] = field(default_factory=list)

    def remember_success(self, note: str) -> None:
        text = (note or "").strip()
        if text and text not in self.completed:
            self.completed.append(text[:240])

    def remember_failure(self, note: str) -> None:
        text = (note or "").strip()
        if text:
            self.failures.append(text[:240])

    def remember_extract(self, note: str) -> None:
        text = (note or "").strip()
        if text:
            self.extracted.append(text[:240])

    def briefing(self) -> str:
        lines = [f"Objective: {self.objective}"]
        if self.current_url:
            lines.append(f"Current page: {self.current_url}")
        if self.completed:
            lines.append("Already done: " + "; ".join(self.completed[-6:]))
        if self.failures:
            lines.append("Already failed (do not repeat identically): " + "; ".join(self.failures[-6:]))
        return "\n".join(lines)

    def clear(self) -> None:
        self.current_url = ""
        self.completed.clear()
        self.failures.clear()
        self.extracted.clear()
