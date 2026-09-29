from app.domain import (
    AIEmployee,
    CapabilityScores,
    RoutingPolicy,
    TaskCreate,
    TaskType,
)
from app.router import route_task


def employee(
    employee_id: int,
    name: str,
    *,
    coding: float,
    speed: float,
    reliability: float,
    quota_remaining: float | None,
    quota_limit: float | None,
):
    return AIEmployee(
        id=employee_id,
        name=name,
        provider="test",
        model=name.lower(),
        quota_unit="tokens",
        quota_remaining=quota_remaining,
        quota_limit=quota_limit,
        capabilities=CapabilityScores(
            coding=coding,
            speed=speed,
            reliability=reliability,
        ),
    )


def test_quality_policy_prefers_stronger_coder():
    employees = [
        employee(1, "Fast", coding=75, speed=100, reliability=90, quota_remaining=900, quota_limit=1000),
        employee(2, "Expert", coding=98, speed=70, reliability=95, quota_remaining=600, quota_limit=1000),
    ]

    decision = route_task(
        TaskCreate(task_type=TaskType.CODING, prompt="Implement parser", policy=RoutingPolicy.QUALITY),
        employees,
    )

    assert decision.selected.employee_name == "Expert"


def test_free_policy_prefers_employee_with_more_remaining_quota():
    employees = [
        employee(1, "Scarce", coding=95, speed=90, reliability=90, quota_remaining=50, quota_limit=1000),
        employee(2, "Plenty", coding=82, speed=80, reliability=85, quota_remaining=1000, quota_limit=1000),
    ]

    decision = route_task(
        TaskCreate(task_type=TaskType.CODING, prompt="Write utility", policy=RoutingPolicy.FREE),
        employees,
    )

    assert decision.selected.employee_name == "Plenty"


def test_speed_policy_prefers_faster_employee():
    employees = [
        employee(1, "Deep", coding=95, speed=45, reliability=90, quota_remaining=1000, quota_limit=1000),
        employee(2, "Quick", coding=80, speed=100, reliability=85, quota_remaining=1000, quota_limit=1000),
    ]

    decision = route_task(
        TaskCreate(task_type=TaskType.CODING, prompt="Small fix", policy=RoutingPolicy.SPEED),
        employees,
    )

    assert decision.selected.employee_name == "Quick"


def test_router_rejects_when_everyone_is_out_of_quota():
    employees = [
        employee(1, "Empty", coding=99, speed=99, reliability=99, quota_remaining=0, quota_limit=1000),
    ]

    try:
        route_task(
            TaskCreate(task_type=TaskType.CODING, prompt="Anything"),
            employees,
        )
    except ValueError as exc:
        assert "No eligible AI employees" in str(exc)
    else:
        raise AssertionError("Expected route_task to fail")
