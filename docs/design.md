# code-story — design decisions

A skill that turns a code change into an immersive, scroll-driven HTML **story** that follows the flow of execution/data, with every code line rendered from git. Theme: **Black Liquid Glass**.

Status: design grilling in progress. Decisions below are settled; open questions live at the bottom.

## Glossary

- **Story** — the generated HTML: an ordered walk through the change, following execution/data/app flow.
- **Chapter** — one stop on that walk (e.g. "token arrives", "middleware validates", "audit write").
- **Frame** — a block of real code inside a chapter: a **diff frame** (changed lines) or a **context frame** (unchanged code at a pinned commit).
- **Index** — the build's first pass: every change listed with a stable id, enclosing symbol, size and content hash.
- **Coverage** — the deterministic guarantee that every change in the diff appears somewhere in the story.
- **Black Liquid Glass** — the design system (tokens, components) the story is built with; reusable beyond this skill.

## Decisions

### D1 — v1 scope: review stories
v1 covers diff-based stories: a PR from a link, or the current branch/session changes. Both are "base...head diff + intent". The **tour** mode (D39) came after: no diff, a walkthrough of how the app works.

### D2 — No hallucinated code
The model never types code into the output. It references code by anchor; a script renders every code line from git. A deterministic **coverage check** verifies all changes are shown.

### D3 — Stack
Single self-contained HTML file, plain HTML/CSS + small vanilla JS, no framework, works offline from disk. Built by a Python script (build-time syntax highlighting via Pygments; intra-line diff tokenised, applied only to paired −/+ lines above a similarity threshold, to avoid confetti).
The HTML is **not locked**: the model has creative room to add extra touches (custom blocks, illustrations, layout flourishes) on top of the components — only code-as-evidence is reserved for the renderer.

### D3a — Code colours
Code uses GitHub Dark's token colours by default, chosen for familiarity over the page's own Glass palette. The colours come from Pygments' `github-dark` style, generated at build time and scoped to `body[data-syn]`. The theme's background is dropped, so the glass panels and diff tints stay the page's own. Readers can switch with `t` (and `shift+t`) or from the help sheet, across 12 dark Pygments themes and Glass. The choice is remembered per browser.

### D4 — Layout: prototype-driven
Decide after seeing prototypes (see D21).

### D5 — Context is first-class; the model owns the narrative
The model has full freedom to construct the story: choose order, pull in unchanged context (callers, consumers, existing infra) as much as a first-time reader needs. Determinism applies only to (a) code text comes from git, (b) every change is shown. Context frames are visibly distinct from diff frames.

### D6 — Findings: additive, optional
Minimum: the story is a reading aid. Optionally it carries annotations (notes/questions/findings/mismatches) near the code, behind a show/hide toggle. The skill is **purely additive**: whatever the calling workflow prints in chat stays in chat; the story never replaces it. The user's PR-review routine will call this skill as its final step.

### D7 — No repo acquisition
The skill is visualisation only. It does not clone, checkout, or create worktrees; the caller (user, routine, agent) prepares the code.

### D8 — Naming & home
Skill and repo: `code-story`, standalone, so it can be public and shared with the team. Design system: **Black Liquid Glass**.

### D9 — Prototypes before engine
Several design prototypes built from the real code of one PR in a private repo, chosen from before building the engine. Fable 5.1 (high) and Codex (astra) reviewed the plan; their valuable ideas are folded into D16–D22.

### D10 — Authoring format: Markdown + directives
The model writes `story.md`: prose plus code directives that reference the index (D17). Raw HTML/SVG is allowed anywhere for creative touches. The build expands directives into real code.

### D11 — Light guardrail on hand-typed code
Real code enters only through directives. Hand-written multi-line code in free HTML triggers a build **warning**. Pseudo-code is allowed as a labelled `:::sketch`. Every rendered frame carries a provenance stamp (`path @ sha · L40–62 ↗`), so free HTML can't pass for evidence. The guardrail must never constrain the design or UX.

### D12 — Coverage: line-level, strict, no bloat
Every meaningful added/removed line must appear in at least one frame (one hunk may be split across chapters; repeats allowed). Unplaced lines **fail** the build with a message naming them and suggesting the appendix if irrelevant to the story. Nothing is auto-dumped; no placement report is rendered into the story. Refinements in D19.

