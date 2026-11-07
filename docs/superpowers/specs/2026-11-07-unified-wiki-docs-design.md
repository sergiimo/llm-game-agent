# Unified Wiki and Operations Docs Design

> **Summary:** Replace the split curated-docs/fan-mirror layout with one topical `wiki/`, keep `docs/` for operating and developing the game-playing app, distribute every durable learning to its canonical page, and remove `docs/learnings.md`.

## Intent

Make repository knowledge easy to navigate by subject instead of by origin. Someone asking about Wylde Flowers should start in `wiki/`; someone operating, testing, troubleshooting, or changing this app should start in `docs/`. The distinction is about the reader's task, not whether a fact came from the fan wiki, a live play session, or code.

## Goals

- Put mechanics, strategy, quests, characters, places, businesses, and items in one joint `wiki/` with no separate raw-reference area.
- Give every page a discoverable topical home and provide small indexes that support progressive loading.
- Preserve both imported fan-wiki facts and locally verified knowledge, while making trust/provenance visible on the page.
- Keep app operation, UI automation, runtime evidence, troubleshooting, testing, and engineering design in `docs/`.
- Validate operational documentation against the current command surface and implementation, correcting stale claims.
- Integrate all useful facts from `docs/learnings.md` into canonical Wiki or operations pages and delete the ledger.
- Update code, generators, tests, skills, README, and `AGENTS.md` so the new layout is the only supported layout.

## Non-goals

- Re-fetch or substantively rewrite the upstream fan-wiki corpus.
- Change gameplay automation behavior except where a path or documentation lookup must change.
- Restore files already deleted in the user's dirty worktree.
- Preserve old paths with duplicate compatibility copies; links and consumers will move together.

## Anti-goals

- A `wiki/reference/`, `wiki/imported/`, or equivalent provenance silo.
- A 1,190-file flat directory with no useful navigation.
- Two canonical pages for the same quest, character, item, place, or mechanic.
- Moving stale operational instructions without checking them against code and CLI behavior.
- Keeping `learnings.md` under a new name as another chronological dumping ground.

## Chosen information architecture

```text
wiki/
  INDEX.md
  mechanics/                 game rules and systems
  tips/                      strategy pages grouped by activity
  quests/<questline>/        one canonical page per quest
  characters/<character>/    overview plus dialogue/schedule/event subpages
  places/                    locations and area pages
  businesses/                shops, services, inventories, and hours
  items/
    crops/ seeds/ forage/ fish/ food/
    ingredients/ potions/ tools/ workstations/ books/ misc/
  story/                     festivals, coven/story concepts, achievements

docs/
  INDEX.md
  operations/                setup, controls, commands, actions, routines, play workflow
  ui/                        screen recognition and safe interaction procedures
  architecture/              runtime/world/object/self-improvement design docs
  troubleshooting/           current symptom -> diagnosis -> recovery guidance
  testing/                   evals, benchmarks, run logging, validation
  superpowers/               historical design specs and implementation plans
```

The exact folder for a fan-wiki page is derived from its infobox/type and a small explicit override map for ambiguous pages. A generated manifest maps every original fan-wiki title to exactly one canonical path. Classification, link rewriting, aliases, duplicate detection, generators, and search consume that manifest rather than independently guessing paths. Filename matching is case-insensitive and punctuation-normalized only for collision detection; the manifest resolves punctuation and title variants safely.

## Canonical-page and merge rules

1. A subject has one canonical page, regardless of source.
2. Existing curated quest pages remain canonical because they contain status, actionable briefs, and verified steps. Matching imported quest content is merged into their generated/wiki-facts section; the standalone imported duplicate disappears.
3. Existing curated mechanic pages remain canonical. Relevant imported general pages are merged or linked as supporting topic pages in the same section.
4. Character overview, schedule, dialogue, conversation, and event material becomes a character directory rather than unrelated top-level files.
5. Item pages are categorized by their primary infobox. Aggregate tables become section indexes, generated from those pages.
6. Pages that cannot be confidently classified go to `wiki/story/uncategorized/` temporarily, are listed in its index, and fail a migration audit until explicitly accepted or classified. There is no hidden fallback corpus.
7. Every page starts with a short summary and source/status markers where appropriate: fan-wiki-derived, verified in-game with date, user-provided, or uncertain.
8. Fan-wiki-derived content retains its Fandom/CC BY-SA attribution through a corpus-level notice linked from `wiki/INDEX.md` and source metadata on imported pages.

## Navigation

- `wiki/INDEX.md` is a short need-to-section router, not a giant page list.
- Each first-level section has an `INDEX.md` with grouped links and generated counts.
- Large sections add second-level indexes: questline indexes, character directory indexes, and item-category indexes.
- `./wf wiki <term>` searches all of `wiki/`, ranks exact title and curated/verified matches first, and prints the canonical path.
- `./wf tips <tags>` reads the topical pages under `wiki/tips/` recursively; tip IDs remain globally unique.
- Relative Markdown links replace prose-only path references where practical.
- A repository validation command checks local Markdown links, legacy path strings, duplicate normalized titles, unindexed pages, and empty sections.

