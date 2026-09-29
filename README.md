# AI Factory

## Live web preview

Open the current browser preview from any PC or phone:

https://thstjdals09-lang.github.io/-/

The preview is built from `docs/index.html` in this repository and is updated as development continues.

The preview generates a real standalone HTML5 microgame for every completed line. It can be played in the browser or downloaded as `index.html`. GitHub repository and Pages controls remain disabled until the server-side publisher returns a successful `published` result; predicted addresses are shown only as non-clickable text and must not be treated as deployed games.

AI Factory is a local-first multi-agent software production system.

The human owner acts as CEO. AI employees are registered with provider/model metadata, capabilities, quotas, and availability. A router assigns work automatically based on task type, quality, speed, free quota, and reliability.

## V0 goal

The first vertical slice is intentionally small:

1. Register AI employees
2. Store capability and quota metadata locally
3. Accept a task
4. Auto-select the best eligible AI employee
5. Record the routing decision
6. Expose the flow through a desktop UI

Later milestones add project planning, code generation, Git worktrees, review, QA, visual inspection, build, and release loops.

## Security

- API keys are never committed to Git.
- The repository stores only the environment-variable name that contains a provider key.
- Local databases and logs are ignored by Git.
- A later milestone will add an OS-backed encrypted secret store.

## Planned stack

- Desktop: React + TypeScript + Tauri
- Core API: Python + FastAPI
- Local persistence: SQLite
- Browser/UI QA: Playwright
- Source control: Git
- Local model fallback: llama.cpp-compatible OpenAI endpoint

## Development

Backend work starts in `backend/`.

```bash
cd backend
python -m venv .venv
# Windows
.venv\Scripts\activate
pip install -e ".[dev]"
pytest
uvicorn app.main:app --reload
```

The desktop frontend will be added after the routing core is covered by tests.

## Publish a completed game to GitHub Pages

The backend can create or update a repository named after the game, create a release commit on `main`, and enable GitHub Pages. Credentials stay on the backend and are never accepted from or returned to the browser.

```bash
cd backend
copy .env.example .env
# Set AI_FACTORY_GITHUB_TOKEN in the server environment.
uvicorn app.main:app --reload
```

Required token access:

- create and update repositories for the configured owner
- write repository contents
- administer GitHub Pages for those repositories

Check configuration with `GET /publishing/github/status`. Submit the completed text release files, including a root `index.html`, to `POST /publishing/github`. The response contains both `repository_url` and the playable `pages_url`.

The publisher rejects traversal paths, `.git`, `.env`, common credential files, private-key extensions, oversized files, and releases without a root `index.html`.
