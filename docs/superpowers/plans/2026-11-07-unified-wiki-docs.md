# Unified Wiki and Operations Docs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `reference/wiki/` plus mixed-purpose `docs/` with one navigable topical `wiki/` and a validated operations-only `docs/`, then integrate and remove `docs/learnings.md`.

**Architecture:** Build a deterministic title-to-canonical-path classifier and manifest before moving content. Use that manifest as the common interface for import, generators, recursive lookup, link rewriting, collision detection, and navigation indexes; then migrate current operational guidance separately and validate it against code. Preserve curated quest/mechanic content as canonical, merge imported facts into those pages, and keep historical plans/specs unchanged except for section labeling.

**Tech Stack:** Python 3 standard library, repository `unittest` tests, Markdown, JSON, existing `./wf` CLI and generators.

**Spec:** `docs/superpowers/specs/2026-11-07-unified-wiki-docs-design.md`

## Global Constraints

- One topical `wiki/`; no `wiki/reference/`, `wiki/imported/`, or equivalent provenance silo.
- One canonical page per subject, with curated/verified content winning collisions.
- `docs/` contains app operations, UI recognition, architecture, troubleshooting, testing, and historical engineering records only.
- Preserve Fandom/CC BY-SA attribution on imported content.
- Do not restore, overwrite, or otherwise disturb unrelated pre-existing worktree changes, including the removed global progress file, retros, routes, and media.
- Do not rewrite historical `docs/superpowers/` narratives solely to change legacy paths.
- Delete `docs/learnings.md` only after every learning ID is dispositioned and all live consumers pass validation.
- Use `apply_patch` for hand edits; migration scripts may perform reviewed bulk mechanical moves and rewrites.

## Review Focus

- Titles differing only by case, punctuation, apostrophes, or Unicode punctuation must resolve to one intentional canonical page and retain aliases.
- Multi-infobox pages must choose the most specific item category, not fall into generic `misc` merely because `[Item]` appears first.
- Curated quest content, front matter, status, briefs, and verified steps must survive regeneration byte-for-byte outside generated markers.
- Every imported page and character subpage must be indexed and searchable after nested relocation, including pages without useful infoboxes.
- Legacy-path validation must reject live references while explicitly allowing historical specs/plans to remain historical records.

---

### Task 1: Freeze the migration inventory and canonical path classifier

**Files:**
- Create: `tools/wiki_layout.py`
- Create: `tools/wiki_overrides.json`
- Create: `tools/test_wiki_layout.py`
- Create: `wiki/manifest.json` (generated fixture/output)

**Interfaces:**
- Consumes: page title, Markdown body, optional existing curated path.
- Produces: `classify_page(title: str, text: str) -> str`, `normalized_title(title: str) -> str`, and `build_manifest(imported_dir: str, curated_roots: list[str]) -> dict` whose entries contain `title`, `source_path`, `canonical_path`, `aliases`, `kind`, and `source`.

- [ ] **Step 1: Write classifier tests for representative page kinds and collision cases**

  Cover character overview/subpages, quest, location, business, specific item plus generic item, mechanic/story page, no-infobox page, straight/curly apostrophes, punctuation-only title variants, and curated quest/mechanic precedence. Assert canonical paths and aliases.

- [ ] **Step 2: Run the focused tests and verify they fail**

  Run: `.venv/bin/python tools/test_wiki_layout.py`

  Expected: FAIL because `tools/wiki_layout.py` does not exist.

- [ ] **Step 3: Implement the classifier, overrides, and manifest builder**

  Use specific infobox precedence, character `__Suffix` parsing, normalized collision checks, and explicit overrides for ambiguous/no-infobox pages. Reject duplicate canonical paths unless the manifest explicitly identifies a curated/imported merge.

- [ ] **Step 4: Generate the complete manifest without moving files**

  Run: `.venv/bin/python tools/wiki_layout.py manifest reference/wiki wiki/manifest.json`

  Expected: all 1,190 imported pages appear exactly once; no unresolved collision or unclassified page is silently accepted.

