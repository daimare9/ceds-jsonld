# CEDS JSON-LD Generator — Agent Instructions

## Project Summary

This is `ceds-jsonld`, a Python library for ingesting education data from multiple sources (CSV, Excel, APIs, databases),
mapping it to CEDS/CEPI ontology-backed SHACL shapes, outputting conformant JSON-LD documents, and loading them
into Azure Cosmos DB NoSQL. The project is in active development following a phased roadmap.

**Runtime:** Python 3.14 on Windows (22-core machine)
**Workspace Root:** `C:\Github\CEDS-JSONLD-Generator`

---

## Critical Context — Read These First

Before making ANY changes, always read the following files to understand current project state:

1. **ROADMAP.md** — The master plan. Contains phases, architecture decisions, risk register. All work MUST align with this.
2. **ResearchFiles/PERFORMANCE_REPORT.md** — Key performance findings. Direct dict construction is 161x faster than rdflib+PyLD.
3. **ResearchFiles/person_example.json** — The canonical target output format for Person shape.
4. **ResearchFiles/Person_SHACL.ttl** — The canonical SHACL shape pattern. All shapes follow this structure.

---

## Task Routing

When the user asks you to do something, classify the request and follow the specific instructions:

### "Start a new phase" or "Begin Phase X"
→ Use the `/new-phase` prompt or read `.github/prompts/new-phase.prompt.md`
→ MUST ask clarifying questions before writing any code
→ MUST present a task breakdown for approval before starting
→ When all phase tasks pass, auto-update `ROADMAP.md` per Rule 7 before reporting results

### "Create a new shape" or "Add [X] shape"
→ Use the `/new-shape` prompt or read `.github/prompts/new-shape.prompt.md`
→ Creates SHACL, context, mapping YAML, sample data, and tests as a unit

### "Run tests" or "Check tests" or "Verify"
→ Use the `/run-tests` prompt or read `.github/prompts/run-tests.prompt.md`
→ Always run tests AFTER any code change, never skip this step

### "Update roadmap" or "Change the plan" or "Pivot"
→ Use the `/update-roadmap` prompt or read `.github/prompts/update-roadmap.prompt.md`
→ Update ROADMAP.md immediately — it is the source of truth

### "Research [library]" or "Look up [tool]"
→ Use the `/research-library` prompt or read `.github/prompts/research-library.prompt.md`
→ Save findings to `.github/docs/library-reference/` for future sessions

### "Benchmark" or "Performance test"
→ Use the `/benchmark` prompt or read `.github/prompts/benchmark.prompt.md`
→ Always compare against baseline numbers from PERFORMANCE_REPORT.md

### "Fix issues" or "Pick up an issue" or "Work on issue #X"
→ Follow the **Issue Ticket Workflow** below — every step is mandatory.

### "Release" or "Tag" or "Publish" or "Push to main"
→ Follow the **Release Checklist** in `.github/instructions/git-workflow.instructions.md`
→ Run the full pre-release checklist (lint, format, tests, version consistency, CHANGELOG) **before** merging to main
→ Never skip the version-consistency check — `pyproject.toml`, `__init__.py`, and `CHANGELOG.md` must all agree

#### Issue Ticket Workflow

1. **List open issues.** Run `gh issue list --state open` (ensure `C:\Program Files\GitHub CLI` is on `$env:PATH`).
2. **Pick one issue.** If the user didn't specify which, choose the most impactful or security-relevant issue and state your choice.
3. **View the issue.** Run `gh issue view <number>` to read the full description, repro steps, and expected behaviour.
4. **Create a topic branch from `dev`.** Branch name must follow the git workflow convention:
   - `fix/<issue#>-<kebab-case-summary>` for bugs (e.g. `fix/5-int-clean-precision-loss`)
   - `feature/<issue#>-<summary>` for enhancements
   - **Never make changes directly on `dev` or `main`.**
   - `git checkout dev && git pull origin dev && git checkout -b fix/<issue#>-<summary>`
