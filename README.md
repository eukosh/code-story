# code-story

An [Agent Skills](https://agentskills.io) skill that turns a code change into a scroll-driven HTML page you read in the order the code runs: a request arrives, a middleware checks it, a record gets written. Each stop shows the real code, rendered from git.

![A code story of a small change: related code sits beside the line it supports, a name opens its definition, the diff splits, a snippet folds when reviewed, a failure path opens in place, a file unfolds, a dbt ref opens its model, a value is traced from the report back to the request, and the full diff opens](docs/demo.webp)

The agent writes the narrative. It never types code into the page: every line comes from git through a script, and the build fails until every change in the diff is shown somewhere.

It makes two kinds of story:

- **A change**: a pull request, a branch, or uncommitted work, walked through in execution order, with notes where the description and the code disagree.
- **A tour**: how an app, or one flow in it, works, for someone new to the code.

## What the page does

- A floating map of the chapters that tracks where you are.
- Unified or split diffs, with word-level highlights on changed lines.
- Any snippet unfolds to show more of its file: 20 lines up or down, everything hidden at that spot, or the whole file.
- A snippet folds to its header with a click, and folds itself when marked reviewed.
- Click a function, class, constant or Python class field to open its definition beside the code, when it is defined in a file the page has. In a dbt project, `ref('model')` and macro calls open the model and the macro.
- Failure paths that open in place at the point they branch off.
- Trace: every snippet a value passes through lights up. A click on a traced name shows the trace in the panel, and its chip starts it; alt-click starts it at once.
- A full file-by-file diff, with jumps both ways between it and the story.
- A reviewed mark per snippet, shared by the PR, branch and working-tree stories of one change. Identical code at another place in the file needs its own mark. A snippet whose code changed after you marked it reopens with "Changed since review" and a bar beside each line that differs. The hint is a best guess from the rows the mark kept: it misses a line removed at a snippet's very start or end, and it also shows when a story re-cuts unchanged code so a snippet grows past one you marked.
- GitHub links on lines and snippets when the code is on GitHub.
- One self-contained HTML file that works offline.

## Install

**Claude Code**, as a plugin, from a terminal:

```bash
claude plugin install code-story --marketplace eukosh/code-story
```

The same inside a Claude Code session is `/plugin install code-story --marketplace eukosh/code-story`. On versions before 2.1.275 it takes two steps: `/plugin marketplace add eukosh/code-story`, then `/plugin install code-story@code-story`.

**Any agent that reads Agent Skills** (Claude Code, Codex, Cursor, Gemini CLI and others):

```bash
npx skills add eukosh/code-story -g -y -s code-story
```

Pick one of the two; installing both gives Claude Code the skill twice.

It needs [`uv`](https://docs.astral.sh/uv/) and `git`. A pull request link also needs [`gh`](https://cli.github.com/).

## Use

Ask your agent:

- "Make a code story for https://github.com/OWNER/REPO/pull/42"
- "Walk me through what I changed on this branch"
- "Give me a tour of how this app handles a request"

It indexes the change, reads the code it needs, writes `story.md`, builds the page, has a second reviewer check the prose against the code, and gives you the path. Stories live in `~/.code-story/<owner>/<repo>/`.

## Repo layout

- `skills/code-story/` is the skill itself, and the only part `npx skills` copies: `SKILL.md`, references, the engine (`scripts/codestory.py`) and the page assets.
- `.claude-plugin/` makes the repo a Claude Code plugin and its own one-plugin marketplace.
- `docs/design.md` records the design decisions.
- `tests/` holds the tests: `uv run --with pytest --with pytest-xdist --with pygments --with markdown-it-py --with pyyaml pytest tests -q -n auto --dist worksteal`. Add `--with playwright` to also run the page's tests (`tests/test_page*.py`) in the Google Chrome installed on the machine; without Playwright or Chrome they are skipped. Without pytest-xdist, drop it and `-n auto --dist worksteal` to run them one at a time, several times slower.

  Tests run in parallel worker processes, in no fixed order, so each one builds everything it needs from its own `repo` or `tmp_path`: no module-level state that a test changes, no fixed paths or ports. A worker keeps one Chrome for all its page tests, so a page test keeps its state in its own `context`; and no test writes to `git_template`, the `.git` every repo starts as a copy of.

## License

[MIT](LICENSE)
