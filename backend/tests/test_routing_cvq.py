"""Parity with tests/web/router.test.mjs: same catalog, same expectations."""

from app import catalog, config, routing

NOW = 1_790_000_000.0


def hire(*ids):
    out = []
    for pid in ids:
        p = catalog.provider(config.load().catalog_dir, pid)
        q = p["quota"]
        out.append(routing.Employee(
            id=pid, name=p["name"], skills=p["skills"], cost_tier=p["cost_tier"], speed=p["speed"], reliability=p["reliability"],
            quota_unit=q["unit"], quota_limit=q["limit"], reserve=q["default_reserve"], context_length=p["context_length"], modalities=p["modalities"],
        ))
    return out


def pick(task, team, **kw):
    d = routing.route(task, team, now=NOW, **kw)
    return d.ordered[0].employee.id if d.ordered else None


def T(kind, difficulty, critical=False):
    return routing.Task(kind=kind, difficulty=difficulty, critical=critical)


def test_simple_work_goes_local():
    team = hire("local-llamacpp", "cerebras", "gemini")
    assert pick(T("coding", 1), team) == "local-llamacpp"
    assert pick(T("qa", 1), team) == "local-llamacpp"


def test_medium_work_prefers_abundant_quota():
    team = hire("local-llamacpp", "cerebras", "gemini", "groq")
    assert pick(T("coding", 2), team) == "cerebras"
    assert pick(T("planning", 2), team) == "cerebras"


def test_hard_work_cheapest_that_meets_bar():
    local, cerebras, gemini, claude = hire("local-llamacpp", "cerebras", "gemini", "anthropic")
    assert pick(T("planning", 3), [local, cerebras, gemini, claude]) == "gemini"
    gemini.quota_used = gemini.quota_limit
    assert pick(T("planning", 3, True), [local, gemini, claude]) == "anthropic"


def test_reserve_kept_for_critical():
    (gemini,) = hire("gemini")
    gemini.quota_used = gemini.quota_limit * 0.85
    d = routing.route(T("vision", 2), [gemini], now=NOW)
    assert d.ordered == [] and d.rejected[0][1] == "reserve_protected"
    assert pick(T("vision", 2, True), [gemini]) == "gemini"


def test_design_skips_local():
    assert pick(T("design", 1), hire("local-llamacpp", "cloudflare", "gemini")) == "cloudflare"


def test_cooldown_and_degrade():
    team = hire("local-llamacpp", "cerebras")
    team[1].cooldown_until = NOW + 5
    d = routing.route(T("coding", 3), team, now=NOW)
    assert d.degraded and d.ordered[0].employee.id == "local-llamacpp" and d.rejected[0][1] == "cooldown"


def test_usage_units():
    groq, cerebras, cf = hire("groq", "cerebras", "cloudflare")
    t = T("coding", 2)
    assert routing.usage_for(groq, t) == 1
    assert routing.usage_for(cerebras, t) == 6000
    assert routing.usage_for(cf, t) == 240
