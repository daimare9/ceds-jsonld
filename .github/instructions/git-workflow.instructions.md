# Git Workflow — Branching & Commit Standards

**Applies to:** All work in this repository.

---

## Branch Structure

```
main          ← Production-ready. Only receives merges from dev. Never commit directly.
  └── dev     ← Integration branch. All feature work merges here first.
       ├── feature/add-org-shape
       ├── fix/iri-encoding-bug
       ├── docs/update-api-reference
       └── chore/upgrade-orjson
```

### Protected branches

| Branch | Direct commits | Force push | Receives merges from |
|--------|---------------|------------|----------------------|
| `main` | ❌ Never | ❌ Never | `dev` only |
| `dev`  | ❌ Never | ❌ Never | Topic branches only |

---

## Branch Naming Convention

All topic branches must use a **type prefix** followed by a `/` and a kebab-case description.

| Prefix | Use when... | Example |
|--------|-------------|---------|
| `feature/` | Adding new functionality | `feature/organization-shape` |
| `fix/` | Fixing a bug | `fix/csv-encoding-error` |
| `docs/` | Documentation-only changes | `docs/add-cosmos-guide` |
| `refactor/` | Restructuring without behaviour change | `refactor/pipeline-internals` |
| `test/` | Adding/fixing tests only | `test/add-excel-adapter-tests` |
| `chore/` | Dependency updates, CI config, tooling | `chore/bump-structlog` |
| `perf/` | Performance improvements | `perf/optimize-builder-loop` |
| `hotfix/` | Urgent fix for production (branches from `main`) | `hotfix/cosmos-auth-crash` |

**Rules:**
- Use lowercase only
- Use hyphens, not underscores or spaces
- Keep names short but descriptive (3–5 words max)
- Include issue number when applicable: `fix/42-null-birthdate`

---

## Commit Message Convention (Conventional Commits)

