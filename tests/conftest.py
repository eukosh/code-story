# Run: uv run --with pytest --with pytest-xdist --with pygments --with markdown-it-py --with pyyaml pytest tests -q -n auto --dist worksteal
# Add --with playwright to run the page's tests in the installed Google Chrome; they skip without it.
import json
import os
import re
import shutil
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path

import pytest


ENGINE = Path(__file__).resolve().parents[1] / "skills/code-story/scripts/codestory.py"
LINES = "".join(f"value_{n} = {n}\n" for n in range(1, 31))


class Tags(HTMLParser):
    def __init__(self, text):
        super().__init__()
        self.tags = []
        self.feed(text)

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


class Repo:
    def __init__(self, root, template=None):
        self.path = root / "repo"
        self.path.mkdir()
        self.out = root / "story"
        home = root / "home"
        home.mkdir()
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(
            HOME=str(home),
            XDG_CONFIG_HOME=str(home),
            CODE_STORY_HOME=str(root / "stories"),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_CONFIG_GLOBAL=os.devnull,
            GIT_ATTR_NOSYSTEM="1",
            GIT_CONFIG_COUNT="2",
            GIT_CONFIG_KEY_0="core.hooksPath",
            GIT_CONFIG_VALUE_0=os.devnull,
            # Otherwise every commit spawns a background `git maintenance run --auto`.
            GIT_CONFIG_KEY_1="maintenance.auto",
            GIT_CONFIG_VALUE_1="false",
            GIT_AUTHOR_NAME="Story Tests",
            GIT_AUTHOR_EMAIL="story@example.invalid",
            GIT_COMMITTER_NAME="Story Tests",
            GIT_COMMITTER_EMAIL="story@example.invalid",
            GIT_AUTHOR_DATE="2020-01-01T12:00:00+0000",
            GIT_COMMITTER_DATE="2020-01-01T12:00:00+0000",
            LC_ALL="C",
            TZ="UTC",
        )
        if template:
            shutil.copytree(template, self.path / ".git")
        else:
            self.git("init", "--quiet", "--initial-branch=main", "--template=")
        self.base = None

    def git(self, *args):
        result = subprocess.run(
            ["git", "-C", str(self.path), *map(str, args)],
            env=self.env, capture_output=True, text=True, timeout=15,
        )
        assert result.returncode == 0, result.stderr
        return result.stdout.strip()

    def write(self, files):
        for name, content in files.items():
            path = self.path / name
            path.parent.mkdir(parents=True, exist_ok=True)
            if content is None:
                path.unlink()
            else:
                path.write_bytes(content if isinstance(content, bytes) else content.encode())

    def commit(self, files=None):
        self.write(files or {})
        self.git("add", "-A")
        self.git("commit", "--quiet", "--allow-empty", "-m", "fixture")
        sha = self.head()
        if self.base is None:
            self.base = sha
        return sha

    def head(self):
        """HEAD's sha read from the ref files, saving a git process per commit."""
        git_dir = self.path / ".git"
        try:
            ref = (git_dir / "HEAD").read_text().strip()
            if ref.startswith("ref: "):
                ref = (git_dir / ref[5:]).read_text().strip()
        except OSError:
            ref = ""
        return ref if re.fullmatch(r"[0-9a-f]{40}", ref) else self.git("rev-parse", "HEAD")

    def run(self, *args, ok=True):
        result = subprocess.run(
            [sys.executable, str(ENGINE), *map(str, args)],
            cwd=self.path, env=self.env, capture_output=True, text=True, timeout=20,
        )
        if ok:
            assert result.returncode == 0, result.stdout + result.stderr
        else:
            assert result.returncode == 1, result.stdout + result.stderr
            assert "Traceback" not in result.stderr
        return result

    def index(self, head="HEAD", base=None, ok=True, out=None):
        return self.run(
            "index", "--repo", self.path, "--base", base or self.base or "HEAD",
            "--head", head, "--out", out or self.out, ok=ok,
        )

    def story(self, body, front=""):
        self.out.mkdir(exist_ok=True)
        (self.out / "story.md").write_text(
            (f"---\n{front}\n---\n" if front else "")
            + "# A change\n\nA short lede.\n\n## Flow {#flow}\n\n" + body + "\n"
        )

    def build(self, *args, ok=True):
        return self.run("build", self.out, *args, ok=ok)

    def read(self, name):
        return (self.out / name).read_text()

    def json(self, name):
        return json.loads(self.read(name))

    def tags(self, tag=None, cls=None):
        return [attrs for name, attrs in Tags(self.read("story.html")).tags
                if (tag is None or name == tag) and (cls is None or cls in attrs.get("class", "").split())]

    def frame(self, fid):
        return next(a for a in self.tags() if a.get("id") == fid)


@pytest.fixture(scope="session")
def git_template(tmp_path_factory):
    """A fresh `git init`, copied by every repo: the same files without a git process per test."""
    return Repo(tmp_path_factory.mktemp("template")).path / ".git"


@pytest.fixture
def repo(tmp_path, git_template):
    return Repo(tmp_path, git_template)


@pytest.fixture
def changed(repo):
    repo.commit({"app.py": LINES, "empty.txt": "", "src/context.py": "first = 1\nsecond = 2\nthird = 3\n"})
    repo.commit({"app.py": LINES.replace("value_2 = 2", "value_2 = 200").replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    return repo


# ---- the page in a browser: Playwright driving the installed Google Chrome ----


@pytest.fixture(scope="session")
def browser():
    sync = pytest.importorskip("playwright.sync_api", reason="browser tests need playwright (uv run --with playwright)")
    with sync.sync_playwright() as p:
        try:
            b = p.chromium.launch(channel="chrome")
        except sync.Error as e:
            pytest.skip(f"browser tests need Google Chrome: {e.message.splitlines()[0]}")
        yield b
        b.close()


@pytest.fixture
def context(browser):
    """One browser profile: pages opened in it share localStorage, as a reader's tabs do."""
    ctx = browser.new_context(viewport={"width": 1400, "height": 900})
    yield ctx
    ctx.close()


@pytest.fixture
def story_page(context):
    """Opens a built story.html; the page's own errors fail the test."""
    errors = []

    def open_(repo, page=None):
        if page is None:
            page = context.new_page()
            page.set_default_timeout(5000)
            page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto((repo.out / "story.html").as_uri())
        page.wait_for_function("document.readyState === 'complete'")
        return page

    yield open_
    assert not errors, errors
