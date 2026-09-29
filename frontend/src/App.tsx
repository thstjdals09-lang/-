import { FormEvent, useEffect, useMemo, useState } from "react";

type CapabilityScores = {
  coding: number;
  planning: number;
  design: number;
  vision: number;
  debugging: number;
  qa: number;
  speed: number;
  reliability: number;
};

type Employee = {
  id: number;
  name: string;
  provider: string;
  model: string;
  status: string;
  quota_unit: string;
  quota_remaining: number | null;
  quota_limit: number | null;
  capabilities: CapabilityScores;
};

type RoutingDecision = {
  task_type: string;
  policy: string;
  selected: {
    employee_name: string;
    provider: string;
    model: string;
    score: number;
  };
};

const API = "http://127.0.0.1:8000";

const defaults: CapabilityScores = {
  coding: 70,
  planning: 70,
  design: 50,
  vision: 0,
  debugging: 70,
  qa: 70,
  speed: 70,
  reliability: 80,
};

export default function App() {
  const [tab, setTab] = useState("dashboard");
  const [employees, setEmployees] = useState<Employee[]>([]);
  const [logs, setLogs] = useState<any[]>([]);
  const [taskPrompt, setTaskPrompt] = useState("");
  const [taskType, setTaskType] = useState("coding");
  const [policy, setPolicy] = useState("balanced");
  const [decision, setDecision] = useState<RoutingDecision | null>(null);
  const [message, setMessage] = useState("");

  const [employeeForm, setEmployeeForm] = useState({
    name: "",
    provider: "",
    model: "",
    api_key_env: "",
    quota_unit: "unknown",
    quota_remaining: "",
    quota_limit: "",
  });

  async function refresh() {
    try {
      const [employeeResponse, logResponse] = await Promise.all([
        fetch(`${API}/employees`),
        fetch(`${API}/routing-logs`),
      ]);
      if (employeeResponse.ok) setEmployees(await employeeResponse.json());
      if (logResponse.ok) setLogs(await logResponse.json());
    } catch {
      setMessage("Backend가 실행 중이지 않습니다. FastAPI 서버를 먼저 실행하세요.");
    }
  }

  useEffect(() => {
    void refresh();
  }, []);

  const onlineCount = useMemo(
    () => employees.filter((employee) => employee.status === "online").length,
    [employees],
  );

  async function addEmployee(event: FormEvent) {
    event.preventDefault();
    setMessage("");

    const payload = {
      name: employeeForm.name,
      provider: employeeForm.provider,
      model: employeeForm.model,
      api_key_env: employeeForm.api_key_env || null,
      quota_unit: employeeForm.quota_unit,
      quota_remaining: employeeForm.quota_remaining ? Number(employeeForm.quota_remaining) : null,
      quota_limit: employeeForm.quota_limit ? Number(employeeForm.quota_limit) : null,
      capabilities: defaults,
    };

    const response = await fetch(`${API}/employees`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });

    if (!response.ok) {
      setMessage("AI 사원 등록에 실패했습니다.");
      return;
    }

    setEmployeeForm({
      name: "",
      provider: "",
      model: "",
      api_key_env: "",
      quota_unit: "unknown",
      quota_remaining: "",
      quota_limit: "",
    });
    setMessage("AI 사원을 등록했습니다.");
    await refresh();
  }

  async function routeTask(event: FormEvent) {
    event.preventDefault();
    setMessage("");

    const response = await fetch(`${API}/route`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        task_type: taskType,
        prompt: taskPrompt,
        policy,
      }),
    });

    if (!response.ok) {
      setDecision(null);
      setMessage("배정 가능한 AI 사원이 없습니다.");
      return;
    }

    setDecision(await response.json());
    setMessage("Router가 담당 AI를 자동 배정했습니다.");
    await refresh();
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-mark">AF</div>
          <div>
            <strong>AI Factory</strong>
            <span>CEO Console</span>
          </div>
        </div>

        <nav>
          {[
            ["dashboard", "대시보드"],
            ["projects", "프로젝트"],
            ["employees", "AI 사원"],
            ["tasks", "작업 배정"],
            ["logs", "작업 로그"],
            ["settings", "설정"],
          ].map(([id, label]) => (
            <button
              key={id}
              className={tab === id ? "nav-item active" : "nav-item"}
              onClick={() => setTab(id)}
            >
              {label}
            </button>
          ))}
        </nav>

        <div className="sidebar-footer">
          <span className="status-dot" />
          Factory Core
          <small>Local-first V0</small>
        </div>
      </aside>

      <main className="content">
        <header className="topbar">
          <div>
            <p className="eyebrow">AI SOFTWARE COMPANY</p>
            <h1>{tab === "dashboard" ? "대표 대시보드" : tab === "employees" ? "AI 사원 관리" : tab === "tasks" ? "작업 자동 배정" : "AI Factory"}</h1>
          </div>
          <button className="secondary" onClick={() => void refresh()}>새로고침</button>
        </header>

        {message && <div className="notice">{message}</div>}

        {tab === "dashboard" && (
          <>
            <section className="stats-grid">
              <article className="stat-card">
                <span>등록된 AI 사원</span>
                <strong>{employees.length}</strong>
                <small>{onlineCount}명 온라인</small>
              </article>
              <article className="stat-card">
                <span>라우팅 기록</span>
                <strong>{logs.length}</strong>
                <small>최근 100건 기준</small>
              </article>
              <article className="stat-card">
                <span>현재 정책</span>
                <strong>Auto</strong>
                <small>능력 + 쿼터 + 속도</small>
              </article>
              <article className="stat-card accent">
                <span>V0 단계</span>
                <strong>Build</strong>
                <small>사원관리 / Router</small>
              </article>
            </section>

            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">FACTORY STATUS</p>
                  <h2>현재 회사 상태</h2>
                </div>
                <span className="pill">V0</span>
              </div>
              <div className="progress-track"><div className="progress-fill" /></div>
              <div className="progress-copy">
                <strong>AI 사원 등록 → 자동 라우팅</strong>
                <span>다음: Provider 실제 API 실행</span>
              </div>
            </section>
          </>
        )}

        {tab === "employees" && (
          <div className="two-column">
            <section className="panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">EMPLOYEE REGISTRY</p>
                  <h2>등록된 AI 사원</h2>
                </div>
                <span className="pill">{employees.length}명</span>
              </div>
              <div className="employee-list">
                {employees.length === 0 && <div className="empty">아직 등록된 AI 사원이 없습니다.</div>}
                {employees.map((employee) => (
                  <article className="employee-card" key={employee.id}>
                    <div>
                      <strong>{employee.name}</strong>
                      <span>{employee.provider} · {employee.model}</span>
                    </div>
                    <div className="employee-score">
                      <span>CODING {Math.round(employee.capabilities.coding)}</span>
                      <span>SPEED {Math.round(employee.capabilities.speed)}</span>
                    </div>
                  </article>
                ))}
              </div>
            </section>

            <section className="panel">
              <p className="eyebrow">HIRE AI</p>
              <h2>AI 사원 추가</h2>
              <form className="form-stack" onSubmit={addEmployee}>
                <input placeholder="사원 이름 (예: Cerebras Coder)" value={employeeForm.name} onChange={(e) => setEmployeeForm({ ...employeeForm, name: e.target.value })} required />
                <input placeholder="Provider (예: cerebras)" value={employeeForm.provider} onChange={(e) => setEmployeeForm({ ...employeeForm, provider: e.target.value })} required />
                <input placeholder="Model ID" value={employeeForm.model} onChange={(e) => setEmployeeForm({ ...employeeForm, model: e.target.value })} required />
                <input placeholder="API Key 환경변수명 (선택)" value={employeeForm.api_key_env} onChange={(e) => setEmployeeForm({ ...employeeForm, api_key_env: e.target.value })} />
                <select value={employeeForm.quota_unit} onChange={(e) => setEmployeeForm({ ...employeeForm, quota_unit: e.target.value })}>
                  <option value="unknown">쿼터 알 수 없음</option>
                  <option value="tokens">Tokens</option>
                  <option value="requests">Requests</option>
                  <option value="neurons">Neurons</option>
                  <option value="credits">Credits</option>
                  <option value="unlimited">Unlimited / Local</option>
                </select>
                <div className="form-row">
                  <input type="number" min="0" placeholder="남은 무료량" value={employeeForm.quota_remaining} onChange={(e) => setEmployeeForm({ ...employeeForm, quota_remaining: e.target.value })} />
                  <input type="number" min="0" placeholder="전체 무료량" value={employeeForm.quota_limit} onChange={(e) => setEmployeeForm({ ...employeeForm, quota_limit: e.target.value })} />
                </div>
                <button className="primary" type="submit">+ AI 사원 채용</button>
              </form>
            </section>
          </div>
        )}

        {tab === "tasks" && (
          <div className="two-column">
            <section className="panel">
              <p className="eyebrow">AUTO ROUTER</p>
              <h2>작업 요청</h2>
              <form className="form-stack" onSubmit={routeTask}>
                <textarea rows={8} placeholder="예: 로그인 화면에서 발생하는 상태관리 버그를 수정해줘" value={taskPrompt} onChange={(e) => setTaskPrompt(e.target.value)} required />
                <div className="form-row">
                  <select value={taskType} onChange={(e) => setTaskType(e.target.value)}>
                    <option value="coding">코딩</option>
                    <option value="planning">기획</option>
                    <option value="design">디자인</option>
                    <option value="vision">비전</option>
                    <option value="debugging">디버깅</option>
                    <option value="qa">QA</option>
                    <option value="general">일반</option>
                  </select>
                  <select value={policy} onChange={(e) => setPolicy(e.target.value)}>
                    <option value="balanced">균형</option>
                    <option value="quality">품질 우선</option>
                    <option value="free">무료량 우선</option>
                    <option value="speed">속도 우선</option>
                  </select>
                </div>
                <button className="primary" type="submit">Router에게 자동 배정</button>
              </form>
            </section>

            <section className="panel route-result">
              <p className="eyebrow">ROUTING RESULT</p>
              <h2>담당 AI</h2>
              {decision ? (
                <div className="selected-agent">
                  <span className="agent-badge">SELECTED</span>
                  <strong>{decision.selected.employee_name}</strong>
                  <p>{decision.selected.provider} · {decision.selected.model}</p>
                  <div className="score">{decision.selected.score}</div>
                  <small>Router 적합도 점수</small>
                </div>
              ) : (
                <div className="empty">작업을 입력하면 Router가 자동으로 담당자를 선택합니다.</div>
              )}
            </section>
          </div>
        )}

        {tab === "logs" && (
          <section className="panel">
            <p className="eyebrow">ROUTING HISTORY</p>
            <h2>작업 로그</h2>
            <div className="log-list">
              {logs.length === 0 && <div className="empty">기록된 라우팅이 없습니다.</div>}
              {logs.map((log) => (
                <article className="log-row" key={log.id}>
                  <div>
                    <strong>{log.task.task_type}</strong>
                    <span>{log.task.prompt}</span>
                  </div>
                  <div>
                    <strong>{log.decision.selected.employee_name}</strong>
                    <span>{log.created_at}</span>
                  </div>
                </article>
              ))}
            </div>
          </section>
        )}

        {(tab === "projects" || tab === "settings") && (
          <section className="panel placeholder-panel">
            <p className="eyebrow">COMING NEXT</p>
            <h2>{tab === "projects" ? "프로젝트 공장" : "Factory 설정"}</h2>
            <p>V0 Router가 안정화되면 이 영역에서 프로젝트 생성부터 기획·개발·QA·배포까지 자동화합니다.</p>
          </section>
        )}
      </main>
    </div>
  );
}
