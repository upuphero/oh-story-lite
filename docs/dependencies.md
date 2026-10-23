# M0 dependency audit

Audit baseline: upstream `v0.9.0`, resolved commit
`74080143dd1ac9a39a930fafd99a0dbbe61b946a`. The 102 Skill files and original
LICENSE are copied byte for byte. Upstream's `.agents/skills` alias and all
other subtrees are excluded, not followed during archive extraction.

## Bundled hard dependencies

| Entry point | Required assets / behavior | Evidence in local mirror |
|---|---|---|
| `story-long-write/SKILL.md` | Scenario-specific workflow references; writing requires full pre-read and valid tracking | `references/workflow-chapter.md`, `workflow-daily.md`, `workflow-revision.md` |
| `build_architect_brief.py` | `outline_view.py`; stage-specific references and conditional method documents | `scripts/dependencies.json` explicitly lists the references; rules-only world/volume/outline CLI checks |
| `build_writer_prompt.py` | `outline_view.py`, author-memory query, genre-card glob; private outline/context inputs | `author_memory_commit.py`, `references/genre-prose-cards/**`; missing-input rejection and genre-card smoke checks |
| `tracking_commit.py` | Dynamically loads `wordcount_core.py`; writes private tracking state and derived views | Synthetic init/check smoke test in a temporary project |
| `storyctl.py` | Dynamically loads wordcount/tracking modules; invokes Node pattern/degeneration/copy/punctuation checks | Explicit dependency manifest and checker-chain smoke test |
| `check-ai-patterns.js`, `normalize-punctuation.js` | Relative Node module `style-whitelist.js`; Node built-ins `fs`, `path` | Static import checks; positive/negative detector fixtures and runtime chain |
| `story-deslop/SKILL.md` | Style resolution, three-layer methods, original backup and two deterministic checks | All eight Markdown files and four JavaScript files included; detectors checked in both Skills |

Python imports observed in these scripts are from the standard library or
bundled local modules. Node imports observed are built-ins or bundled relative
modules. No pip/npm installation is needed for the checked paths.

## Optional assets and runtime capabilities

`check-outline-contract.js` lists both `workflow-outline.md` and
`outline-reverse-rules.md` as possible report sources, then filters using
`existsSync`. The latter does not exist in this upstream Skill. The former is
bundled. This exact missing asset is allowlisted with an explanation, reported
as a warning and exercised through an invalid-outline check. It is not silently
replaced or downloaded from a third Skill.

The upstream text mentions `story-setup`, `story-import`, `story-review`,
`story-long-analyze`, `story-long-scan`, and `story-short-write`. These routes are
not distributed. They are reviewed documentation/workflow routes, not evidence
that this mirror provides those capabilities. In particular, migration of an
existing book with missing standard tracking can require `story-import`; that
workflow is unavailable here. New-book tracking initialization instructions
are bundled in `references/tracking-initialization.md`.

`narrative-writer`, `story-architect`, `story-explorer`, `story-continuity`,
`story-researcher` and other professional Agents are optional runtime
capabilities. The upstream workflows document direct execution when unavailable.
The mirror does not install them or claim that DSH roles/hooks are present.
The upstream suggestion to run `/story-setup` is also not provided by this mirror.

## Private project inputs

Chapter writing still consumes the author's volume/scene outline, settings,
style and tracking state. Missing inputs must be reported and repaired according
to the workflow. Bundling these two Skills does not remove those prerequisites.
Author memory, `.story/work`, tracking state, backups and generated
`writer_prompt.md` belong to private projects, never this distribution.

## Validation limits and update policy

`scripts/validate_references.py` checks relative Markdown links, reference-style
links, explicit asset paths, method filenames, Python imports, Node `require`
calls and literal script dependencies. `scripts/dependencies.json` records the
reviewed dynamic dependency graph. New packages, missing hard assets, escaping
paths or unreviewed Skill routes fail the check and require manual adaptation.
The scanner is conservative and may need a reviewed adjustment when upstream
changes its syntax; it is not a full Markdown/JavaScript parser or a proof of
all runtime-generated paths. Smoke tests exercise selected dynamic paths.

Byte manifests catch accidental edits/deletions and CRLF conversion, but cannot
authenticate a maliciously regenerated lock or an arbitrary offline archive.
The normal sync path resolves the public GitHub release tag to a commit and
downloads from that fixed commit. Updates must later be reviewed before merge.

No DSH discovery, provider connection, end-to-end model writing, literary
quality or native Role/Hook compatibility has been tested during M0～M2.

Follow-up on 2026-10-23: installed DSH discovery/loading and same-layer name
precedence were exercised in a minimal isolated Context. Unknown professional
presets return not-found; the loaded Skills' solo/direct instructions are not
automatic DSH routing. No model was run. See `docs/dsh-discovery.md`.