- [ ] **Step 5: Run classifier tests and inspect category counts**

  Run: `.venv/bin/python tools/test_wiki_layout.py`

  Expected: PASS; printed/audited counts show every proposed first-level Wiki section is populated and no catch-all dominates due to a classifier bug.

- [ ] **Step 6: Commit the classifier gate**

  ```bash
  git add tools/wiki_layout.py tools/wiki_overrides.json tools/test_wiki_layout.py wiki/manifest.json
  git commit -m "build: classify unified wiki content"
  ```

### Task 2: Materialize the unified topical Wiki and navigation

**Files:**
- Create: `tools/migrate_wiki.py`
- Create: `tools/test_migrate_wiki.py`
- Create: `wiki/INDEX.md`
- Create: `wiki/ATTRIBUTION.md`
- Create/Move: `wiki/mechanics/**`, `wiki/tips/**`, `wiki/quests/**`, `wiki/characters/**`, `wiki/places/**`, `wiki/businesses/**`, `wiki/items/**`, `wiki/story/**`
- Delete after successful migration: `reference/wiki/**`, `docs/mechanics/**`, `docs/quests/**`, `docs/world/**`, `docs/tips.md`

**Interfaces:**
- Consumes: `wiki/manifest.json`, existing imported pages, and curated game-knowledge pages.
- Produces: `materialize(manifest_path: str, root: str, dry_run: bool = True) -> MigrationReport` with moved/merged/indexed/unresolved counts; one canonical Markdown file per manifest subject.

- [ ] **Step 1: Write migration tests in a temporary fixture tree**

  Assert dry-run writes nothing; imported-only pages move to classified paths; curated/imported collisions produce one page with preserved curated regions and source-marked imported facts; character subpages nest correctly; section indexes link every output; attribution is present; rerunning is idempotent.

- [ ] **Step 2: Run migration tests and verify they fail**

  Run: `.venv/bin/python tools/test_migrate_wiki.py`

  Expected: FAIL because the migration implementation is missing.

- [ ] **Step 3: Implement migration and index generation**

  Preserve existing quest front matter and verified sections. Generate small router indexes at the root, each first-level section, each questline, each item category, and the character directory. Add summary/source metadata to imported pages without rewriting their substantive content.

- [ ] **Step 4: Review a dry-run against the real tree**

  Run: `.venv/bin/python tools/migrate_wiki.py --dry-run --manifest wiki/manifest.json`

  Expected: 1,190 imported inputs accounted for; curated inputs accounted for; zero unresolved collisions, overwrites, or outputs outside `wiki/`.

- [ ] **Step 5: Materialize the migration**

  Run: `.venv/bin/python tools/migrate_wiki.py --apply --manifest wiki/manifest.json`

  Expected: the topical Wiki exists; source game-knowledge trees are gone only where every input has a canonical output.

- [ ] **Step 6: Run migration tests twice to prove idempotence**

  Run: `.venv/bin/python tools/test_migrate_wiki.py && .venv/bin/python tools/test_migrate_wiki.py`

  Expected: PASS both times.

- [ ] **Step 7: Commit the unified Wiki**

  ```bash
  git add tools/migrate_wiki.py tools/test_migrate_wiki.py wiki reference/wiki docs/mechanics docs/quests docs/world docs/tips.md
  git commit -m "docs: create unified topical game wiki"
  ```

### Task 3: Move generators and CLI consumers onto the manifest

**Files:**
- Modify: `tools/build_reference.py`
- Modify: `tools/gen_quests.py`
- Modify: `tools/gen_world_tables.py`
- Modify: `tools/wf.py`
- Create: `tools/test_wiki_cli.py`
- Modify: relevant existing tests that contain old fixture paths