5. **Read the relevant source code** to understand the root cause before writing any fix.
6. **Implement the fix** on the topic branch, following coding standards in `.github/instructions/python-code.instructions.md`.
7. **Add tests** that prove the bug is fixed, following `.github/instructions/testing.instructions.md`.
8. **Run the full test suite once** (`python -m pytest tests/ -v --tb=short`). All tests must pass.
9. **Commit** with a Conventional Commits message referencing the issue: `fix(scope): description\n\nCloses #<number>`.
10. **Push the topic branch** to `origin`.
11. **Merge into `dev`** with `--no-ff`: `git checkout dev && git merge --no-ff <branch>` (set `$env:GIT_EDITOR = "true"` to auto-accept the merge message).
12. **Push `dev`** to `origin`.
13. **Delete the topic branch** (local + remote):
    - `git branch -d <branch>`
    - `git push origin --delete <branch>`
14. **Close the issue** with a summary comment: `gh issue close <number> --comment "..."`. Include: commit hash, what changed, tests added, pass count.

> **Key guardrail:** Never skip step 4 (branch creation). If you catch yourself about to edit files on `dev`, stop and create the branch first.

### General coding / bug fixing / feature implementation
→ Follow the coding standards in `.github/instructions/python-code.instructions.md`
→ Follow the testing protocol in `.github/instructions/testing.instructions.md`
→ Follow the Git workflow in `.github/instructions/git-workflow.instructions.md`
→ Reference library docs in `.github/docs/library-reference/` when using external libraries

---

## Mandatory Workflow Rules

### 1. Always Consult the Roadmap
Before starting any significant work, read `ROADMAP.md` and identify:
- Which phase this work belongs to
- Whether prerequisite phases are complete
- If the request conflicts with architectural decisions in the roadmap

If the user's request diverges from the roadmap, **say so explicitly** and ask whether to update the roadmap.

### 2. Ask Clarifying Questions at Phase Boundaries
When beginning a new phase or major feature, ALWAYS ask:
- What is the acceptance criteria for this phase?
- Are there any constraints or preferences not in the roadmap?
- Should we adjust scope, add items, or remove items?
- What is the priority order if there are multiple tasks?

Present the phase tasks as a numbered list and get confirmation before starting.

### 3. Testing is Not Optional
- Every code change MUST have a corresponding test.
- Run tests **once** after a logical set of related changes — not after every micro-edit.
- **Never re-run tests that already passed.** If the suite passed, move on.
- **Never grep or filter pytest output.** Run `pytest` directly and read the raw output.
  Do not pipe through `Select-String`, `grep`, `findstr`, or `Select-Object`.
- Tests must pass before moving to the next task.
- Report test results with: pass count, fail count, and failure details.
- Performance-sensitive code must include benchmark assertions.
- **Never write fake or mock-based tests when the real dependency can be installed.** See Rule 8.
- **Use `cls ;` before test commands** to clear stale terminal output. The shared terminal
  accumulates history; without clearing, you will misread old failures as current ones.
- **Set timeout ≥ 360000 (6 min) for full suite runs.** The 900+ test suite takes 3–6 min.
  A short timeout causes `KeyboardInterrupt` that looks like real failure.
- **When output is in a temp file, read the END.** Large output files contain the entire
  terminal buffer. Old run results are at the top; current results are at the bottom.

### 4. Update the Roadmap Immediately on Pivots
If the user says anything like "let's change direction", "actually let's do X instead", or "skip that":
- Update `ROADMAP.md` immediately with the change
- Mark skipped items with ~~strikethrough~~ and a note explaining why
- Add new items in the appropriate phase
- Confirm the change with the user

### 5. Reference Library Docs, Don't Guess
When using `rdflib`, `pyshacl`, `azure-cosmos`, `orjson`, or `pyyaml`:
- Read the reference doc in `.github/docs/library-reference/` FIRST
- Use the exact API patterns documented there
- If the reference doc is missing or outdated, fetch updated docs and save them

### 6. Progress Tracking
- Use a todo list to track all tasks in the current session
- Mark tasks in-progress → completed as you go
- Provide a brief status update after completing each task