### D13 — "Not in story" bucket
Tests, lockfiles, generated files are excluded from **coverage** (not from the story), listed at the end, collapsed, with per-file expand to the real diff. Usually tests belong there; the model may still pull a test or lockfile change into a chapter as evidence when it genuinely helps. Default globs (incl. `.terraform.lock.hcl`, `uv.lock`) decide; the model may override with a reason. Terraform and docs are not excluded by default.

### D14 — Input contract
Input: a local git repo, a base, and a head (commit or working tree). Never mutates the working tree. A PR link is used via `gh` only for intent (title, body, base ref). If the PR head isn't available locally, the skill stops and says so. Pinning details in D18.

### D15 — Output location: one folder per story
Default home: `~/.code-story/<owner>/<repo>/<pr-N | branch>/` holding `story.md`, `index.json`, `story.html`, so a rebuild after a push finds the previous story (D22d). `--out` overrides. Not an artifact store: no cleanup logic. The path is printed in chat and the file opened in the browser.

### D16 — Prose faithfulness: guidance + verification pass
Misinterpretation can't be eliminated with agents; aim for faithful, not perfect.
- Guidance: consequential claims sit next to the code that backs them; code dominates, prose stays lean. Don't pollute the story with callouts.
- `:::mismatch` callout for real contradictions between PR description, docs, code and tests (e.g. a description says `sub`, the code reads `claims.user_id`). Part of the annotation layer (D6).
- Before showing the story to the user, a **verification pass** runs once (no loop): a fresh, read-only reviewer (subagent where the harness has one, inline otherwise) gets the built story, the index and the repo, and checks: prose claims vs adjacent code; important flows or side effects missing or misrepresented; padding to cut. Coverage is not its job (the build checks it).
- The reviewer can be wrong: the **authoring model verifies every reviewer claim** against the code before acting on it; it stays responsible for the story.
- **Prose quality, conditional**: if the user has skills aimed at how AI-written text should read (e.g. a humanizer-style skill, or prose rules in their AGENTS.md/CLAUDE.md), the authoring model loads them before it writes any prose, and the reviewer reviews the prose against them. Discovered from the available skills and instructions, never hard-coded to a specific skill name. SKILL.md says this up front, in the authoring steps, not only in the review step.

### D17 — Anchors: two-pass index with stable ids
1. `index` emits every change with a stable id, enclosing symbol, size, content hash (e.g. `src/auth.py#h4 · get_current_user_id · +18/−3`). The model plans from it and opens only the hunks it needs (context budget for big PRs).
2. Directives reference hunk ids (sub-hunk via hunk-relative offsets). Context frames reference `path@base|head` + symbol or range. Hash mismatch fails the build; anchors are never silently relocated.

### D18 — Pinned comparison
Diff against the merge-base (`base...head`), like GitHub. Header shows base, head and merge-base SHAs. A commit head is read from git objects only, never disk (a dirty clone must not leak in). Working-tree head = snapshot at index time: staged, unstaged and untracked non-ignored files; changes between index and build fail the build.

### D19 — Coverage refinements
- Auto-covered once the file is referenced: blank lines, trailing-whitespace edits of a line that stays in place, and hunks that only add, drop or reorder whole import statements. Indentation changes and edited imports stay strict: in Python or YAML they change behaviour.
- Ripples (same mechanical rename at many sites) render as one frame + expandable "N more sites".
- Markdown and whole-file add/delete covered at file level.
- Renames, binaries, mode changes, symlinks: explicit change records, covered only when placed.
- Everything else stays strict at line level.

### D20 — Storytelling: guidance, not rules
The skill ships **guidance** (principles and things worth considering), never a step-by-step recipe; models are getting better and over-specific rules make stories worse. Guidance themes: pick the spine from the flow that first hits changed behaviour; show config where it's read and infra where it's consumed; keep startup, request and deploy concerns distinct; context one hop out (who calls, what consumes, where a value comes from); failure paths near their decision point; collapse ripples; explain deliberate leftovers; note mechanisms that live outside the repo; flag symlinked files whose one diff changes several places.

