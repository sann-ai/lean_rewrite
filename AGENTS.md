# Instructions for automated agents

You are an automated research agent contributing to the `lean_rewrite` project. **Multiple instances of you may run concurrently on the same local machine, all reading and writing this repository**. Follow the workflow below strictly — it is the only thing preventing collisions between agents.

## Project goal

Build a Python tool that takes a Lean 4 definition from mathlib4 and proposes rewrites that make downstream proofs easier to work with. The long-term goal is to automate the kind of iterative refinement shown by Buzzard et al., *Schemes in Lean* (arXiv:2101.02602). See `PLAN.md` for the current phase and `TASKS.md` for open tasks. These two files are authoritative — always defer to them over anything you remember.

## Startup procedure

When you are invoked (likely by a scheduled trigger), your session must be self-contained — do not rely on any prior conversation state. Start from the loop below.

### 1. Sync

Always start from a clean, up-to-date state. If a local clone already exists, update it; otherwise clone first:

```bash
REPO=/Users/san/lean_rewrite
if [ ! -d "$REPO/.git" ]; then
  git clone https://github.com/sann-ai/lean_rewrite.git "$REPO"
fi
cd "$REPO"
git fetch origin
git checkout main
git pull --rebase origin main
```

Because multiple agents may run in parallel, prefer operating in a dedicated worktree to avoid state contamination:

```bash
WT=$(mktemp -d -t lr-XXXXXX)
git worktree add "$WT" main
cd "$WT"
```

### 2. Read state

Read the following, in this order:

1. `PLAN.md` — current phase and approach
2. `TASKS.md` — find tasks with `status: open`
3. The last ~80 lines of `NOTEBOOK.md` — see what recent agents did, avoid duplicating

When choosing a task, **respect its dependencies**. Each task has a `依存:` (dependencies) field listing other task IDs. Skip any task whose dependencies are not all `status: done`. For example, if `T005` has `依存: T003` and T003 is still `open` or `claimed`, do not claim T005 — pick a different task.

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

**Claims expire after 90 minutes without progress.** If you find an older claim, you may reclaim it, but record it in `NOTEBOOK.md` as `Re-claimed stale task <id> (previously <old-agent>)`.

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

## Conventions

- **Commit messages**:
  - Claim: `claim: <task-id> by <agent-id>`
  - Work: `<task-id>: <short imperative>`
  - Completion: `done: <task-id>`
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
- Python 3.11+
- mathlib4 is not cloned initially — `T001` is responsible for cloning it to `/Users/san/mathlib4`

## Common pitfalls

- **mathlib4 builds are slow.** Always run `lake exe cache get` before attempting any build.
- **Panic on push conflict.** Always resolve by `git pull --rebase` and re-verifying state. Never use `--force`.
- **Redefining existing task IDs.** Do not repurpose an existing `T00X`; add a new ID (`T0XX`) instead.
- **Forgetting to release.** Before you exit, the task must be either `done` or `blocked: ...` in `TASKS.md` on `origin/main`.

## Language

The canonical language of this repository is a mix: `AGENTS.md` (this file) is in English so that prompts remain legible across tools; `PLAN.md`, `TASKS.md`, and `NOTEBOOK.md` may contain Japanese content written by the human operator. Read whichever language you encounter; write new notebook entries in whichever language is natural for the content (short and factual is preferred regardless).