### 7. Update Roadmap and README on Phase Completion
When all tasks for a phase are complete and the full test suite passes:
- Update `ROADMAP.md` **immediately** — do NOT wait for the user to ask.
- Mark all deliverable checkboxes (`- [ ]` → `- [x]`) with details.
- Update the phase status line (e.g. `Status: Phase 3 — In Progress (Phases 0–2 Complete)`).
- Update the summary timeline table (add ✅ Complete and brief results).
- Set the roadmap date to the current date.
- Add a completion note block (e.g. `> **Phase 2 completed February 2026.** ...`).
- Update `README.md` — update the **Project Status** table, add any new user-facing
  feature sections (e.g. Validation, CLI), update test/coverage counts, and ensure
  all code examples still work with the latest API.
- Then suggest next steps to the user based on the upcoming phase.

### 8. Install Real Dependencies — No Fake Tests
Never create mock-based or "fake" tests that substitute a stub for a real library
when that library can simply be installed. Mocking a library you control the
environment for negates the validity of those tests.

- **Install first, then test.** If a test needs `httpx`, `sqlalchemy`, `openpyxl`,
  or any other optional dependency, install it in the dev environment before writing
  the test.  Use `pip install ceds-jsonld[dev,excel,api,database]` or equivalent.
- **Mocks are only acceptable for true external services** — live APIs with auth
  tokens, production databases, Azure Cosmos DB endpoints — where a real call is
  impractical or costly.  Even then, prefer lightweight local substitutes (e.g.
  SQLite for database tests, local HTTP test servers via `pytest-httpserver`).
- If a dependency cannot be installed for a valid reason (e.g. binary not
  available for the platform), mark the test with `@pytest.mark.skip` with a
  clear reason — do NOT write a passing fake.

### 10. Git Branching & Commits
Follow the Git workflow defined in `.github/instructions/git-workflow.instructions.md`. The key rules:

