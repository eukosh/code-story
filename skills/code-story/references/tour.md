# Tours

A **tour** walks a newcomer through how an app works, with no change to review: what it's for, where it starts, the flow that matters most, and where to look next. It is for the gist, not for coverage. Leaving most of the code out is the job; the build checks no coverage.

## Index

```bash
uv run <skill>/scripts/codestory.py index --repo PATH --tour [--head REF|WORKTREE]
```

It pins one commit (HEAD by default) and reads only what that commit holds: uncommitted and untracked files stay out unless you pass `--head WORKTREE`. It prints the repo's layout two levels deep and names the story folder: `~/.code-story/<owner>/<repo>/tour/`. A repo has one tour. Later, index again to re-pin it at a newer commit and build: the build names every chapter whose code moved, as in a change story (re-read, update the prose, `--accept`).

## Read

- `show DIR path@head` lists a directory with file and line counts; `show DIR path@head:a-b` reads lines. Your own tools (search, file reads) work too, but take line numbers for `@ctx` from `show`.
- Find the entry points first: `main`, server or app setup, CLI commands, request handlers, job or DAG definitions, the Terraform root. They tell you what the app does when it runs.
- Then find where state lives (database models, schemas, caches, external services) and where configuration is read.
- READMEs and docs state intent. Check them against the code like a PR description; where they disagree, the code wins and a `mismatch` note says so.

## The spine

When the user named a flow ("how auth works"), that flow is the spine. Otherwise pick the one a newcomer most needs (a request end to end, a job run, a row through the pipeline). Walk it, one chapter per stop, with a `where=` on each. [`storytelling.md`](storytelling.md) applies, read with "the app" in place of "the change".

- The hero says what the app is for and who uses it, in two or three sentences. A `::: sketch` or an inline SVG of the main flow fits here when the shape helps.
- Open with `@tree` only when the layout itself tells the reader something (a monorepo's packages, a layered app); otherwise open at the entry point.
- Side flows (failure handling, a second mode, an admin path) go in a fork at the point they leave the main flow, not in chapters of their own.
- Keep startup, per-request and deploy-time code in separate chapters.
- Frames show the lines that make the point: a signature and the 10–30 lines that matter, not whole files. The stamp links to the rest.
- End with an appendix chapter, "Where to go next": the areas the tour skipped, one line each, with a `@tree` where that helps.

## Directives in a tour

Only `@ctx path@head a-b` and `@tree` work. `@diff`, `@ripple`, `@also` and `@base` have nothing to show and fail the build. Steps, cards, forks, notes, sketches and traces work as in a change story. `question` and `finding` notes are for real problems the code shows; a tour isn't a review.

## Verify

Run the verification pass with the tour variant of the brief in [`verification.md`](verification.md).
