# Instructions for automated agents

You are an automated research agent contributing to the `lean_rewrite` project. **Multiple instances of you may run concurrently on the same local machine, all reading and writing this repository**. Follow the workflow below strictly — it is the only thing preventing collisions between agents.

## Project goal

Build a Python tool that takes a Lean 4 definition from mathlib4 and proposes rewrites that make downstream proofs easier to work with. The long-term goal is to automate the kind of iterative refinement shown by Buzzard et al., *Schemes in Lean* (arXiv:2101.02602). See `PLAN.md` for the current phase and `TASKS.md` for open tasks. These two files are authoritative — always defer to them over anything you remember.

## Startup procedure

When you are invoked (likely by a scheduled trigger), your session must be self-contained — do not rely on any prior conversation state. Start from the loop below.

### 1. Sync

Always start from a clean, up-to-date state. If a local clone already exists, update it; otherwise clone first:

**Every session must work inside its own isolated clone.** Never modify the main checkout at `/Users/san/lean_rewrite` directly — that is the human operator's working copy.

```bash
SESSION=$(mktemp -d -t lr-agent-XXXXXX)
git clone https://github.com/sann-ai/lean_rewrite.git "$SESSION"
cd "$SESSION"
git config user.email "sann-ai@users.noreply.github.com"
git config user.name "sann-ai"
```

The session clone is small (~a few MB) and the clone completes in a few seconds. At the very end of the session — after your last successful push — clean it up:

```bash
cd /tmp  # or anywhere outside $SESSION
rm -rf "$SESSION"
```

If you have to bail out early due to an error, leave the session directory in place so the human operator can inspect it.

### 2. Read state

Read the following, in this order:

1. `PLAN.md` — current phase and approach
2. `TASKS.md` — find tasks with `status: open`
3. The last ~80 lines of `NOTEBOOK.md` — see what recent agents did, avoid duplicating
4. `QUESTIONS.md` — look for any tasks blocked on a question that has just been answered (see §"Asking for human input" for the protocol)

When choosing a task, **respect its dependencies**. Each task has a `依存:` (dependencies) field listing other task IDs. Skip any task whose dependencies are not all `status: done`. For example, if `T005` has `依存: T003` and T003 is still `open` or `claimed`, do not claim T005 — pick a different task.

If a task's status is `blocked: awaiting Q0NN`, check `QUESTIONS.md`:
- If Q0NN has an `**Answer:**` filled in, treat the task as eligible to claim. Your claim commit should both (a) change the task's status back to `claimed` with your agent ID, and (b) reference the answered question in a NOTEBOOK entry so later readers can follow the reasoning.
- If Q0NN is still unanswered, skip the task.

### 3. Claim a task (mandatory before any work)

You must claim your task **atomically via git** before doing any real work. Do not start working until the claim has been successfully pushed.

1. Generate an agent ID at session start (a random 6-character alphanumeric string, e.g. `a7f2k9`).
2. Edit `TASKS.md` for the task you picked:
   - `status: open` → `status: claimed`
   - `claimed_by: <agent-id>`
   - `claimed_at: <UTC ISO8601>` (e.g. `2026-04-18T14:30:00Z`)
3. `git add TASKS.md && git commit -m "claim: <task-id> by <agent-id>"`
4. `git push origin main`
5. If the push is rejected as non-fast-forward:
   - `git pull --rebase origin main`
   - Re-read `TASKS.md`
   - If your task is still `open`, re-apply the edit and push again
   - If someone else has claimed it, pick a different task and start over

**Claims expire after 90 minutes without progress.** Here, *progress* means any commit on `origin/main` authored by the claim holder's agent ID (including a small `NOTEBOOK.md` status update). The 90-minute clock resets at the most recent such commit. If your task is expected to run longer than 90 minutes, push an incremental `NOTEBOOK.md` note every ~45 minutes. If you find an expired claim, you may reclaim it, but record it in `NOTEBOOK.md` as `Re-claimed stale task <id> (previously <old-agent>)`.

### 4. Work

