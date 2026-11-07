---
name: code-story
description: Turn a code change into a scroll-driven HTML review story that walks the reader through the change in the order the code runs, with every line of code rendered from git. Use when someone wants a code story, a walkthrough or visual review of a pull request, a branch, or uncommitted work, or when a review workflow asks for a story as its last step. Also makes a tour of a codebase when someone asks how an app, or one flow in it, works.
---

# code-story

A **story** walks a reviewer through a change the way the program meets it: a token arrives, a middleware reads it, a record gets written. You write the narrative in `story.md`; the engine renders every line of code from git and refuses to build until every change is shown somewhere. Code on the page is evidence, so it only ever enters through directives.

**Tours.** When the user asks how an app or one of its flows works, with no change to review, make a tour: do step 1, then follow [`references/tour.md`](references/tour.md) in place of steps 2 and 3, then continue at step 4.

`<skill>` below is this skill's directory. The engine needs `uv` and `git`; a PR link also needs `gh`.

## 1. Load the prose rules

Before writing a word of the story, look through your available skills and instructions for anything about how written text should read (a humanizer-style skill, prose rules in AGENTS.md or CLAUDE.md) and load it. The story's prose follows those rules, and the reviewer in step 6 checks against them.

## 2. Index the change

The caller prepares the repo: this skill never clones, fetches, or checks out.

```bash
uv run <skill>/scripts/codestory.py index --repo PATH --pr https://github.com/OWNER/REPO/pull/N
uv run <skill>/scripts/codestory.py index --repo PATH [--base REF] [--head REF]
uv run <skill>/scripts/codestory.py index --repo PATH --head WORKTREE
```

- `--pr` reads the PR's title, description and base with `gh`, for intent only. Index reads commits straight from git, so whichever branch the clone has checked out doesn't matter. If the PR head isn't in the clone, index stops with the fetch command to run; pass that to the user rather than fetching yourself.
- `WORKTREE` snapshots staged, unstaged and untracked files without touching the repo. Build fails if the files change afterwards; index again then. The snapshot lives only as loose git objects, so a working-tree story is for now, not for keeping; `--out` must sit outside the repo.
- The output lists every file and hunk with its id (`src/auth.py#h2`), enclosing symbol and size, the files kept out of coverage by default (tests, lockfiles, generated), the PR description, and the **story folder** where `story.md` goes.

## 3. Read the change

Read every hunk you will place, with `show`, plus the unchanged code a first-time reader needs one hop out: callers, consumers, where a value comes from.

```bash
uv run <skill>/scripts/codestory.py show DIR src/auth.py#h2 src/env.py      # hunks, with row numbers for rows=
uv run <skill>/scripts/codestory.py show DIR src/app.py@head:40-80          # file lines at head or base
```

Check the PR description against the code as you go. Where they disagree, the story says so in a `mismatch` note. Then pick the spine: [`references/storytelling.md`](references/storytelling.md) holds the guidance for ordering chapters, choosing context and keeping prose lean. Read it before outlining.

## 4. Write story.md

Write `story.md` in the story folder. The format, every directive and block, and the build's errors are in [`references/directives.md`](references/directives.md); read it before writing. Raw HTML is allowed for creative touches; [`references/design-system.md`](references/design-system.md) has the classes and tokens to build them with.

## 5. Build

```bash
uv run <skill>/scripts/codestory.py build DIR
```

The story folder holds `story.md` (yours), `index.json` (from index), and after a build `story.html`, `story.txt` and `anchors.json` (the code each anchor pointed at, for the stale check below). The build fails on coverage gaps, unknown ids, card lines the step's code doesn't show, and stale anchors, each with the line in `story.md` and a hint. Fix and rebuild. Done when it prints `built …/story.html` and every warning is either fixed or one you can justify. `check DIR` runs the same checks without writing.

## 6. Verify

Every build also writes `story.txt` beside the page: the story as a reader meets it, in plain text, with each frame's code and line numbers and each card's target lines. Read it before the pass; it's the quickest way to catch a frame pointing at the wrong lines.

Run the verification pass once: a fresh reviewer reads the built story against the code. The brief is in [`references/verification.md`](references/verification.md). Use a subagent where your harness has one; otherwise do the pass yourself in a separate, deliberate read. The reviewer can be wrong, so check each claim against the code before changing the story. Rebuild after changes.

## 7. Hand over

```bash
uv run <skill>/scripts/codestory.py build DIR --open
```

Give the user the path to `story.html` and open it. The page embeds the repo's code: keep it on this machine and share it only where the user says. Anything the calling workflow already reported in chat stays there; the story adds to it.

When the change moves later (a new push, more edits), index again into the same folder and build. If the code under an anchor changed, the build names the chapters; re-read them, update the prose, and build with `--accept`.