All commits follow the [Conventional Commits 1.0.0](https://www.conventionalcommits.org/) specification.

### Format

```
<type>(<optional scope>): <description>

[optional body]

[optional footer(s)]
```

### Allowed types

| Type | Purpose |
|------|---------|
| `feat` | New feature |
| `fix` | Bug fix |
| `docs` | Documentation only |
| `style` | Formatting, whitespace (no logic change) |
| `refactor` | Code restructuring (no feature/fix) |
| `perf` | Performance improvement |
| `test` | Adding or fixing tests |
| `build` | Build system or dependencies (`pyproject.toml`, etc.) |
| `ci` | CI/CD configuration |
| `chore` | Maintenance tasks |
| `revert` | Reverting a previous commit |

### Scopes (optional but encouraged)

Use the module or area being changed: `pipeline`, `builder`, `mapper`, `cosmos`, `cli`, `adapters`, `shacl`, `registry`, `serializer`, `validator`, `logging`, `sanitize`.

### Examples

```
feat(pipeline): add dead-letter queue for failed records
fix(builder): sanitize IRI components to prevent injection
docs: update README with production features
test(adapters): add Excel adapter edge case tests
refactor(pipeline): extract progress tracking into helper
build: add structlog and tqdm to optional deps
chore: update .gitignore for Sphinx build artifacts
perf(serializer): switch to orjson bulk serialization

feat(pipeline)!: return PipelineResult instead of int from to_json

BREAKING CHANGE: to_json() and to_ndjson() now return PipelineResult.
Use result.bytes_written for the previous int value.
```

### Rules

- **Subject line:** imperative mood, lowercase, no period, max 72 chars
- **Body:** wrap at 72 chars, explain *what* and *why* (not *how*)
- **Breaking changes:** append `!` after type/scope AND add `BREAKING CHANGE:` footer
- **One logical change per commit.** Don't mix a feature + a refactor + a test fix in one commit.

---

## Workflow — Day-to-Day Development

### Starting new work

```powershell
# 1. Make sure dev is up to date
git checkout dev
git pull origin dev

# 2. Create a topic branch
git checkout -b feature/my-new-feature

# 3. Do your work, commit often with conventional commits
git add -A
git commit -m "feat(pipeline): add progress callback support"

# 4. Push your branch
git push -u origin feature/my-new-feature
```

### Completing a feature (merge to dev)

```powershell
# 1. Make sure dev hasn't diverged
git checkout dev
git pull origin dev
git checkout feature/my-new-feature
git rebase dev    # or merge — see merge strategy below

# 2. Run tests to confirm everything passes
python -m pytest tests/ -v --tb=short

# 3. Merge into dev (use --no-ff to preserve branch history)
git checkout dev
git merge --no-ff feature/my-new-feature -m "feat(pipeline): add progress callback support"

# 4. Push dev
git push origin dev

# 5. Delete the topic branch (local and remote)
git branch -d feature/my-new-feature
git push origin --delete feature/my-new-feature
```

### Releasing to main

Only merge `dev` → `main` when `dev` is stable **and every pre-release check passes**.

#### Pre-release checklist (mandatory — every release)

Run every step **from `dev`**, in order.  Do not skip any step.

```powershell
# 0. Start clean
git checkout dev
git pull origin dev

# 1. Reinstall from source (catches stale installed metadata)
pip install -e ".[dev,cli]"

# 2. Lint — must match CI exactly
ruff check src/ tests/
ruff format --check src/ tests/

# 3. Type check
mypy src/

# 4. Full test suite — all must pass
python -m pytest tests/ -v --tb=short

# 5. Version consistency — the SAME version string must appear in all three places
#    • pyproject.toml   →  version = "X.Y.Z"
#    • src/ceds_jsonld/__init__.py  →  __version__ = "X.Y.Z"
#    • CHANGELOG.md     →  ## [X.Y.Z] — <today's date>
#    If any disagree, fix them before continuing.

# 6. CHANGELOG — verify [Unreleased] section is empty and the new version
#    section is complete with a Summary and all relevant Fixed/Added/Changed entries.

# 7. README — verify README.md reflects ALL features in this release:
#    • Test badge count matches the latest suite run.
#    • Project Status table has a row for this version.
#    • Any new user-facing features have documentation, examples, or API
#      reference in the appropriate README section.
#    • Code examples are runnable (imports exist, variables defined).
#    If any are missing, add them before continuing.
```

#### Performing the release

Only proceed here after **every pre-release check passes**.

```powershell
# 1. Merge dev into main
git checkout main
git pull origin main
git merge --no-ff dev -m "release: v<X.Y.Z>"

# 2. Tag the release (SemVer)
git tag -a v<X.Y.Z> -m "v<X.Y.Z> — <brief description>"

# 3. Push main and tags
git push origin main --tags

# 4. Return to dev
git checkout dev
```

#### Post-release

- Verify the GitHub Actions CI **and** Publish workflows pass on the tag.
- If CI fails: **do not delete the tag and retry**. Instead, fix forward:
  create a `fix/` branch on `dev`, fix the issue, and release a `PATCH+1`.

### Hotfixes (urgent production fixes)

```powershell
# Branch from main, not dev
git checkout main
git checkout -b hotfix/critical-cosmos-bug

# Fix, test, commit
git commit -m "fix(cosmos): handle null partition key"

# Merge into BOTH main and dev
git checkout main
git merge --no-ff hotfix/critical-cosmos-bug
git checkout dev
git merge --no-ff hotfix/critical-cosmos-bug

# Push both, delete hotfix branch
git push origin main dev
git branch -d hotfix/critical-cosmos-bug
git push origin --delete hotfix/critical-cosmos-bug
```

---

## Merge Strategy

- **Topic → dev:** Use `--no-ff` (no fast-forward) to preserve branch history in the graph.
- **dev → main:** Always `--no-ff` merge. Never rebase main.
- **Keeping topic branch current:** Prefer `git rebase dev` for a clean linear history on the topic branch. Use `git merge dev` if the branch is shared with others.

---

## Agent-Specific Rules

When I (the AI agent) am working on code changes:

1. **Always check the current branch** before making changes: `git branch --show-current`
2. **Never commit directly to `main` or `dev`.** Create a topic branch first.
3. **Create the topic branch from `dev`** unless it's a hotfix (then branch from `main`).
4. **Commit with Conventional Commits** format — every single time.
5. **Run tests before merging** — verify the suite passes on the topic branch.
6. **After completing a feature**, merge the topic branch into `dev`, push, and clean up.
7. **Do not push to `main`** unless the user explicitly says "release" or "merge to main".
8. **Use atomic commits** — one logical change per commit. Don't lump unrelated changes.
9. **Always push the branch** after committing so work is backed up to the remote.
10. **Include the scope** in commit messages when the change touches a specific module.

### Before every release — agent-mandatory steps

When the user says "release", "tag", "push to main", or "publish":

1. **Run `ruff check src/ tests/`** — fix any failures before proceeding.
2. **Run `ruff format --check src/ tests/`** — fix any formatting issues.
3. **Run `python -m pytest tests/ -v --tb=short`** — all tests must pass.
4. **Verify version consistency** — confirm `pyproject.toml`, `__init__.py`, and `CHANGELOG.md` all have the same version string. If they differ, ask the user which version is correct and fix all three.
5. **Confirm CHANGELOG is up to date** — the `[Unreleased]` section should be empty, and a dated `[X.Y.Z]` section must exist.
6. Only then proceed with the `dev → main` merge and tagging.

### Workflow for a typical agent task

```
git checkout dev && git pull origin dev       # sync
git checkout -b feature/my-task               # branch
# ... make changes, run tests ...
git add -A && git commit -m "feat(scope): description"
git push -u origin feature/my-task            # backup
git checkout dev && git merge --no-ff feature/my-task
git push origin dev                           # integrate
git branch -d feature/my-task                 # clean up local
git push origin --delete feature/my-task      # clean up remote
```

---

## Tags & Versioning

- Follow [SemVer 2.0](https://semver.org/): `MAJOR.MINOR.PATCH`
- Tag format: `v1.2.3`
- Tag on `main` only, after merging from `dev`
- `feat` commits → bump MINOR
- `fix` commits → bump PATCH
- `BREAKING CHANGE` → bump MAJOR