**Interfaces:**
- Consumes: `wiki/manifest.json` via `load_manifest(root: str) -> dict` from `tools/wiki_layout.py`.
- Produces: recursive canonical `wiki()` results, recursive globally unique `tips()` rows, quest generation under `wiki/quests/`, and aggregate indexes within the relevant Wiki sections.

- [ ] **Step 1: Write failing generator and CLI tests**

  Assert exact-title lookup, alias lookup, nested content lookup, `--show`, representative mechanic/quest/character/item results, recursive tips lookup, unique tip IDs, quest preservation outside generated markers, and world index generation from manifest paths.

- [ ] **Step 2: Run the focused tests and verify legacy assumptions fail**

  Run: `.venv/bin/python tools/test_wiki_cli.py`

  Expected: FAIL because current code scans flat `reference/wiki/` and `docs/tips.md`.

- [ ] **Step 3: Update importer and generators**

  Make `build_reference.py` classify cleaned pages and update the manifest; make quest/world generators resolve titles through the manifest and write canonical Wiki files/indexes. Preserve the existing marker contract for hand-maintained quest content.

- [ ] **Step 4: Update `./wf wiki` and `./wf tips`**

  Search nested Wiki pages through the manifest, rank exact canonical/alias titles before partial titles and content, print canonical paths, and read all tip tables under `wiki/tips/` while rejecting duplicate tip IDs.

- [ ] **Step 5: Run generators and prove stable output**

  Run: `python3 -I tools/gen_quests.py`

  Run: `python3 -I tools/gen_world_tables.py`

  Run both again and verify `git diff` has no second-run changes.

- [ ] **Step 6: Run focused and relevant regression tests**

  Run: `.venv/bin/python tools/test_wiki_layout.py && .venv/bin/python tools/test_migrate_wiki.py && .venv/bin/python tools/test_wiki_cli.py && .venv/bin/python tools/test_brief.py && .venv/bin/python tools/test_plan.py`

  Expected: PASS.

- [ ] **Step 7: Commit consumer migration**

  ```bash
  git add tools wiki
  git commit -m "refactor: use canonical wiki manifest"
  ```

### Task 4: Reorganize and validate operations documentation

**Files:**
- Rewrite: `docs/INDEX.md`
- Move: `docs/actions.md` -> `docs/operations/actions.md`
- Move: `docs/routines.md` -> `docs/operations/routines.md`
- Move: `docs/agent-runs.md` -> `docs/testing/run-logging.md`
- Move: `docs/self-improvement.md` -> `docs/architecture/self-improvement.md`
- Retain and update: `docs/ui/**`
- Create: `docs/operations/INDEX.md`
- Create: `docs/architecture/INDEX.md`
- Create: `docs/testing/INDEX.md`
- Create: `docs/troubleshooting/INDEX.md`
- Create: `tools/audit_operations_docs.py`
- Create: `tools/test_operations_docs.py`

**Interfaces:**
- Consumes: live CLI parser/help, `tools/game/goals.json`, current module/file names, and current operations Markdown.
- Produces: `audit_operations_docs(root: str) -> list[str]`, where an empty list means documented commands, paths, modes, fields, and goal names exist and disabled mechanisms are not presented as current.

- [ ] **Step 1: Write failing audit tests for known stale and valid claims**

  Test command extraction, file/module references, goal names, disabled keyboard navigation wording, missing index entries, and the historical-spec exclusion.

- [ ] **Step 2: Run the audit tests and verify they fail on the current mixed layout**

  Run: `.venv/bin/python tools/test_operations_docs.py`

  Expected: FAIL with old paths and at least one stale/current-boundary violation.

- [ ] **Step 3: Move and rewrite current operations pages**

  Keep command recipes, verification signals, coordinates, machine-recognition rules, and safe exits in Docs. Replace duplicated game rules with links to canonical Wiki pages. Label `docs/superpowers/` as historical engineering records from the Docs router.

