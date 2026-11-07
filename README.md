# code-story

An [Agent Skills](https://agentskills.io) skill that turns a code change into a scroll-driven HTML page you read in the order the code runs: a request arrives, a middleware checks it, a record gets written. Each stop shows the real code, rendered from git.

The agent writes the narrative. It never types code into the page: every line comes from git through a script, and the build fails until every change in the diff is shown somewhere.

It makes two kinds of story:

- **A change**: a pull request, a branch, or uncommitted work, walked through in execution order, with notes where the description and the code disagree.
- **A tour**: how an app, or one flow in it, works, for someone new to the code.

## What the page does

- A floating map of the chapters that tracks where you are.
- Unified or split diffs, with word-level highlights on changed lines.
- Failure paths that open in place at the point they branch off.
- Trace: click a value and every frame it passes through lights up.
- A full file-by-file diff, with jumps both ways between it and the story.
- A "reviewed" mark per frame, and GitHub links on lines and frames when the code is on GitHub.
- One self-contained HTML file that works offline.

## Install

```bash
npx skills add eukosh/code-story -g -y -s code-story
```

It needs [`uv`](https://docs.astral.sh/uv/) and `git`. A pull request link also needs [`gh`](https://cli.github.com/).

## Use

Ask your agent:

- "Make a code story for https://github.com/OWNER/REPO/pull/42"
- "Walk me through what I changed on this branch"
- "Give me a tour of how this app handles a request"

It indexes the change, reads the code it needs, writes `story.md`, builds the page, has a second reviewer check the prose against the code, and gives you the path. Stories live in `~/.code-story/<owner>/<repo>/`.

## Repo layout

- `skills/code-story/` is the skill itself, and the only part an install copies: `SKILL.md`, references, the engine (`scripts/codestory.py`) and the page assets.
- `docs/design.md` records the design decisions.
- `tests/` holds the engine's tests: `uv run --with pytest --with pygments --with markdown-it-py --with pyyaml pytest tests -q`

## License

[MIT](LICENSE)