## Wiki generation and maintenance

- `tools/build_reference.py` becomes the importer/normalizer for the unified Wiki. It writes classified pages into topical locations rather than recreating `reference/wiki/`, and emits the original-title-to-canonical-path manifest.
- `tools/gen_world_tables.py` reads topical Wiki pages and writes aggregate indexes inside `wiki/`.
- `tools/gen_quests.py` reads imported quest facts and preserves locally maintained front matter and verified steps in canonical quest files.
- Classification logic and explicit overrides live in code/data with tests so regeneration is deterministic.
- Classification tests explicitly cover multi-infobox pages, generic `Item` plus specific types, character subpages, punctuation/title variants, and pages without useful infoboxes.
- Generated files name their generator and source inputs. Hand-maintained sections remain delimited and preserved across regeneration.

## Operations documentation audit

Operational pages are validated against the current repository rather than assumed correct:

- Compare documented `./wf` commands and options with the current CLI parser/help and goal registry.
- Compare named modules, files, log fields, screen modes, and recovery commands with current code.
- Mark historical material in `docs/superpowers/` as historical; do not rewrite old decisions as current instructions.
- Remove instructions for disabled keyboard navigation and other superseded mechanisms from current pages, retaining history only where it explains a current constraint.
- Consolidate setup and recovery guidance so `AGENTS.md` points to canonical operations/troubleshooting pages instead of line numbers in a learning ledger.
- Keep `docs/operations/actions.md` focused on app command recipes, expected signals, and recovery. Reusable game rules link to Wiki mechanics instead of being duplicated.
- Keep `docs/ui/` focused on machine recognition, virtual coordinates, commands, and safe exits. Player-facing rules belong in Wiki mechanics.

## Integrating `docs/learnings.md`

The ledger is decomposed entry by entry:

- Game rules, mechanics, strategy, world facts, quest facts, and player-facing game UI behavior go to the relevant `wiki/` page.
- App setup, permissions, capture/input behavior, CLI behavior, runtime evidence, automation laws, and recovery procedures go to the relevant `docs/` operations, UI, architecture, testing, or troubleshooting page.
- Superseded observations are omitted from current guidance unless the correction explains an important trap; in that case only the corrected rule and concise rationale remain.
- The migration audit records every learning ID as integrated, superseded, or intentionally historical before `docs/learnings.md` is deleted.
- The learning-disposition manifest is temporary, machine-checkable migration evidence. Remove it after validation or retain it only as explicitly labeled migration evidence, never as a replacement chronological ledger.

This split follows the requested Wiki/Docs audience boundary while still fully integrating and removing the standalone ledger.

## Migration and compatibility

- Move files with history-preserving filesystem renames where possible.
- Rewrite all live repository references from `reference/wiki/...` and moved `docs/...` paths, including Python, JSON, Markdown, skills, agents, tests, and README/AGENTS instructions.
- Historical specs/plans remain historical records and may retain old paths in their narrative. Their section index labels them historical, and the legacy-path audit explicitly excludes them.
- Do not touch unrelated existing deletions or modifications.
- The migration is complete only when no live code, current instructions, skills, tests, templates, or current documentation references `reference/wiki`, `docs/learnings.md`, or old game-knowledge paths under `docs/`.

## Validation

- Deterministic migration/classification tests cover every imported page exactly once and verify the complete title-to-path manifest.
- Quest and world generators run successfully and are idempotent.
- CLI tests prove `./wf wiki` finds representative mechanics, quests, characters, and items in their canonical locations.
- A link/index audit finds no broken internal Markdown links, unindexed Wiki pages, duplicate normalized subjects, or legacy live paths.
- Existing relevant unit tests pass.
- A final manual sample checks one mechanic, tip, quest, character with subpages, place, business, and each item category for readable navigation and provenance.

## Approaches considered

1. **Unified topical Wiki (chosen).** Mix imported and verified knowledge by subject, merging collisions into canonical pages. Best navigation and directly matches the request; requires a careful classifier and merge audit.
2. **Curated Wiki plus `wiki/reference/`.** Easiest and safest migration, but preserves the origin-based split the user explicitly rejected.
3. **Flat unified Wiki.** Minimal tooling change, but 1,190+ pages make browsing poor and collisions ambiguous.

## Builder calls still allowed

- Choose exact slugs and the smallest practical explicit classification override format.
- Adjust second-level categories when corpus counts show a proposed category is empty or excessively broad.
- Keep historical specs/plans at their existing paths if moving them would create disproportionate churn; `docs/INDEX.md` must still label them as historical engineering material.