### D21 — Prototypes to build
All from that PR's real code, all Black Liquid Glass:
- **P1 · Scroll + graph map** — single column, floating vertical flow graph tracking position.
- **P2 · Evidence lane** — spine in the centre; a right lane with supporting pieces (terraform, env, fixture) connected to the exact line they support.
- **P3 · Branch lanes** — like P1, failure paths open sideways at their decision point, with a return link.
- **Trace layer** on all three — click a changed identifier (`user_id`) and every frame using it lights up; the map becomes a heatmap of its journey.

Canvas and deck dropped (both peers: hostile to reading/comparing diffs). Design rule: glass on navigation chrome; code surfaces opaque; native scrolling; word highlights subordinate to red/green.

### D22 — Review features, all in v1
- (a) Full file-by-file diff view with two-way jumps to/from story frames, preserving position.
- (b) GitHub deep link on every diff line.
- (c) Per-frame "reviewed" toggle with progress on the map (localStorage).
- (d) `story.md` kept next to the HTML; rebuilding after a push reports which chapters went stale.

### D23 — Agent-agnostic
Follows the agentskills.io layout, in `skills/code-story/` so an install (`npx skills add`) ships only the skill, not these docs or the tests; works for Claude Code and Codex (`agents/openai.yaml`); harness-specific steps (e.g. subagents) are optional.

### D24 — Skill layout (progressive disclosure)
```
skills/code-story/
  SKILL.md                 # when to use, flow: index → author → build → verify; pointers
  references/
    directives.md          # directive syntax + examples
    storytelling.md        # guidance (D20)
    design-system.md       # Black Liquid Glass tokens/components for creative extras
    verification.md        # reviewer brief (D16)
    tour.md                # tours: index --tour, the spine, directives (D39)
  scripts/codestory.py     # uv / PEP 723: index, build, check
  assets/                  # story.css, story.js, template.html
  agents/openai.yaml
```
Invocation: `uv run skills/code-story/scripts/codestory.py index --repo . --base origin/main --head HEAD|WORKTREE [--pr URL]`, then `build`. `uv` is a required dependency.

### D25 — Visual details are decided by prototype
Fonts, spacing, motion and similar details are judged on the prototypes, not debated up front. Prototypes start with the system font stack (SF Pro / SF Mono).

### D26 — Prototype code comes from git
A throwaway script extracts real hunks and context from the PR's commits into the prototypes. Only the narrative is hand-written.

### D27 — Repo setup
A standalone repo; this doc lives in `docs/design.md`. The prototypes render a private repo's code, so they stay out of this repo; the engine reproduces P4.

### D28 — One layout: P4 combines P1–P3
The reading spine and map come from P1. Evidence cards come from P2, used only where a card supports a specific line. Failure branches come from P3, opened in place under a fork instead of in a side column. P1–P3 stay as references; P4 is the layout the engine builds toward (decides D4).

### D29 — Width and code
- Pages use the full viewport, like GitHub: prose is capped near 74ch and frames run full width.
- Code is never truncated and never hidden behind a sideways scroll. Long lines wrap, and the continuation hangs under the line's own indentation.
- Split view stays and is generated client-side from the unified rows, which halves page size. In split mode, evidence lanes move under the code, because halves beside a lane are too narrow to read.
- Split is offered only when the story column itself, without the map's lane and the gutters, is at least 680px wide. On a phone, or with a wide map beside a small window, the page shows unified and the Split button is disabled with the reason; the stored choice returns when there is room.
- Indentation is rendered as no-break spaces, so a long first token wraps inside itself instead of leaving the first visual line blank. Copying restores real spaces: copied code is byte-for-byte what git has. In split, a selection stays on the side where it started.

### D30 — Chrome
- The header is two floating pieces, pinned to the top corners: nothing the map does moves them. The left one holds the title and commits. The right one holds progress, Trace, Unified/Split, notes, Full diff and help.
- It hides on scroll down and comes back on scroll up, on keyboard focus, or when the pointer nears the top. Scrolls the page makes itself (map jumps, trace steps, layout changes) never hide it.
- The pieces never overlap. When the title would get less than 240px, the right piece drops its text labels and the left drops the commits.
- Layout changes (map, split, notes) keep the line being read in place, resolving it to whatever shows that line after the change.
- The map is a floating panel that starts open at the top left, under the header. Its height fits its content. It has a grip and is dragged by its header. While it is dragged, a faint outline marks its home slot, and it lights up when the panel is close enough to dock. Dropping it there docks it, so the column's shift on release is expected. Dropping it anywhere else floats it. Double-clicking the header, or its put-back button, returns it home. Away from home it resizes from every edge and corner. At home it is anchored to the corner, so only its right and bottom edges resize, and it never narrows the story column below 540px. It never disappears: its collapse button (or `m`) shrinks it to a rail of chapter dots that keeps showing progress. While it sits at home, the story column leaves room for it; dragged away, the column takes the full width. Moving or resizing touches only the panel, and the column adjusts once, on release. Its state is remembered. On phones it is a drawer opened from the header.
- The map shows each chapter's title with where it runs ("Every request, AccessCheck"). There is no TOC block above chapter 1.

