# AI Factory Agent Swarm Architecture

This document records architectural ideas adopted after reviewing HKUDS/ClawTeam.

## Why this reference matters

ClawTeam demonstrates several production-proven patterns that match AI Factory's goals:

- A leader agent can create specialized workers dynamically.
- Work is represented as dependency-aware tasks rather than free-form chat.
- Each coding worker can receive an isolated Git worktree and branch.
- Agents communicate through structured inbox messages.
- Workers report lifecycle states such as idle/completed/blocked.
- A Web UI can expose the entire swarm to the human operator.
- Team templates allow reusable role/task compositions.

AI Factory will adopt these patterns conceptually, while adding a game-studio production model, multi-provider quota routing, plugin-style AI hiring, and CEO review workflows.

---

## AI Factory-specific architecture

### 1. CEO
The human user is the Executive Producer.

The CEO should mainly:
- provide a topic or product brief
- inspect ideas, builds and progress
- choose an older backlog idea to revive
- send revision feedback
- approve release

The CEO should not manually coordinate agents.

### 2. Studio Director / Leader Agent

Every active production line has a Leader Agent.

Responsibilities:
- interpret the current game-production stage
- decompose work into tasks
- create worker agents
- declare dependencies
- watch budget / quota
- reassign blocked work
- consolidate outputs
- decide when QA is required
- report the stage status to the dashboard

### 3. Worker Agents

Workers are ephemeral and role-specific.

Examples:
- Creative Director
- Game Designer
- Systems Designer
- Technical Director
- Gameplay Programmer
- UI/UX Designer
- Art Director
- QA
- Build Engineer
- Release Manager

Workers do not permanently own a project. The Router assigns the best available AI employee for each role and task.

### 4. Task Graph

Every stage is represented as a dependency graph.

Example:

T1 Core-loop specification
T2 Economy specification         blocked by T1
T3 Save architecture             blocked by T1
T4 Gameplay prototype            blocked by T1,T3
T5 UI prototype                  blocked by T1
T6 Integration                   blocked by T4,T5
T7 QA                            blocked by T6

States:
- pending
- blocked
- ready
- in_progress
- review
- completed
- failed

A completed dependency automatically unlocks downstream work.

### 5. Git Worktree Isolation

Coding workers must work in isolated Git worktrees.

Branch convention:

ai-factory/<project>/<line>/<agent>/<task>

Flow:
1. Leader creates task.
2. Router chooses AI employee.
3. Worker receives a worktree.
4. Worker commits only inside its branch.
5. Reviewer inspects diff.
6. Tests run.
7. Leader merges approved work.
8. Worktree is cleaned up.

This avoids multiple agents overwriting the same files.

### 6. Agent Messaging

Workers communicate using structured messages.

Message types:
- task_started
- question
- dependency_ready
- result
- review_request
- blocked
- quota_warning
- handoff
- idle

Each message contains:
- team
- production line
- sender
- recipient
- task id
- timestamp
- payload

The system may initially store messages in SQLite. Later transports can support Redis / P2P while retaining the same interface.

### 7. Adaptive Scheduling

Unlike a fixed swarm, AI Factory must dynamically change workers based on:

- role fit
- task complexity
- remaining free quota
- token/request burn rate
- response speed
- error rate
- recent task quality
- required modality
- context length
- expected task cost

Default policy:

CHEAPEST_VIABLE_QUALITY

Meaning:
1. Use unlimited/local workers for simple repeated work.
2. Use free cloud quota when quality gain is worthwhile.
3. Reserve scarce high-quality quota for hard tasks/review.
4. If a provider approaches its reserve threshold, stop assigning non-critical work.
5. Automatically fail over to the next compatible AI.
6. If every cloud provider is unavailable, keep the factory alive with local workers.

The factory must never stop merely because one provider hits a limit.

### 8. Multi-line Game Studio

One theme may generate 10+ ideas.

The system should:
1. Generate approximately 10 concepts.
2. Run multi-agent critique.
3. Score feasibility, cost, differentiation, core-loop clarity, marketability and technical risk.
4. Automatically shortlist the best few based on the configured parallel-line budget.
5. Start separate production lines for the shortlist.
6. Keep the rest in an Idea Backlog.
7. Allow the CEO to later press "Build this idea" and create a new production line.

Every line has its own:
- Leader
- task graph
- Git branches/worktrees
- artifacts
- build history
- feedback history
- cost/quota history

### 9. Plugin-style AI Hiring

AI employees are installed from an AI Marketplace.

Provider adapter contract:
- id
- display_name
- auth_type
- models
- capabilities
- quota_probe
- health_check
- execute
- token_usage_parser
- error_classifier

Auth types:
- oauth
- api_key
- local
- custom_endpoint

Marketplace UX:
- Recommended
- Installed
- Free
- Coding
- Planning
- Vision
- Image
- Audio
- Local
- Needs login

Clicking "+" installs the provider adapter and starts its auth flow.

### 10. Account Sync / Secret Vault

Google login identifies the AI Factory user.

Provider credentials must never be stored in GitHub Pages or browser localStorage.

Target flow:

Browser
  -> Google login
  -> AI Factory backend
  -> encrypted secret vault
  -> provider adapters

Stored account data:
- installed AI employees
- encrypted provider credentials
- projects
- production lines
- quota history
- dashboard settings

This allows the same AI configuration to appear on every device after login.

### 11. Dashboard

The CEO dashboard should show the factory like a real production floor:

- Idea room
- Shortlisted ideas
- Backlog ideas
- Active production lines
- Current stage per line
- Active AI workers
- Task dependency graph
- Agent messages
- Git branch/worktree state
- Latest commits
- QA failures
- Build artifacts
- Provider quota gauges
- Cost-saving decisions
- automatic failovers
- CEO feedback requests

The dashboard is observational by default. Manual controls are available but not required.

### 12. Reusable Team Templates

Borrow the useful concept of team templates, specialized for game production.

Examples:
- Game Ideation Team
- Prototype Team
- Vertical Slice Team
- Full Production Team
- QA / Release Team
- Live Ops Team

Templates define roles, expected artifacts and task patterns. The Leader may still spawn extra workers dynamically when needed.

---

## Key difference from generic agent swarms

ClawTeam-style coordination is used as the execution substrate.

AI Factory adds four opinionated layers above it:

1. Real game-studio production stages
2. Multi-provider free-quota optimization
3. Multi-line idea portfolio management
4. CEO-only review and feedback workflow

The goal is not merely "many agents talking."

The goal is a continuously operating autonomous game studio that produces reviewable builds.