- Stay within the scope of the claimed task. Do not touch unrelated code.
- If the task turns out to be too large, split it: edit `TASKS.md` to narrow the scope and add new follow-up tasks (a claim holder may edit their own task entry).
- When writing code, add at least a minimal pytest where it makes sense.

**Prohibited**:

- Destroying in-progress work of other agents
- `git push --force` or force-with-lease
- Modifying CI configuration or branch protection
- Committing secrets, API keys, or tokens
- Modifying `AGENTS.md` (requires human approval)
- Running `git rm -rf`, `rm -rf`, or equivalent destructive commands without human approval

### 5. Record and release

When you are done:

1. Append an entry to `NOTEBOOK.md` (append-only):

   ```markdown
   ## <UTC ISO8601> — <task-id> — <agent-id>
   - Did:
   - Learned (especially anything surprising):
   - Files touched:
   - Next steps (if any):
   ```

2. Update `TASKS.md`: set the task to `status: done`, or to `status: blocked: <reason>`. If blocked, add a follow-up task.
3. If the plan itself changed, update `PLAN.md` — but only for small, incremental updates. Any large change in direction must be stopped with `status: blocked: needs human`.
4. `git add -A && git commit -m "<task-id>: <short imperative summary>"`
5. `git push origin main`. On conflict, `git pull --rebase` and push again.

### 6. Stop conditions

End the session under any of the following:

- Task completed and pushed
- Cannot make progress (record the blocker in `NOTEBOOK.md` and set `status: blocked: <reason>`)
- 60 minutes elapsed (record the state as `status: blocked: timeout` and release the claim)
- A decision point requires human judgment (set `status: blocked: needs human` and **stop**)

## Asking for human input (`QUESTIONS.md`)

If you hit a decision that genuinely needs the human operator's guidance AND can be answered in **1–2 sentences or a choice of options**, post the question to `QUESTIONS.md` instead of escalating to the heavier `blocked: needs human`.

### When to ask vs decide yourself

**Ask** for:
- Direction-level questions that affect multiple future tasks ("should the algorithm prioritize X or Y?")
- A choice between equally-defensible strategies with different downstream tradeoffs
- Scope clarifications ("does X count as a valid signal for this metric?")
- Questions whose answer the human almost certainly has cached ("do we care about backwards compatibility with Lean 3?")

**Decide yourself** for:
- Routine implementation choices (naming, test coverage, adding a docstring)
- Questions that become clear on careful re-reading of `PLAN.md` / `AGENTS.md`
- Things you can resolve empirically by trying (e.g. "does this build?")

**At most one question per session.** If you have more, pick the most blocking and leave the rest for a follow-up session to raise. Prefer solving small things yourself over asking.

### Question format (append to `QUESTIONS.md`)

```
## Q0NN — <short title> — <agent-id> — <UTC ISO>

**Context**: 2–3 sentences of what you were doing
**Question**: the specific thing you need answered
**Options considered**:
- A: <option>
- B: <option>
- (optional) C: ...
**Blocker level**: low | medium | high
**Associated task**: T0NN | planning | (empty)

**Answer**:

<!-- human to fill in -->
```

Continue the Q numbering from the highest existing `Q0NN` in the file.

### After posting a question

1. Change the associated task's status to `blocked: awaiting Q0NN` (if there is one).
2. Append a short NOTEBOOK entry:
   ```
   ## <UTC ISO> — question posted — <agent-id>: Q0NN — <title>
   ```
3. Commit as `ask: Q0NN — <short title>`, push, and stop the session. The task is now in the hands of the human.

### Looking for answered questions

Step 2 of the main workflow directs you to read `QUESTIONS.md`. Before the main planning flow:
- Tasks with `status: blocked: awaiting Q0NN` where Q0NN has an `**Answer:**` → eligible again. Claim and resume.
- Questions without an `**Answer:**` → leave as-is; pick another task or enter planning (but do not re-ask the same question).

### Asking as a planning agent

