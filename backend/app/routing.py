"""CHEAPEST_VIABLE_QUALITY router. Mirrors docs/js/router.js rule-for-rule.

1. Exclude AIs that are paused, unauthenticated, offline, cooling down, out of quota, or at their
   reserve line (reserve is kept for critical tasks), or that lack the needed capability.
2. Among AIs that meet the task's quality bar, prefer the cheapest cost tier.
3. Inside a tier, protect scarce quota from easy work (penalty shrinks as difficulty rises).
4. Below-quality AIs are appended as a last-resort tail so a line never stops.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

DEFAULT_ROUTING = {
    "required_quality": {"1": 55, "2": 72, "3": 85},
    "estimated_tokens": {"1": 2500, "2": 6000, "3": 12000},
    "scarce_request_limit": 500,
}
SCARCITY_WEIGHT = {1: 100, 2: 40, 3: 0}
POLICIES = ("cheapest_viable_quality", "quality", "speed", "free")


@dataclass
class Employee:
    id: str
    name: str
    skills: dict[str, float]
    cost_tier: int = 1
    speed: float = 50
    reliability: float = 50
    status: str = "online"
    quota_unit: str = "unknown"
    quota_limit: float | None = None
    quota_used: float = 0
    reserve: float = 0
    cooldown_until: float = 0
    context_length: int | None = None
    modalities: list[str] = field(default_factory=lambda: ["text"])

    @property
    def has_limit(self) -> bool:
        return self.quota_unit != "unlimited" and isinstance(self.quota_limit, (int, float)) and self.quota_limit > 0

    @property
    def remaining(self) -> float:
        return max(0.0, self.quota_limit - self.quota_used) if self.has_limit else math.inf

    @property
    def ratio(self) -> float:
        return self.remaining / self.quota_limit if self.has_limit else 1.0

    @property
    def at_reserve(self) -> bool:
        return self.has_limit and self.remaining <= self.quota_limit * (self.reserve or 0)

    @property
    def exhausted(self) -> bool:
        return self.has_limit and self.remaining <= 0


@dataclass
class Task:
    kind: str
    difficulty: int
    critical: bool = False
    context_needed: int | None = None


@dataclass
class Candidate:
    employee: Employee
    capability: float
    viable: bool
    scarcity: float


@dataclass
class Decision:
    ordered: list[Candidate]
    rejected: list[tuple[Employee, str]]
    degraded: bool
    required: float


def capability_for(e: Employee, kind: str) -> float:
    if kind in ("image", "audio"):
        return float(e.skills.get("design", 0)) if kind in e.modalities else 0.0
    return float(e.skills.get(kind, 0))


def scarcity(e: Employee, routing: dict = DEFAULT_ROUTING) -> float:
    if not e.has_limit:
        return 0.0
    small = e.quota_unit == "requests" and e.quota_limit <= routing["scarce_request_limit"]
    return (0.5 if small else 0.0) + (1 - e.ratio) * 0.5


def usage_for(e: Employee, task: Task, routing: dict = DEFAULT_ROUTING) -> float:
    tokens = routing["estimated_tokens"].get(str(task.difficulty), 5000)
    return {
        "tokens": tokens,
        "requests": 1,
        "neurons": math.ceil(tokens / 25),
        "credits": round(tokens / 10000, 2),
    }.get(e.quota_unit, 0)


def exclusion_reason(e: Employee, task: Task, now: float) -> str | None:
    if e.status in ("paused", "auth_required", "offline"):
        return e.status
    if e.cooldown_until and e.cooldown_until > now:
        return "cooldown"
    if e.exhausted:
        return "quota_exhausted"
    if e.at_reserve and not task.critical:
        return "reserve_protected"
    if task.context_needed and e.context_length and task.context_needed > e.context_length:
        return "context_too_small"
    if capability_for(e, task.kind) <= 0:
        return "missing_capability"
    return None


def _sort_key(policy: str, task: Task):
    weight = SCARCITY_WEIGHT.get(task.difficulty, 40)
    if policy == "quality":
        return lambda c: (-c.capability, -c.employee.reliability)
    if policy == "speed":
        return lambda c: (-c.employee.speed, -c.capability)
    if policy == "free":
        return lambda c: (c.employee.cost_tier, -c.employee.ratio, -c.capability)
    return lambda c: (c.employee.cost_tier, -(c.capability - c.scarcity * weight), -c.employee.reliability)


def route(task: Task, employees: list[Employee], *, policy: str = "cheapest_viable_quality", now: float | None = None, routing: dict = DEFAULT_ROUTING) -> Decision:
    now = datetime.now(timezone.utc).timestamp() if now is None else now
    required = float(routing["required_quality"].get(str(task.difficulty), 70))
    rejected: list[tuple[Employee, str]] = []
    eligible: list[Candidate] = []
    for e in employees:
        reason = exclusion_reason(e, task, now)
        if reason:
            rejected.append((e, reason))
            continue
        cap = capability_for(e, task.kind)
        eligible.append(Candidate(e, cap, cap >= required, scarcity(e, routing)))

    viable = [c for c in eligible if c.viable]
    if viable:
        below = sorted((c for c in eligible if not c.viable), key=lambda c: -c.capability)
        return Decision(sorted(viable, key=_sort_key(policy, task)) + below, rejected, False, required)
    return Decision(sorted(eligible, key=lambda c: -c.capability), rejected, bool(eligible), required)