### D31 — No decorative subtitles
A line under a heading must carry information, or it moves into the title, the paragraph or a note. This goes into `references/storytelling.md`.

### D32 — Evidence cards: the line contract
- A card declares `data-to=<frame id>` and `data-lines="15,21-23"` (new-side numbers).
- Hovering the card, or clicking its label, lights the target lines, the wire and the card together. Hovering a linked line lights its cards.
- Wires are 1px with no fill and no glow. Narrow layouts drop the wires and show a `L15` chip instead.

### D33 — Rows
- Clicking a line or its number selects it like GitHub. Shift-click, or dragging down the line numbers (scrolling at the edges), selects a range. Cmd/ctrl-click adds or removes single lines. The URL hash becomes `#<frame>-R15-R18,R21` and is restored on load, opening any collapsed block that holds it. Selecting a linked line also lights its cards.
- In split, the selection belongs to the side that was clicked: `#auth-L12-L28` paints only left halves. Unified paints the contiguous block.
- A GitHub icon in the gutter of the hovered line opens that line on GitHub.
- Only changed frames carry "reviewed" ticks; context frames don't count toward progress.

### D34 — Full diff overlay
- A macOS-style red close button sits at the top left. This is universal: every element that closes (dialogs, sheets, the full diff, branch panels) uses the red dot at its top left, never a "Close" text button.
- Files collapse like GitHub's: by the chevron, or by clicking the file header outside the path and stats. There is a collapse-all control.
- The file list can be resized by dragging its border, and it highlights the file being read.
- Dialogs stack: Help opened over the full diff makes the full diff inert too, and closing it returns focus there.
- A file is one block of rows, so a line selection there belongs to the file (`#fd-<file>-R15`). Each hunk's header sits where its hidden lines are and carries their expand buttons (D40).

### D35 — Trace
- Identifiers are highlighted only on hover or while a trace is active.
- The trace pill counts the frames a trace lights and, once the reader steps through them, says where they are: "4 / 16".
- The Trace button shows the active value. Its menu is fixed under the button and explains what a trace does in one line.
- The pill at the bottom steps through the traced frames with icon buttons: previous, next, stop.

### D36 — story.md format
Markdown with YAML front matter (`title`, `map`, `traces`, `exclude` with a required reason, `include`). `# Title` and the prose under it make the hero; each `## Chapter {#id map="Label" where="…" .appendix}` is a chapter. Code comes only from directive lines: `@diff hunk-ids [rows=a-b]`, `@ctx path@head|base a-b`, `@ripple first more…`, `@also path`. Layout blocks are fenced with `::: name … :::`: `step` (one code frame, then `card LINES` blocks whose first line is the reason), `fork` holding `branch` blocks, `note <kind> Title`, and `sketch` for labelled pseudo-code. A card points only at its own step's code, by new-side line numbers, checked at build. Hand-typed code blocks of two or more lines warn (D11). Not-in-story is generated from the exclusions, never written by hand.

### D37 — Stale anchors need an explicit accept
`anchors.json` records the hash of every hunk and context range the last build used, and a fingerprint (blob ids, modes, status, rename) for every file covered as a whole. When an anchor's code changed, whether the head or the base moved, build fails and names every chapter that uses it. After re-reading them and updating the prose, `build --accept` records the new anchors. Nothing is relocated silently (D17).

### D38 — The diff is pinned, not configured
The engine pins every git setting that changes diff output (blank context lines, relative paths, submodule format, diff algorithm, inter-hunk context, renames, textconv filters), so a story parses and numbers the same on every machine. Patch sections are matched to files by their headers, which handles a file that becomes a symlink. A PR's base is GitHub's own base commit when the clone has it. Reviewed marks are keyed by path and content, not by frame position, so a frame whose code changed comes back unreviewed while the rest keep their marks, even when frames are added before it.

