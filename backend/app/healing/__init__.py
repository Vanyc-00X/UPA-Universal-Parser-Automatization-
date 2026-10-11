"""Надёжность и self-healing сценариев (Этап 6)."""

from app.healing.journal import JournalStep, RunJournal
from app.healing.retry import RetryDecision, classify_fetch_error, with_retries
from app.healing.robots import RobotsCheck, check_robots
from app.healing.service import (
    HealProposal,
    apply_heal_proposal,
    build_heal_proposal,
    proposal_from_run,
)

__all__ = [
    "HealProposal",
    "JournalStep",
    "RetryDecision",
    "RobotsCheck",
    "RunJournal",
    "apply_heal_proposal",
    "build_heal_proposal",
    "check_robots",
    "classify_fetch_error",
    "proposal_from_run",
    "with_retries",
]
