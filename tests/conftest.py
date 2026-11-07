# Run: uv run --with pytest --with pygments --with markdown-it-py --with pyyaml pytest tests -q
import json
import os
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
    def __init__(self, root):
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
            GIT_CONFIG_COUNT="1",
            GIT_CONFIG_KEY_0="core.hooksPath",
            GIT_CONFIG_VALUE_0=os.devnull,
            GIT_AUTHOR_NAME="Story Tests",
            GIT_AUTHOR_EMAIL="story@example.invalid",
            GIT_COMMITTER_NAME="Story Tests",
            GIT_COMMITTER_EMAIL="story@example.invalid",
            GIT_AUTHOR_DATE="2020-01-01T12:00:00+0000",
            GIT_COMMITTER_DATE="2020-01-01T12:00:00+0000",
            LC_ALL="C",
            TZ="UTC",
        )
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
        sha = self.git("rev-parse", "HEAD")
        if self.base is None:
            self.base = sha
        return sha

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


@pytest.fixture
def repo(tmp_path):
    return Repo(tmp_path)


@pytest.fixture
def changed(repo):
    repo.commit({"app.py": LINES, "empty.txt": "", "src/context.py": "first = 1\nsecond = 2\nthird = 3\n"})
    repo.commit({"app.py": LINES.replace("value_2 = 2", "value_2 = 200").replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    return repo