- **Never commit directly to `main` or `dev`.** Always create a topic branch.
- **Branch from `dev`** for all normal work. Branch from `main` only for hotfixes.
- **Branch names** must use type prefixes: `feature/`, `fix/`, `docs/`, `refactor/`, `test/`, `chore/`, `perf/`, `hotfix/`.
- **Commit messages** must follow [Conventional Commits](https://www.conventionalcommits.org/): `type(scope): description`.
- **Merge to `dev`** with `--no-ff` when the feature is complete and tests pass.
- **Merge to `main`** only on explicit release — never automatically.
- **Push after every commit** to back up work to the remote.
- **Delete topic branches** after merging (both local and remote).

### 9. Design for the End User
Every feature, API, and code change must be evaluated from the **end user's perspective** — the education data engineer who installs this library and uses it to convert their data.

- **Before adding a feature**, ask: "How would a user discover and use this? Can they do it through the Pipeline, or are we forcing them into low-level components?"
- **The Pipeline is the primary interface.** Any capability that exists in lower-level components (FieldMapper, JSONLDBuilder) should also be accessible through Pipeline parameters when it's a common need. Column renaming, custom transforms, and output format are common needs — they belong on Pipeline.
- **Minimize setup ceremony.** If the user has to create 3 objects and call 4 methods before doing useful work, the API has too much friction. Look for ways to reduce it.
- **Imports should be flat.** All public classes should be importable from `ceds_jsonld` directly. Never require users to import from sub-packages for standard workflows.
- **Errors must guide the user.** Every error message should say what happened, what the user likely intended, and what to do instead. Example: `"Field 'FIRST_NM' not found in source data. Available columns: ['FirstName', 'LastName', ...]. Did you mean to use source_overrides to remap column names?"`
- **README examples must run.** Every code snippet in the README must work if copy-pasted. Variables cannot be undefined, imports cannot be missing.
- **Write user journey tests.** For every feature, write at least one test that mimics a real user's complete workflow (CSV → Pipeline → JSON-LD output), not just an internal unit test.

---

## Key Architecture Decisions (DO NOT VIOLATE)

These are settled decisions from our research phase. Do not revisit unless the user explicitly asks.

1. **Direct dict construction** — Build JSON-LD as plain Python dicts. Do NOT use rdflib graph construction + PyLD compaction for production output. (161x faster, proven)
2. **orjson for serialization** — Use `orjson` for all JSON output. Fall back to stdlib `json` only if orjson is unavailable.
3. **YAML mapping configs** — Each shape has a `_mapping.yaml` that drives field mapping. SHACL defines constraints; YAML defines source mappings.
4. **One Cosmos container per shape** — Separate containers for Person, Organization, etc.
5. **SHACL validation is optional** — pySHACL validation is opt-in, not in the hot path. Use lightweight pre-build validation for 100% of records.
6. **Per-shape file organization** — Each shape is a self-contained folder: SHACL + context + mapping + extensions + sample data.

---

## Directory Structure

```
CEDS-JSONLD-Generator/
├── .github/
│   ├── copilot-instructions.md          ← YOU ARE HERE (main routing instructions)
│   ├── instructions/                    ← Path-specific coding rules
│   │   ├── python-code.instructions.md  ← Python coding standards (all .py files)
│   │   ├── ontology.instructions.md     ← SHACL/TTL/RDF rules (ontology files)
│   │   ├── testing.instructions.md      ← Testing protocol (test files)
│   │   ├── cosmos.instructions.md       ← Cosmos DB patterns (cosmos module)
│   │   ├── yaml-mapping.instructions.md ← Mapping config rules (.yaml files)
│   │   └── git-workflow.instructions.md ← Git branching, commits, merge strategy
│   ├── prompts/                         ← On-demand slash commands
│   │   ├── new-phase.prompt.md          ← /new-phase
│   │   ├── new-shape.prompt.md          ← /new-shape
│   │   ├── run-tests.prompt.md          ← /run-tests
│   │   ├── update-roadmap.prompt.md     ← /update-roadmap
│   │   ├── research-library.prompt.md   ← /research-library
│   │   └── benchmark.prompt.md          ← /benchmark
│   └── docs/
│       └── library-reference/           ← Local copies of library API docs
│           ├── rdflib-reference.md
│           ├── pyshacl-reference.md
│           ├── azure-cosmos-reference.md
│           ├── orjson-reference.md
│           └── pyyaml-reference.md
├── ROADMAP.md                           ← Master project plan (source of truth)
├── ResearchFiles/                       ← Prior research (read-only reference)
│   ├── PERFORMANCE_REPORT.md
│   ├── Person_SHACL.ttl
│   ├── person_example.json
│   ├── Person_context.json
│   ├── context.json (26K lines CEDS)
│   ├── Common.ttl
│   ├── benchmark_approaches.py
│   └── ... (other research artifacts)
├── src/                                 ← Library source code (future)
│   └── ceds_jsonld/
├── tests/                               ← Test suite (future)
├── ontologies/                          ← Shape definitions (future)
│   ├── base/
│   ├── person/
│   └── organization/
└── pyproject.toml                       ← Project config (future)
```

---

## Environment Setup

- Python 3.14 with pip
- Install dev deps: `pip install rdflib pyshacl orjson pyyaml pandas openpyxl pytest pytest-cov hypothesis ruff mypy`
- Always run commands from workspace root: `C:\Github\CEDS-JSONLD-Generator`
- Use PowerShell syntax (Windows) — use `;` not `&&` to chain commands

---

## How to Use These Instructions Efficiently

**For the human operator:**

1. **Starting a new phase:** Type `/new-phase` in chat or say "Begin Phase X"
2. **Quick shape creation:** Type `/new-shape` or say "Create Organization shape"
3. **After code changes:** Type `/run-tests` or say "Run the tests"
4. **Changing plans:** Say "Update roadmap: [your change]" — I'll update ROADMAP.md immediately
5. **Need library help:** Say "Research [library name]" — I'll fetch docs and save them locally
6. **Performance check:** Type `/benchmark` or say "Benchmark the Person builder"

**Trust these instructions.** Only search the workspace for additional context if information here is incomplete or appears incorrect.