A planning agent (see §"Planning when idle") may also post a question when the direction is genuinely unclear — for example, when multiple tiers have very different interpretations. Use the same format, `Associated task: planning`. Still cap at one question per session.

## Planning when idle

If Step 2 finds **zero eligible open tasks** (all existing tasks are `done` or `blocked`), you do NOT stop with an idle tick. You become a **planning agent** whose job is to extend the task backlog toward the "Completion criteria" in `PLAN.md`.

### Planning procedure

1. Re-read `PLAN.md`, especially the "Completion criteria" section and the current phase. These define the target.
2. Read the last ~200 lines of `NOTEBOOK.md` — what was just completed, what did recent agents learn, what follow-ups did they flag?
3. Scan `TASKS.md` for the highest existing task ID (e.g., `T007`). New tasks continue the numbering (`T008`, `T009`, ...).
4. Run `git pull --rebase origin main` one more time. **If another agent raced you and has added open tasks, abort planning**: exit without modifying anything (the system is no longer idle).
5. Judge whether the Completion criteria have been met, using NOTEBOOK evidence:
   - If **all tiers are satisfied** (and a human has not flagged Tier gaps), append a single idle entry to `NOTEBOOK.md` — e.g. `## <UTC> — idle — <agent-id>: completion criteria appear met; awaiting human direction` — commit as `chore: idle tick by <agent-id>`, push, and stop.
   - Otherwise, identify the **nearest unmet tier** and propose **2–4 concrete next tasks** to advance it.
6. For each proposed task:
   - Unique new ID continuing the sequence
   - `status: open`, empty `claimed_by` / `claimed_at`
   - Explicit `依存:` — only list prerequisites that are already `status: done` (no forward references)
   - Description tight enough that a different agent can execute it without asking you: include relevant file paths, acceptance criteria, constraints, and any test expectations
7. Append a planning entry to `NOTEBOOK.md`:
   ```
   ## <UTC ISO> — planning — <agent-id>
   - Trigger: TASKS.md had zero eligible open tasks.
   - Reading: <1–2 sentences on which tier is unmet and why>
   - New tasks: T0NN..T0MM
   - Rationale: <1 short paragraph on how these advance Completion criteria>
   ```
8. Commit as `plan: add T0NN..T0MM`, push. The next scheduled fire will claim one of these.

### Planning guardrails