- [ ] **Step 4: Validate every documented command and code claim**

  Compare extracted commands/options with `./wf --help`/parser definitions, goals with `tools/game/goals.json`, and named files/symbols with the current tree. Correct current pages rather than weakening the audit.

- [ ] **Step 5: Run operations tests and inspect the docs router**

  Run: `.venv/bin/python tools/test_operations_docs.py`

  Expected: PASS; `docs/INDEX.md` routes only app-operation/development needs and points game questions to `../wiki/INDEX.md`.

- [ ] **Step 6: Commit operations documentation**

  ```bash
  git add docs tools/audit_operations_docs.py tools/test_operations_docs.py
  git commit -m "docs: separate app operations from game knowledge"
  ```

### Task 5: Integrate every learning and remove the ledger

**Files:**
- Create temporarily: `tools/learning_disposition.json`
- Create: `tools/audit_learnings.py`
- Create: `tools/test_audit_learnings.py`
- Modify: relevant `wiki/**` and `docs/**` canonical pages
- Delete: `docs/learnings.md`
- Delete after proof: `tools/learning_disposition.json` (unless retained as clearly labeled migration evidence)

**Interfaces:**
- Consumes: parsed `L<number>` entries and their section/expected/actual/now/updated fields.
- Produces: `audit_dispositions(learnings_path: str, dispositions_path: str, root: str) -> list[str]`; every ID must map to existing canonical destinations with status `integrated`, `superseded`, or `historical` and a concise rationale.

- [ ] **Step 1: Write tests that reject missing, duplicate, invalid, or destination-less learning dispositions**

  Include sparse/non-monotonic IDs and multiple destinations. Assert operational destinations stay under `docs/` and game destinations stay under `wiki/`.

- [ ] **Step 2: Run the tests and verify they fail without the audit implementation**

  Run: `.venv/bin/python tools/test_audit_learnings.py`

  Expected: FAIL.

- [ ] **Step 3: Implement the audit and build the complete disposition manifest**

  Parse IDs from the original ledger, record every one exactly once, and point each durable rule to its canonical topic. Use `superseded` only when the current correction already exists; use `historical` only for non-current run/process observations that are intentionally preserved elsewhere or no longer actionable.

- [ ] **Step 4: Integrate missing durable conclusions into canonical pages**

  Write conclusions as current topical guidance, not chronological anecdotes. Put game behavior/strategy in Wiki; permissions, capture/input, CLI/runtime evidence, automation laws, recovery, and testing in Docs. Retain a short trap rationale only when it helps prevent recurrence.

- [ ] **Step 5: Run the disposition and operations audits before deletion**

  Run: `.venv/bin/python tools/test_audit_learnings.py && .venv/bin/python tools/audit_learnings.py && .venv/bin/python tools/test_operations_docs.py`

  Expected: PASS; every learning ID accounted for and every destination exists.

- [ ] **Step 6: Delete `docs/learnings.md` and prove no live dependency remains**

  Remove the ledger with `apply_patch`, rerun the audit in post-migration mode against the saved disposition data, then remove the temporary manifest if the test embeds/retains enough migration evidence.

- [ ] **Step 7: Commit learning integration**

  ```bash
  git add wiki docs tools/audit_learnings.py tools/test_audit_learnings.py tools/learning_disposition.json
  git commit -m "docs: integrate verified learnings by topic"
  ```

### Task 6: Rewrite live repository references and agent instructions

**Files:**
- Modify: `AGENTS.md`
- Modify: `README.md`
- Modify: `.claude/agents/*.md`
- Modify: `.claude/skills/wylde-*/SKILL.md`
- Modify: relevant `.claude/skills/game-onboarding/**`
- Modify: live `tools/**`, `tools/bench/**`, JSON templates, and tests containing legacy paths
- Create: `tools/audit_knowledge_tree.py`
- Create: `tools/test_knowledge_tree.py`

