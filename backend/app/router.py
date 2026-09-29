from __future__ import annotations

from .domain import (
    AIEmployee,
    EmployeeStatus,
    RoutingCandidate,
    RoutingDecision,
    RoutingPolicy,
    TaskCreate,
)


CAPABILITY_FIELD = {
    "coding": "coding",
    "planning": "planning",
    "design": "design",
    "vision": "vision",
    "debugging": "debugging",
    "qa": "qa",
    "general": "reliability",
}


def _quota_ratio(employee: AIEmployee) -> float:
    if employee.quota_unit == "unlimited":
        return 1.0
    if employee.quota_remaining is None or employee.quota_limit is None:
        return 0.5
    if employee.quota_limit <= 0:
        return 0.0
    return max(0.0, min(1.0, employee.quota_remaining / employee.quota_limit))


def _weights(policy: RoutingPolicy) -> tuple[float, float, float, float]:
    if policy == RoutingPolicy.QUALITY:
        return (0.65, 0.10, 0.10, 0.15)
    if policy == RoutingPolicy.FREE:
        return (0.35, 0.45, 0.10, 0.10)
    if policy == RoutingPolicy.SPEED:
        return (0.35, 0.10, 0.45, 0.10)
    return (0.45, 0.25, 0.15, 0.15)


def route_task(task: TaskCreate, employees: list[AIEmployee]) -> RoutingDecision:
    eligible = [
        employee
        for employee in employees
        if employee.status in {EmployeeStatus.ONLINE, EmployeeStatus.BUSY}
        and (employee.quota_unit == "unlimited" or employee.quota_remaining is None or employee.quota_remaining > 0)
    ]

    if not eligible:
        raise ValueError("No eligible AI employees are available")

    capability_field = CAPABILITY_FIELD[task.task_type.value]
    capability_w, quota_w, speed_w, reliability_w = _weights(task.policy)

    candidates: list[RoutingCandidate] = []
    for employee in eligible:
        capability_score = float(getattr(employee.capabilities, capability_field))
        quota_ratio = _quota_ratio(employee)
        speed_score = float(employee.capabilities.speed)
        reliability_score = float(employee.capabilities.reliability)

        score = (
            capability_score * capability_w
            + quota_ratio * 100 * quota_w
            + speed_score * speed_w
            + reliability_score * reliability_w
        )

        candidates.append(
            RoutingCandidate(
                employee_id=employee.id,
                employee_name=employee.name,
                provider=employee.provider,
                model=employee.model,
                score=round(score, 2),
                capability_score=capability_score,
                quota_ratio=round(quota_ratio, 4),
                speed_score=speed_score,
                reliability_score=reliability_score,
            )
        )

    candidates.sort(key=lambda candidate: (-candidate.score, candidate.employee_id))

    return RoutingDecision(
        task_type=task.task_type,
        policy=task.policy,
        selected=candidates[0],
        candidates=candidates,
    )