### D39 — Tours
- A tour explains how an app works to a newcomer: the main parts and the flow that matters, not every file. There is no coverage check.
- `index --tour` pins one commit (HEAD, a ref, or the working tree) with no base and no diff. A repo has one tour, at `<repo>/tour/`; it branches through forks like any story.
- Only `@ctx path@head` and `@tree` work; `@diff`, `@ripple`, `@also` and `@base` fail with a pointer to them. The stale-anchor check stays, so re-indexing a tour at a newer commit names the chapters whose code moved.
- `@tree dir depth=N` lists a directory from git (dirs with file counts, files with line counts), so the layout is evidence too. Its anchor hashes the structure only. It works in change stories as well.
- The page drops what needs a diff: full diff, unified/split, reviewed marks and progress. Frames lose the Unchanged chip and the dimmed context look. The map footer counts chapters instead.
- One skill: the description names the tour case and SKILL.md branches to `references/tour.md`. Change stories stay the main use.
- The layout is the scroll story. A canvas was reconsidered for tours and left for after a real tour has been read; the map and a hero sketch carry the overview for now.
- Symbol anchors (`@ctx path symbol=X`) are deferred; line ranges plus the stale check first.

### D40 — More of a file, packed once
- Any frame can show more of its file. The break between two shown runs, and a frame's top and bottom edge when lines are hidden there, carry buttons: 20 lines up, 20 lines down, or everything hidden at that break. Shift-click unfolds the whole file. A fold button appears in the frame's header and takes the frame back to what the story chose.
- What unfolds is the file's diff, not just unchanged lines: changes from hunks shown elsewhere keep their red and green. Unchanged lines the reader unfolded are dimmed a step, so the story's own choice stays readable. A context frame unfolds the plain file at its commit.
- Scroll rule: a step down keeps its button under the pointer, so it can be clicked again; anything that unfolds a whole section keeps the code that was already on screen where it was.
- Each file is packed into the page once as a **source**: every row of its diff with all unchanged lines in place (or the plain file, for a context frame), rendered by the build like any other row, deflated, and inflated in the browser on first use. The page stays one offline file. Frames record where their rows sit in the source, so no numbering is recomputed in the browser beyond counting.
- The full diff and the bodies under "Not in story" ship no rows. They are filled from the sources: the full diff fills the file it opens at, then whatever is near the screen, then the rest in the background while correcting the scroll, so opening never waits on the whole diff and searching the page soon finds all of it. A real PR page went from 3.5 MB and 9,500 rows at load to 1.1 MB and 1,600, with whole-file context included.
- Limits: files over 1.5 MB, binaries, symlinks and submodules keep their hunks but can't unfold. So does a file whose blob and patch disagree line for line, rather than show wrong numbers. The browser needs `DecompressionStream` (Chrome 80, Firefox 113, Safari 16.4); without it the buttons don't appear, and the full diff and "Not in story" bodies stay empty with a notice.
- A trace counts only where the story shows it. One that appears only in a file left out of the story warns, since the page can't light it there.
- Build cost: word marks are computed only by `build` (not `index`, `show` or `check`), lines over 200 characters pair by word instead of by character, and git answers every file read from one process. The same PR builds in 1.7 s instead of 4, and `show` answers in 0.3 s.

### D41 — A scroll repaints nothing
- Hover on code rows is set by the script (`.hov`), not by `:hover`. A browser also hovers whatever scrolls under a resting pointer, so every row passing it lit up, took the GitHub icon and could light a linked note: a flicker at the pointer and a repaint on each frame. While the page scrolls the hover stays where it was and settles 100 ms after the scroll stops.
- What the map animates as chapters pass (the progress line, the lit dot, the tour bar) moves by `transform` and `opacity` only. Animating a height or a colour there laid the page out and repainted the story on every frame of the transition.
- Measured on a real PR page, 150 wheel steps with the pointer over code: 359 repaints and 196 layouts before, 33 and 9 after.
- The header changes state only after 24 px of travel in one direction, so a few pixels back and forth can't flip it, and scrolling never hides it from under the pointer.
- No blur behind the header, the map or the full diff. The panels were frosted glass (`backdrop-filter`), which the browser recomputes on every frame of a scroll; side by side with a plain, nearly opaque panel the owner saw no difference, so the blur went. At a chapter boundary the map waits 8 px before switching, and its list glides to the active chapter instead of jumping.