**Interfaces:**
- Consumes: the repository tree, manifest, and an explicit historical-path exclusion list.
- Produces: `audit_tree(root: str) -> list[str]` covering broken local Markdown links, unindexed Wiki pages, duplicate normalized subjects, missing manifest destinations, current references to legacy paths, and disallowed game content under Docs.

- [ ] **Step 1: Write failing repository-audit tests**

  Use fixture trees to prove broken links, unindexed pages, duplicate subjects, missing manifest targets, and live `reference/wiki`/`docs/learnings.md`/old game-doc references fail while historical `docs/superpowers/` prose is excluded.

- [ ] **Step 2: Run the audit tests and verify they fail**

  Run: `.venv/bin/python tools/test_knowledge_tree.py`

  Expected: FAIL before the audit exists and/or while live legacy references remain.

- [ ] **Step 3: Update current instructions and templates**

  Make `AGENTS.md` and README describe the Wiki/Docs boundary and progressive routers. Update quest/runner/supervisor manifests, benchmarks, onboarding templates, and live code/tests to canonical paths. Preserve unrelated user deletions.

- [ ] **Step 4: Implement and run the repository audit**

  Run: `.venv/bin/python tools/test_knowledge_tree.py && .venv/bin/python tools/audit_knowledge_tree.py`

  Expected: PASS with zero live legacy references, broken links, duplicate canonical subjects, missing destinations, or unindexed Wiki pages.

- [ ] **Step 5: Commit live-reference updates**

  ```bash
  git add AGENTS.md README.md .claude tools wiki docs
  git commit -m "docs: route agents through unified knowledge tree"
  ```

### Task 7: Full regeneration, verification, and migration cleanup

**Files:**
- Modify only as produced by deterministic generators/audits.
- Delete: empty `reference/` directory if no non-Wiki content remains.

**Interfaces:**
- Consumes: all prior task outputs.
- Produces: a clean, reproducible unified knowledge tree with passing tests and a migration summary.

- [ ] **Step 1: Run all knowledge-tree generators twice**

  Run: `python3 -I tools/gen_quests.py && python3 -I tools/gen_world_tables.py`

  Repeat and verify the second run creates no diff.

- [ ] **Step 2: Run all focused migration/documentation audits**

  Run: `.venv/bin/python tools/test_wiki_layout.py && .venv/bin/python tools/test_migrate_wiki.py && .venv/bin/python tools/test_wiki_cli.py && .venv/bin/python tools/test_operations_docs.py && .venv/bin/python tools/test_audit_learnings.py && .venv/bin/python tools/test_knowledge_tree.py`

  Expected: PASS.

- [ ] **Step 3: Run the repository regression suite**

  Run: `for t in tools/test_*.py; do .venv/bin/python "$t" || exit 1; done`

  Expected: every test passes; any environment-only test is explicitly identified rather than silently skipped.

- [ ] **Step 4: Exercise representative CLI lookups**

  Run `./wf wiki` searches for one mechanic, quest, character alias, character schedule, place, business, and item; run `./wf tips` for representative tags. Confirm canonical nested paths and readable output.

- [ ] **Step 5: Manually inspect navigation and attribution samples**

  Read `wiki/INDEX.md`, `docs/INDEX.md`, one page from every Wiki section, a merged quest, a character directory, and `wiki/ATTRIBUTION.md`. Confirm summaries, provenance, and back-links make browsing understandable without knowing the old layout.

- [ ] **Step 6: Review the final diff against the initial dirty-worktree inventory**

  Confirm pre-existing deletions/modifications remain user-owned and were not restored or folded into commits. Confirm `reference/wiki/` and `docs/learnings.md` are gone, with no empty obsolete directories tracked.

- [ ] **Step 7: Commit final deterministic outputs and fixes**

  ```bash
  git add wiki docs tools AGENTS.md README.md .claude reference
  git commit -m "chore: verify unified wiki migration"
  ```