- Propose **at most 4 tasks** in a single planning run.
- **Never modify or delete existing tasks.** Only append new ones.
- **Never add a task whose dependency is not yet `done`.**
- Do not alter `AGENTS.md`, `README.md`, or the Completion criteria in `PLAN.md` — those are human-approval territory.
- If you believe the Completion criteria themselves need revision, stop planning and append `## <UTC> — blocked: needs human — <agent-id>` to `NOTEBOOK.md` naming the criterion and why; do not add tasks premised on revised criteria.
- If the last 2 consecutive NOTEBOOK entries are already `planning` entries (another agent just planned, and the last-planned tasks haven't executed yet), stop without adding more — you're looping.

### Auto-pause after prolonged idle

If the last **5 NOTEBOOK entries are all `idle` entries**, the project is genuinely out of productive work and cron cycles are being wasted. Instead of writing a 6th idle entry:

1. Call `mcp__scheduled-tasks__update_scheduled_task` with:
   - `taskId`: `lean-rewrite-agent`
   - `enabled`: false
2. Append a single NOTEBOOK entry:
   ```
   ## <UTC ISO> — auto-pause — <agent-id>
   - Trigger: 5+ consecutive idle entries; completion criteria still appear met.
   - Action: Disabled the `lean-rewrite-agent` scheduled task to conserve cron cycles.
   - Re-enable: After the human operator adjusts `PLAN.md` Completion criteria or adds new tasks, they can toggle the task back on via `mcp__scheduled-tasks__update_scheduled_task(taskId='lean-rewrite-agent', enabled=true)` or from the desktop Scheduled sidebar.
   ```
3. Commit as `chore: auto-pause scheduler after idle streak`, push, stop.

This rule applies to **the default scheduled-task agent only**. A manually-invoked agent (spawned by a human via the Agent tool, or by the user running the kickoff prompt directly) must not pause the scheduler.

## Conventions

- **Commit messages**:
  - Claim: `claim: <task-id> by <agent-id>`
  - Work: `<task-id>: <short imperative>`
  - Completion: `done: <task-id>: <short summary>` (subject line ≤72 chars; longer details go in a multi-line body after a blank line)
- **One task per session.** Never hold multiple tasks at once.
- When in doubt, do not change anything — leave a note in `NOTEBOOK.md` and stop.
- All timestamps must be **actual UTC**, not your local timezone with a `Z` suffix. Run `date -u +%Y-%m-%dT%H:%M:%SZ` in a shell to get a correct value (e.g. `2026-04-18T14:30:00Z`). Do not compute UTC from local time mentally — the offset is easy to get wrong.
- Use your agent ID consistently throughout the session, in both commit messages and the `claimed_by` field.

## Per-file modification policy

| File | Modifiable? |
|---|---|
| `AGENTS.md` | No — human approval required |
| `README.md` | No — human approval required |
| `PLAN.md` | Yes, when your work affects the plan |
| `TASKS.md` | Yes (claim / release / add follow-ups) |
| `NOTEBOOK.md` | Append only |
| `src/`, `scripts/`, `experiments/` | Yes, within the scope of your task |

## Environment assumptions

- macOS (darwin), `elan` + `lean` + `lake` already installed
- `gh` CLI authenticated as `sann-ai` with push access
- Python 3 available as `python3` (not `python`); `pytest` already installed globally
- mathlib4 is cloned at `/Users/san/mathlib4` (done by T001). **Treat it as read-only.**
- This machine is shared with other Lean / Python projects. Respect the rules below to avoid stepping on them.

## Isolation rules (do not break)

### Mathlib must never be edited in place

The shared mathlib4 clone at `/Users/san/mathlib4` is used by other projects on this machine. **Agents must never modify it directly.** If your task needs a modified mathlib (e.g. to test a candidate rewrite), create an ephemeral worktree:

```bash
MLWT=$(mktemp -d -t mlwt-XXXXXX)
(cd /Users/san/mathlib4 && git worktree add "$MLWT" HEAD)
# apply changes inside $MLWT, build there with `cd $MLWT && lake build ...`
# The .lake cache from the parent mathlib4 is shared automatically.
```

On session exit, clean up:

```bash
(cd /Users/san/mathlib4 && git worktree remove --force "$MLWT" 2>/dev/null) || rm -rf "$MLWT"
```

The parent clone's `.lake/` cache is linked into worktrees, so cache downloads are not duplicated. Worktrees that fail to clean up cost disk, not correctness.

### Python dependencies stay in a per-session venv

If your task requires installing any Python package beyond the standard library and `pytest`, do it inside a per-session venv, never globally:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .  # or install the specific dep you need
```

The `.venv/` directory is gitignored. Do not commit `requirements.txt`/`pyproject.toml` dependency additions without justifying them in `NOTEBOOK.md`.

If your task needs no extra deps (as T003/T004 did not), just run `python3 -m pytest tests/` directly — no venv needed.

## Common pitfalls

- **mathlib4 builds are slow.** Always run `lake exe cache get` before attempting any build.
- **Panic on push conflict.** Always resolve by `git pull --rebase` and re-verifying state. Never use `--force`.
- **Redefining existing task IDs.** Do not repurpose an existing `T00X`; add a new ID (`T0XX`) instead.
- **Forgetting to release.** Before you exit, the task must be either `done` or `blocked: ...` in `TASKS.md` on `origin/main`.

## Language

The canonical language of this repository is a mix: `AGENTS.md` (this file) is in English so that prompts remain legible across tools; `PLAN.md`, `TASKS.md`, and `NOTEBOOK.md` may contain Japanese content written by the human operator. Read whichever language you encounter; write new notebook entries in whichever language is natural for the content (short and factual is preferred regardless).