### D42 — A frame folds to its header
- Clicking a frame's header, or the chevron in it, folds the frame to that header; clicking again opens it. The path and the counts stay selectable text, as in the full diff.
- Marking a frame reviewed folds it, and unmarking opens it, as GitHub does with viewed files. Reviewed frames come back folded on reload. A reviewed frame can still be opened by its header without losing the mark.
- Anything that points into a folded frame opens it: a line link, a note's link to its lines, a trace step.
- Folded with `r` while its header is off screen above, the frame is brought back to the top, since the code under the reader is gone.

### D43 — A name opens its definition
- A name on the page that has a definition on the page underlines under the pointer. A click opens the definition in a panel beside the code: the function, class or constant with the decorators and comments above it, at most 120 rows, with the same unfold buttons as a frame for the rest of its file. Names inside the panel open in it too. Esc, the red dot or a click outside the panel closes it; that click does nothing else unless it lands on a button or a link. The panel is at most 46% of the window's height (560 px at most) and scrolls inside; it never opens on top of the name that was clicked, but under that line or above it. Its header drags it, and it stays where it was dragged for the next definitions; a double-click on the header puts it back. The panel is measured once at the grab and then moved by a transform on its own layer, so a move costs no layout and no paint; the position is written on release. A definition still loading when the panel is closed, or when another is asked for, is dropped. Where the name can also start a trace, the click opens the definition and alt-click starts the trace.
- There is no language server and nothing is resolved in the browser. The build reads the highlighter's tokens: a name after `def`, `class`, `function`, `func`, `fn`, `struct`, `interface`, `type` and their kin is a definition, plus top-level constants, Go methods, JS methods and what Java and C mark as a function. Each use carries `data-d`, places in a small manifest; the panel is drawn from the sources of D40, so a definition costs the page no rows until it is opened.
- A definition is known only if its file is on the page: a changed file, or one a `@ctx …@head` shows. Nothing else in the repo is searched or packed for code.
- A use is linked only when its name and the code around it settle where it leads. An import line names the file (`from src.cache import load`, `import { load } from "./cache"`), and a name imported from somewhere the page doesn't have links nothing. A relative import (`from .cache import load`, `"./cache"`) means the file beside the importer and no other of that name. An alias (`import Thing as Base`) opens what it was imported as. Otherwise the name has to be a call or tell enough by itself (`load_rows`, `MAX_ROWS`, `TableCatalog`). `x.get(` needs a receiver that names the file or is `self`. A method never leads to itself (`super().load()`), a function inside a function is not reached through a dot, test helpers serve only tests. One candidate in the same file wins; two or three are all offered ("1 of 2"); more than three link nothing. No link is better than a wrong one. On two real stories, 920 links were checked by hand after these rules; the wrong ones found on the way each became a rule and a test.
- dbt: in a tree with a `dbt_project.yml`, `ref('model')` opens the model's file and a call to a project macro opens the macro, up to its `endmacro`. These are found by text, since the SQL lexer knows no Jinja: one string literal in `ref`, a macro name only inside `{{ }}` or `{% %}`, which can span lines. Two models of one name link neither. Package macros, sources and seeds are not linked.
- Models and macros are usually outside the change, so the page packs them, within a budget: 3,000 rows and 60 files a page, 600 rows a file. Files named in lines the story itself shows (its `@diff`, `@ripple`, `@also` and `@ctx`) go first, then files named only in lines a reader has to unfold or open the full diff for; inside each group the most-named first. Past the budget a `ref` stays plain text and the build prints one `note:` with the counts and the names left out. A packed model's own `ref`s open only what the page already has: one hop, never the lineage. Measured on three commits of a 1,350-model project (8, 38 and 128 files changed): 41 to 60 outside files, 49 to 58 kB added to pages of 0.5 to 2 MB, nothing inflated until a click, builds of 1.5 to 2.1 s.
- `check` and `show` find no definitions; only a `build` that writes the page does.

## Open questions
None. P4 went through review rounds with Fable 5.1 and Codex Sol. The engine (D24) lives in `skills/code-story/scripts/codestory.py` and `skills/code-story/assets/`; it reproduces P4 from a story.md.
