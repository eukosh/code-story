#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["pygments>=2.18", "markdown-it-py>=3.0", "pyyaml>=6.0"]
# ///
"""code-story: turn a code change, or a tour of a codebase, into a scroll-driven page.

    codestory.py index --repo PATH [--base REF] [--head REF|WORKTREE] [--pr URL] [--out DIR]
    codestory.py index --repo PATH --tour [--head REF|WORKTREE] [--out DIR]
    codestory.py show DIR SPEC...      SPEC: hunk id | path | path@head|base[:a-b | a-b | :n | n]
    codestory.py build DIR [--open] [--accept]   story.md -> story.html and story.txt
    codestory.py check DIR [--accept]            build's checks, nothing written

Every line of code on the page is read from git. The model writes only story.md.
"""

from __future__ import annotations

import argparse
import base64
import bisect
import difflib
import hashlib
import html
import json
import os
import posixpath
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import webbrowser
import zlib
from urllib.parse import quote
from dataclasses import dataclass, field
from datetime import datetime, timezone
from fnmatch import fnmatch
from functools import cache
from html.parser import HTMLParser
from pathlib import Path

import yaml
from markdown_it import MarkdownIt
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_for_filename
from pygments.lexers.special import TextLexer
from pygments.token import STANDARD_TYPES
from pygments.util import ClassNotFound

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"
HOME = Path(os.environ.get("CODE_STORY_HOME", "~/.code-story")).expanduser()
WORKTREE = "WORKTREE"


class Fail(Exception):
    """A problem the caller has to fix; printed without a traceback."""


# ---------- git ----------


# Settings that change diff output, pinned so a story parses and numbers the same on every machine.
GIT_CONFIG = tuple(
    x
    for kv in (
        "core.quotePath=false", "diff.suppressBlankEmpty=false", "diff.noprefix=false", "diff.mnemonicPrefix=false",
        "diff.relative=false", "diff.algorithm=myers", "diff.interHunkContext=0", "diff.indentHeuristic=true",
        "diff.ignoreSubmodules=none", "diff.submodule=short", "diff.renameLimit=0",
    )
    for x in ("-c", kv)
)


class Git:
    def __init__(self, repo: Path) -> None:
        self.repo = repo

    def run(self, *args: str, env: dict | None = None, ok: tuple[int, ...] = (0,), input: str | None = None) -> str:
        p = subprocess.run(
            ["git", "-C", str(self.repo), *GIT_CONFIG, *args],
            capture_output=True,
            env=env,
            input=input.encode() if input is not None else None,
        )
        if p.returncode not in ok:
            raise Fail(f"git {' '.join(args[:3])} failed: {p.stderr.decode(errors='replace').strip()}")
        return p.stdout.decode("utf-8", errors="replace")

    def try_run(self, *args: str) -> str | None:
        try:
            return self.run(*args)
        except Fail:
            return None

    def commit(self, ref: str) -> str | None:
        out = self.try_run("rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
        return out.strip() if out else None

    def snapshot(self) -> str:
        """The working tree as a tree object: tracked, staged, unstaged and untracked non-ignored
        files. Works on a copy of the index, so neither the working tree nor the real index changes."""
        top = Git(Path(self.run("rev-parse", "--show-toplevel").strip()))
        real = Path(self.run("rev-parse", "--path-format=absolute", "--git-path", "index").strip())
        with tempfile.TemporaryDirectory() as d:
            env = {**os.environ, "GIT_INDEX_FILE": str(Path(d) / "index")}
            seeded = False
            if real.exists():
                # starting from the real index keeps force-added files that .gitignore would skip;
                # copy2 keeps its mtime, which git needs to rehash files edited within the same second
                shutil.copy2(real, Path(d) / "index")
                assumed = [ln[2:] for ln in top.run("ls-files", "-v", "-z", env=env).split("\0") if ln[:1].islower()]
                if assumed:
                    top.run("update-index", "--no-assume-unchanged", "-z", "--stdin", env=env, input="\0".join(assumed))
                seeded = top.try_run_env(env, "add", "-A", "--", ":/") is not None
            if not seeded:
                (Path(d) / "index").unlink(missing_ok=True)
                if self.commit("HEAD"):
                    self.run("read-tree", "HEAD", env=env)
                top.run("add", "-A", "--", ":/", env=env)
            return self.run("write-tree", env=env).strip()

    def try_run_env(self, env: dict, *args: str) -> str | None:
        try:
            return self.run(*args, env=env)
        except Fail:
            return None


# ---------- diff model ----------


@dataclass
class Row:
    kind: str  # " " context, "-" removed, "+" added
    text: str
    old: int | None
    new: int | None
    marks: list[tuple[int, int]] = field(default_factory=list)
    nonl: bool = False  # "\ No newline at end of file" follows this row


@dataclass
class Hunk:
    path: str
    n: int
    header: str
    rows: list[Row]
    new_start: int = 0  # from the @@ line: the first new-side line, or the line before a hunk with none

    @property
    def id(self) -> str:
        return f"{self.path}#h{self.n}"

    @property
    def adds(self) -> int:
        return sum(r.kind == "+" for r in self.rows)

    @property
    def dels(self) -> int:
        return sum(r.kind == "-" for r in self.rows)

    @property
    def hash(self) -> str:
        return rows_hash(self.rows)


@dataclass
class FileDiff:
    path: str
    status: str  # A M D R C T
    old_path: str | None = None
    binary: bool = False
    old_mode: str | None = None
    new_mode: str | None = None
    hunks: list[Hunk] = field(default_factory=list)
    excluded: str | None = None  # why it's outside coverage: tests, lockfiles, generated, or a story reason
    blobs: list[str] = field(default_factory=list)  # "old..new" object ids from the patch's index lines

    @property
    def fingerprint(self) -> str:
        return digest(
            f"{self.status}|{self.old_path}|{self.old_mode}|{self.new_mode}|{self.binary}|{','.join(self.blobs)}|"
            + ",".join(h.hash for h in self.hunks)
        )

    @property
    def adds(self) -> int:
        return sum(h.adds for h in self.hunks)

    @property
    def dels(self) -> int:
        return sum(h.dels for h in self.hunks)

    @property
    def symlink(self) -> bool:
        return "120000" in (self.old_mode, self.new_mode)

    @property
    def submodule(self) -> bool:
        return "160000" in (self.old_mode, self.new_mode)

    @property
    def meta(self) -> str | None:
        """Rename or mode change that comes with the content change, if any."""
        bits = []
        if self.old_path:
            bits.append(f"renamed from {self.old_path}")
        if self.status == "T":
            kind = lambda m: {"120000": "symlink", "160000": "submodule"}.get(m or "", "file")
            bits.append(f"{kind(self.old_mode)} → {kind(self.new_mode)}")
        elif self.old_mode and self.new_mode and self.old_mode != self.new_mode and self.status not in "AD":
            bits.append(f"mode {self.old_mode} → {self.new_mode}")
        return ", ".join(bits) or None

    @property
    def file_level(self) -> bool:
        """Covered as a whole once referenced, rather than line by line (D19)."""
        return (
            self.binary
            or self.symlink
            or self.submodule
            or not self.hunks
            or self.status in ("A", "D")
            or Path(self.path).suffix.lower() in (".md", ".mdx", ".rst", ".adoc")
        )


def digest(s: str) -> str:
    return hashlib.sha1(s.encode()).hexdigest()[:8]


HUNK_RE = re.compile(r"@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@ ?(.*)$")
DIFF_ARGS = (
    "--no-color", "--no-ext-diff", "--no-textconv", "--no-relative", "--submodule=short", "--ignore-submodules=none",
    "-M", "--src-prefix=a/", "--dst-prefix=b/",
)
QUOTE = {"\a": "\\a", "\b": "\\b", "\t": "\\t", "\n": "\\n", "\v": "\\v", "\f": "\\f", "\r": "\\r", '"': '\\"', "\\": "\\\\"}


def git_quote(p: str) -> str:
    """A path as git writes it in a diff header (with core.quotePath=false)."""
    if not any(c in '"\\' or ord(c) < 0x20 or ord(c) == 0x7F for c in p):
        return p
    return '"' + "".join(QUOTE.get(c) or (f"\\{ord(c):03o}" if ord(c) < 0x20 or ord(c) == 0x7F else c) for c in p) + '"'


def parse_diff(g: Git, base: str, head: str, marks: bool = True) -> list[FileDiff]:
    names = g.run("diff", *DIFF_ARGS, "--name-status", "-z", base, head).split("\0")
    files: list[FileDiff] = []
    i = 0
    while i < len(names) and names[i]:
        st = names[i][0]
        if st in "RC":
            files.append(FileDiff(names[i + 2], st, old_path=names[i + 1]))
            i += 3
        else:
            files.append(FileDiff(names[i + 1], st))
            i += 2
    patch = g.run("diff", *DIFF_ARGS, "--no-textconv", "-U3", base, head)
    parts = re.split(r"^(diff --git .*)$\n?", patch, flags=re.M)
    sections: dict[str, list[str]] = {}
    for header, sec in zip(parts[1::2], parts[2::2]):
        sections.setdefault(header, []).append(sec)
    for f in files:
        header = f"diff --git {git_quote('a/' + (f.old_path or f.path))} {git_quote('b/' + f.path)}"
        # a type change (file <-> symlink) comes as two sections: the old one deleted, the new one added
        for sec in sections.pop(header, None) or []:
            parse_section(f, sec)
    if sections:
        raise Fail(f"diff parse mismatch: patch sections without a file: {', '.join(list(sections)[:3])}")
    # only a build shows them, and pairing lines up is the slow part of reading a diff
    for f in files if marks else []:
        for h in f.hunks:
            add_word_marks(h)
    return files


def parse_section(f: FileDiff, sec: str) -> None:
    hunk: Hunk | None = None
    oc = nc = 0
    for line in sec.split("\n"):
        if hunk is None:
            if line.startswith("old mode "):
                f.old_mode = line[9:].strip()
            elif line.startswith("new mode "):
                f.new_mode = line[9:].strip()
            elif line.startswith("new file mode "):
                f.new_mode = line[14:].strip()
            elif line.startswith("deleted file mode "):
                f.old_mode = line[18:].strip()
            elif line.startswith("index "):
                f.blobs.append(line.split()[1])
                if len(line.split()) == 3:
                    f.old_mode = f.new_mode = f.new_mode or line.split()[2]
            elif line.startswith("Binary files ") or line.startswith("GIT binary patch"):
                f.binary = True
        if line.startswith("\\") and hunk is not None and hunk.rows:
            hunk.rows[-1].nonl = True
        elif line.startswith("@@"):
            m = HUNK_RE.match(line)
            if not m:
                continue
            oc, nc = int(m[1]), int(m[2])
            hunk = Hunk(f.path, len(f.hunks) + 1, m[3].strip(), [], nc)
            f.hunks.append(hunk)
        elif hunk is not None and line[:1] in (" ", "-", "+"):
            kind, text = line[0], line[1:]
            if kind == " ":
                hunk.rows.append(Row(kind, text, oc, nc))
                oc, nc = oc + 1, nc + 1
            elif kind == "-":
                hunk.rows.append(Row(kind, text, oc, None))
                oc += 1
            else:
                hunk.rows.append(Row(kind, text, None, nc))
                nc += 1


# ---------- intra-line diff ----------

TOKEN_RE = re.compile(r"\w+|\s+|[^\w\s]")


def tokens(s: str) -> list[tuple[int, int, str]]:
    return [(m.start(), m.end(), m.group()) for m in TOKEN_RE.finditer(s)]


def pair_marks(d: Row, a: Row) -> None:
    ta, tb = tokens(d.text), tokens(a.text)
    sm = difflib.SequenceMatcher(None, [t[2] for t in ta], [t[2] for t in tb], autojunk=False)
    for op, a1, a2, b1, b2 in sm.get_opcodes():
        if op == "equal":
            continue
        if a2 > a1:
            d.marks.append((ta[a1][0], ta[a2 - 1][1]))
        if b2 > b1:
            a.marks.append((tb[b1][0], tb[b2 - 1][1]))
    for r in (d, a):
        r.marks = [(s, e) for s, e in r.marks if r.text[s:e].strip()]
        # a mostly rewritten line reads better without marks
        if sum(e - s for s, e in r.marks) > 0.6 * max(len(r.text.strip()), 1):
            r.marks = []


LONG = 200  # characters; past this a line is compared by word, since comparing by character is quadratic
PAIR_MAX = 250_000  # words in one line times words in the other; past this a pair goes without word marks


def closeness(a: str, b: str, floor: float) -> float:
    """How alike two lines are, from 0 to 1; 0 unless they beat `floor`."""
    if len(a) > LONG or len(b) > LONG:
        a, b = TOKEN_RE.findall(a), TOKEN_RE.findall(b)
        if len(a) * len(b) > PAIR_MAX:
            return 0
    sm = difflib.SequenceMatcher(None, a, b, autojunk=False)
    # the quick ratios are upper bounds, so most pairs never reach the real one
    if sm.real_quick_ratio() <= floor or sm.quick_ratio() <= floor:
        return 0
    ratio = sm.ratio()
    return ratio if ratio > floor else 0


def add_word_marks(h: Hunk) -> None:
    """Mark changed words only on removed/added lines that pair up closely, to avoid confetti."""
    rows, i = h.rows, 0
    while i < len(rows):
        if rows[i].kind != "-":
            i += 1
            continue
        j = i
        while j < len(rows) and rows[j].kind == "-":
            j += 1
        k = j
        while k < len(rows) and rows[k].kind == "+":
            k += 1
        dels, adds, p = rows[i:j], rows[j:k], 0
        for d in dels:
            best = None
            for q in range(p, len(adds)):
                ratio = closeness(d.text, adds[q].text, best[0] if best else 0.5)
                if ratio:
                    best = (ratio, q)
            if best:
                pair_marks(d, adds[best[1]])
                p = best[1] + 1
        i = max(k, j)


# ---------- what stays outside coverage (D13) ----------

DEFAULT_EXCLUDES = {
    "tests": [
        "tests/*", "test/*", "__tests__/*", "spec/*", "*/tests/*", "*/test/*", "*/__tests__/*", "*/spec/*",
        "*/__snapshots__/*", "*_test.go", "*_test.py", "test_*.py", "*.test.*", "*.spec.*", "*.snap",
    ],
    "lockfiles": [
        "*.lock", "*.lockb", "package-lock.json", "npm-shrinkwrap.json", "pnpm-lock.yaml", "go.sum",
        ".terraform.lock.hcl",
    ],
    "generated": ["*.min.js", "*.min.css", "*.pb.go", "*_pb2.py", "*_pb2.pyi", "*.generated.*"],
}
GROUP_TITLES = {"tests": "Tests", "lockfiles": "Lockfiles", "generated": "Generated"}


def glob_match(path: str, pattern: str) -> bool:
    # a pattern without "/" matches the file name in any directory; "*" crosses "/"
    return fnmatch(path, pattern) if "/" in pattern else fnmatch(path.rsplit("/", 1)[-1], pattern)


def generated_by_attr(g: Git, tree: str, paths: list[str], worktree: bool) -> set[str]:
    """linguist-generated as .gitattributes says at the indexed head (a commit or the snapshot tree)."""
    if not paths:
        return set()
    out = g.try_run("check-attr", "-z", f"--source={tree}", "linguist-generated", "--", *paths)
    if out is None:
        # git before 2.40 has no --source; on-disk attributes are only right for a working-tree story
        out = (g.try_run("check-attr", "-z", "linguist-generated", "--", *paths) if worktree else None) or ""
    parts = out.split("\0")
    return {parts[i] for i in range(0, len(parts) - 2, 3) if parts[i + 2] in ("set", "true")}


def default_exclusion(path: str, generated: set[str]) -> str | None:
    if path in generated:
        return "generated"
    for group, globs in DEFAULT_EXCLUDES.items():
        if any(glob_match(path, p) for p in globs):
            return group
    return None


# ---------- highlighting ----------


def css_class(tt) -> str:
    while tt not in STANDARD_TYPES:
        tt = tt.parent
    return STANDARD_TYPES[tt]


CR, BOM = "\ue000", "\ue001"


class Source:
    """File text at a commit or tree, highlighted once per (sha, path)."""

    def __init__(self, g: Git) -> None:
        self.g = g
        self.batch: subprocess.Popen | None = None

    @cache
    def text(self, sha: str, path: str) -> str | None:
        # the batch protocol is a line per request, and git drops a carriage return at the end of one
        if "\n" in path or path.endswith("\r"):
            return self.g.try_run("cat-file", "blob", f"{sha}:{path}")
        # one git process answers every read; a story touches dozens of files
        if self.batch is None:
            self.batch = subprocess.Popen(
                ["git", "-C", str(self.g.repo), *GIT_CONFIG, "cat-file", "--batch"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
            )
        self.batch.stdin.write(f"{sha}:{path}\n".encode())
        self.batch.stdin.flush()
        head = self.batch.stdout.readline().split()
        if len(head) < 3 or head[-1] == b"missing" or not head[-1].isdigit():
            return None
        data = self.batch.stdout.read(int(head[-1]) + 1)[:-1]
        return data.decode("utf-8", errors="replace") if head[-2] == b"blob" else None

    @cache
    def raw(self, sha: str, path: str) -> list[str] | None:
        """git's lines, split on \\n only; a trailing \\r stays part of the line."""
        text = self.text(sha, path)
        if text is None:
            return None
        lines = text.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        return lines

    @cache
    def lines(self, sha: str, path: str) -> list[list[tuple[str, str]]] | None:
        """Highlighted tokens per git line, without the line's trailing \\r."""
        raw = self.raw(sha, path)
        if raw is None:
            return None
        try:
            lexer = get_lexer_for_filename(path, stripnl=False, ensurenl=False)
        except ClassNotFound:
            lexer = TextLexer(stripnl=False, ensurenl=False)
        # Pygments turns \r into \n and drops a BOM; stand-ins keep its lines aligned with git's
        text = "\n".join(l.removesuffix("\r").replace("\r", CR).replace("\ufeff", BOM) for l in raw)
        # some lexers only recognise a construct on the last line when its newline is there
        text += "\n" if self.text(sha, path).endswith("\n") else ""
        lines: list[list[tuple[str, str]]] = [[]]
        for tt, val in lexer.get_tokens(text):
            cls = css_class(tt)
            for i, part in enumerate(val.split("\n")):
                if i:
                    lines.append([])
                if part:
                    lines[-1].append((cls, part.replace(CR, "\r").replace(BOM, "\ufeff")))
        del lines[len(raw):]
        lines += [[] for _ in range(len(raw) - len(lines))]
        return lines


@dataclass
class TreeEntry:
    path: str
    kind: str  # dir, file, link, module
    level: int  # 1 for the listed directory's own entries
    oid: str
    files: int = 0  # a dir's files, at any depth

    @property
    def name(self) -> str:
        return self.path.rpartition("/")[2]


def tree_entries(g: Git, sha: str, path: str, depth: int) -> tuple[list[TreeEntry], int] | None:
    """A directory at sha, `depth` levels deep, dirs first; and how many files it holds. None if path isn't a directory."""
    path = posixpath.normpath(path.strip("/") or ".")
    path = "" if path == "." else path
    if path and (g.try_run("cat-file", "-t", f"{sha}:{path}") or "").strip() != "tree":
        return None
    out = g.run("ls-tree", "-r", "-t", "-z", "--full-tree", f"{sha}:{path}" if path else sha)
    recs = []
    for rec in filter(None, out.split("\0")):
        meta, _, rel = rec.partition("\t")
        mode, typ, oid = meta.split(" ")
        recs.append((rel, "dir" if typ == "tree" else "module" if typ == "commit" else "link" if mode == "120000" else "file", oid))
    counts: dict[str, int] = {}
    for rel, kind, _ in recs:
        if kind != "dir":
            parts = rel.split("/")
            for i in range(1, len(parts)):
                counts["/".join(parts[:i])] = counts.get("/".join(parts[:i]), 0) + 1
    order = lambda rk: [(i == rk[0].count("/") and rk[1] != "dir", p.lower(), p) for i, p in enumerate(rk[0].split("/"))]
    entries = [
        TreeEntry(f"{path}/{rel}" if path else rel, kind, rel.count("/") + 1, oid, counts.get(rel, 0))
        for rel, kind, oid in sorted(recs, key=order)
        if rel.count("/") < depth
    ]
    return entries, sum(kind != "dir" for _, kind, _ in recs)


BIG = 2_000_000  # bytes; bigger files show their size, so a listing never reads them


def blob_lines(g: Git, entries: list[TreeEntry]) -> dict[str, int | str | None]:
    """Line counts of the listed files, by blob id: None for binaries, a size for big files."""
    files = [e for e in entries if e.kind == "file"]
    if not files:
        return {}
    sizes = subprocess.run(
        ["git", "-C", str(g.repo), *GIT_CONFIG, "cat-file", "--batch-check=%(objectsize)"],
        input="".join(f"{e.oid}\n" for e in files).encode(),
        capture_output=True,
    ).stdout.split()
    res: dict[str, int | str | None] = {e.path: f"{int(n) / 1e6:.0f} MB" for e, n in zip(files, sizes) if int(n) > BIG}
    files = [e for e in files if e.path not in res]
    out = subprocess.run(
        ["git", "-C", str(g.repo), *GIT_CONFIG, "cat-file", "--batch"],
        input="".join(f"{e.oid}\n" for e in files).encode(),
        capture_output=True,
    ).stdout
    i = 0
    for e in files:
        nl = out.find(b"\n", i)
        head, i = out[i:nl].split(), nl + 1
        size = int(head[2])
        data = out[i : i + size]
        i += size + 1
        res[e.path] = None if b"\0" in data[:8000] else data.count(b"\n") + (bool(data) and not data.endswith(b"\n"))
    return res


def tree_text(entries: list[TreeEntry], lines: dict[str, int | str | None]) -> list[tuple[TreeEntry, str, str]]:
    """Each entry with its display name and what it holds."""
    out = []
    for e in entries:
        if e.kind == "dir":
            count = f"{e.files} file" + ("" if e.files == 1 else "s")
        elif e.kind == "file":
            n = lines.get(e.path)
            count = "binary" if n is None else n if isinstance(n, str) else f"{n} line" + ("" if n == 1 else "s")
        else:
            count = "symlink" if e.kind == "link" else "submodule"
        out.append((e, e.name + ("/" if e.kind == "dir" else ""), count))
    return out


# ---------- index ----------


def gh_remote(g: Git) -> tuple[str, str] | None:
    url = g.try_run("remote", "get-url", "origin") or ""
    m = re.search(r"github\.com[:/]([^/\s]+)/([^/\s]+?)(?:\.git)?/?$", url.strip())
    return (m[1], m[2]) if m else None


def ignored(g: Git, path: Path) -> bool:
    return subprocess.run(["git", "-C", str(g.repo), "check-ignore", "-q", str(path)], capture_output=True).returncode == 0


def pr_meta(repo: Path, url: str) -> dict:
    p = subprocess.run(
        ["gh", "pr", "view", url, "--json", "number,title,body,url,baseRefName,baseRefOid,headRefName,headRefOid"],
        capture_output=True,
        cwd=repo,
    )
    if p.returncode != 0:
        raise Fail(f"gh pr view failed: {p.stderr.decode(errors='replace').strip()}")
    return json.loads(p.stdout)


def default_base(g: Git) -> str:
    sym = g.try_run("symbolic-ref", "--quiet", "--short", "refs/remotes/origin/HEAD")
    for ref in ([sym.strip()] if sym else []) + ["origin/main", "origin/master", "main", "master"]:
        if g.commit(ref):
            return ref
    raise Fail("no base found; pass --base")


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def pushed(g: Git, sha: str) -> bool:
    return bool((g.try_run("for-each-ref", "--count=1", f"--contains={sha}", "refs/remotes") or "").strip())


def cmd_index(a: argparse.Namespace) -> None:
    if a.tour and (a.pr or a.base):
        raise Fail("a tour shows the code at one commit; --pr and --base are for stories about a change")
    repo = Path(a.repo).expanduser().resolve()
    g = Git(repo)
    g.run("rev-parse", "--git-dir")
    remote = gh_remote(g)
    pr = pr_meta(repo, a.pr) if a.pr else None
    if pr:
        m = re.search(r"github\.com/([^/]+)/([^/]+)/pull/\d+", pr["url"])
        remote = (m[1], m[2]) if m else remote

    head_ref = a.head or (pr["headRefOid"] if pr else "HEAD")
    if pr and not a.head and not g.commit(head_ref):
        raise Fail(
            f"The PR head {head_ref[:7]} isn't in this clone. code-story doesn't fetch; "
            f"fetch it first (e.g. git fetch origin pull/{pr['number']}/head) and run index again."
        )
    worktree = head_ref == WORKTREE
    head_commit = g.commit("HEAD" if worktree else head_ref)
    if not head_commit and not (a.tour and worktree):
        if head_ref in ("HEAD", WORKTREE) and not g.commit("HEAD"):
            raise Fail(
                "this repo has no commits yet; tour the working tree with --head WORKTREE"
                if a.tour else "this repo has no commits yet; code-story needs a base commit to compare against"
            )
        raise Fail(f"head {head_ref!r} is not a commit in {repo}")

    out = Path(a.out).expanduser().resolve() if a.out else None
    if worktree and out:
        top = Path(g.run("rev-parse", "--show-toplevel").strip()).resolve()
        if out.is_relative_to(top) and not ignored(g, out):
            raise Fail(f"--out {out} is inside the repo, so the story's own files would join the working-tree snapshot; pick a folder outside it")
    head = g.snapshot() if worktree else head_commit

    if a.tour:
        base_ref = base = mb = None
        files: list[FileDiff] = []
    else:
        if a.base:
            base_ref, base = a.base, g.commit(a.base)
        elif pr and g.commit(pr.get("baseRefOid") or "-"):
            # GitHub's own base commit for this PR: right even when the local base branch moved or the PR is merged
            base_ref, base = pr["baseRefName"], pr["baseRefOid"]
        else:
            if pr and pr.get("baseRefOid"):
                print(
                    f"note: the PR's base commit {pr['baseRefOid'][:7]} isn't in this clone; comparing against the local "
                    f"{pr['baseRefName']} instead, which can differ from GitHub's diff. Fetch it to match.",
                    file=sys.stderr,
                )
            base_ref = next((r for r in ([f"origin/{pr['baseRefName']}", pr["baseRefName"]] if pr else []) if g.commit(r)), None)
            base_ref = base_ref or default_base(g)
            base = g.commit(base_ref)
        if not base:
            raise Fail(f"base {base_ref!r} is not a commit in {repo}")
        mb = g.run("merge-base", base, head_commit).strip()

        files = parse_diff(g, mb, head, marks=False)
        if not files:
            raise Fail(f"no changes between {base_ref} and {head_ref}")
        generated = generated_by_attr(g, head, [f.path for f in files], worktree)
        for f in files:
            f.excluded = default_exclusion(f.path, generated)

    branch = (g.try_run("rev-parse", "--abbrev-ref", "HEAD") or "").strip() if head_ref in ("HEAD", WORKTREE) else ""
    branch = "" if branch == "HEAD" else branch
    if a.tour:
        label = "tour"
    elif pr:
        label = f"pr-{pr['number']}"
    elif branch:
        label = slug(branch)
    else:
        label = head_commit[:7] if head_ref in ("HEAD", WORKTREE) or g.commit(head_ref) == head_ref else slug(head_ref)
    if worktree and not a.tour:
        label = f"{label}-worktree"
    owner, name = remote or ("local", repo.name)
    out = out or HOME / owner / name / label
    out.mkdir(parents=True, exist_ok=True)

    idx = {
        "version": 1,
        "created": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "repo": str(repo),
        "owner": owner if remote else None,
        "name": name,
        "pr": {k: pr[k] for k in ("number", "title", "body", "url", "baseRefName", "headRefName")} if pr else None,
        "base_ref": base_ref,
        "base": base,
        "merge_base": mb,
        "head_ref": head_ref,
        "head": head,
        "head_commit": head_commit,
        "worktree": worktree,
        "tour": bool(a.tour),
        "branch": branch or None,
        "files": [
            {
                "path": f.path,
                "old_path": f.old_path,
                "status": f.status,
                "binary": f.binary,
                "old_mode": f.old_mode,
                "new_mode": f.new_mode,
                "adds": f.adds,
                "dels": f.dels,
                "excluded": f.excluded,
                "hunks": [
                    {"id": h.id, "header": h.header, "adds": h.adds, "dels": h.dels, "rows": len(h.rows), "hash": h.hash}
                    for h in f.hunks
                ],
            }
            for f in files
        ],
    }
    (out / "index.json").write_text(json.dumps(idx, indent=1))
    print_tour(idx, g, out) if a.tour else print_index(idx, files, out)


def print_tour(idx: dict, g: Git, out: Path) -> None:
    head = "working tree (snapshot)" if idx["worktree"] else idx["head"][:7]
    print(f"repo      {idx['owner'] or 'local'}/{idx['name']}  ({idx['repo']})")
    print(f"tour at   {head}" + (f"  ({idx['branch']})" if idx["branch"] else ""))
    print(f"story     {out}/   <- write story.md here, then: build {out}")
    entries, total = tree_entries(g, idx["head"], "", 2)
    print(f"{total} files\n")
    for e, name, count in tree_text(entries[:150], {}):
        print("  " * (e.level - 1) + name + (f"  {count}" if e.kind == "dir" else ""))
    if len(entries) > 150:
        print(f"… {len(entries) - 150} more; list a directory with: show {out} DIR@head")


def print_index(idx: dict, files: list[FileDiff], out: Path) -> None:
    adds = sum(f.adds for f in files)
    dels = sum(f.dels for f in files)
    head = "working tree (snapshot)" if idx["worktree"] else idx["head"][:7]
    print(f"repo      {idx['owner'] or 'local'}/{idx['name']}  ({idx['repo']})")
    if idx["pr"]:
        print(f"pr        #{idx['pr']['number']} {idx['pr']['title']}  {idx['pr']['url']}")
    print(f"base      {idx['base_ref']} {idx['base'][:7]}  (merge-base {idx['merge_base'][:7]})")
    print(f"head      {head}" + (f"  ({idx['head_ref']})" if idx["head_ref"] not in (idx["head"], WORKTREE) else ""))
    print(f"story     {out}/   <- write story.md here, then: build {out}")
    excl = [f for f in files if f.excluded]
    print(f"{len(files)} files  +{adds} −{dels}   ({len(excl)} not in story by default)\n")
    for f in files:
        if f.excluded:
            continue
        print_file(f)
    if excl:
        print("\nNot in story by default (tests, lockfiles, generated); bring one into coverage with `include:`")
        for f in excl:
            print(f"  {f.path}  [{f.status}] +{f.adds} −{f.dels}  ({f.excluded})")
    if idx["pr"] and (idx["pr"].get("body") or "").strip():
        print("\nPR description (intent; check it against the code):\n")
        print(idx["pr"]["body"].strip())


def print_file(f: FileDiff) -> None:
    flags = [x for x, on in (("binary", f.binary), ("symlink", f.symlink), ("submodule", f.submodule)) if on]
    if f.old_mode and f.new_mode and f.old_mode != f.new_mode and f.status not in "AD":
        flags.append(f"mode {f.old_mode}->{f.new_mode}")
    if f.old_path:
        flags.append(f"from {f.old_path}")
    if f.file_level:
        flags.append("covered as a whole")
    tail = f"  ({', '.join(flags)})" if flags else ""
    print(f"{f.path}  [{f.status}] +{f.adds} −{f.dels}{tail}")
    for h in f.hunks:
        first = next((r for r in h.rows if r.kind != " "), h.rows[0])
        print(f"  {h.id:<44} +{h.adds:<3} −{h.dels:<3} {h.header[:36]:<36} | {first.kind}{first.text.strip()[:56]}")


# ---------- loading an indexed story ----------


@dataclass
class Indexed:
    dir: Path
    idx: dict
    g: Git
    files: list[FileDiff]
    src: Source

    @property
    def hunks(self) -> dict[str, Hunk]:
        return {h.id: h for f in self.files for h in f.hunks}

    def file(self, path: str) -> FileDiff | None:
        return next((f for f in self.files if f.path == path), None)


def load(dir_: str, verify: bool = True, marks: bool = True) -> Indexed:
    d = Path(dir_).expanduser().resolve()
    p = d / "index.json"
    if not p.exists():
        raise Fail(f"{p} not found; run index first")
    idx = json.loads(p.read_text())
    g = Git(Path(idx["repo"]))
    if verify and idx["worktree"] and g.snapshot() != idx["head"]:
        raise Fail("the working tree changed since index; run index again so the story shows what's on disk now")
    if idx.get("tour"):
        return Indexed(d, idx, g, [], Source(g))
    files = parse_diff(g, idx["merge_base"], idx["head"], marks)
    by_path = {f["path"]: f for f in idx["files"]}
    if set(by_path) != {f.path for f in files}:
        changed = sorted(set(by_path) ^ {f.path for f in files})
        raise Fail(f"the diff no longer has the files index.json lists ({', '.join(changed[:3])}); run index again")
    for f in files:
        rec = by_path[f.path]
        now = (f.status, f.old_path, f.binary, f.old_mode, f.new_mode, [h.hash for h in f.hunks])
        then = (rec["status"], rec["old_path"], rec["binary"], rec["old_mode"], rec["new_mode"], [h["hash"] for h in rec["hunks"]])
        if now != then:
            raise Fail(f"{f.path} no longer matches index.json; run index again")
        f.excluded = rec["excluded"]
    return Indexed(d, idx, g, files, Source(g))


def cmd_show(a: argparse.Namespace) -> None:
    ix = load(a.dir, verify=False, marks=False)
    hunks = ix.hunks
    specs = list(a.spec)
    while specs:
        spec = specs.pop(0)
        if spec in hunks:
            show_hunk(hunks[spec])
        elif ls := parse_lines_spec([spec] + specs[:1]):
            path, side, rng = ls
            if rng and ":" not in spec:
                specs.pop(0)
            if side == "base" and ix.idx.get("tour"):
                raise Fail(f"a tour has no base; read {path}@head")
            sha = ix.idx["head"] if side == "head" else ix.idx["merge_base"]
            lines = ix.src.raw(sha, path)
            if lines is None and not rng and (tree := tree_entries(ix.g, sha, path, 1)):
                entries, total = tree
                found = tree_text(entries, blob_lines(ix.g, entries))
                print(f"{path}@{side}  {total} files")
                for e, name, count in found:
                    print(f"  {name:<40} {count}")
                print()
                continue
            if lines is None:
                raise Fail(missing(ix, sha, path, side))
            a_, b_ = rng or (1, len(lines))
            if rng and not 1 <= a_ <= b_ <= len(lines):
                raise Fail(f"{path}@{side} has {len(lines)} lines; {span(a_, b_)} is out of range")
            print(f"{path}@{side}  " + (f"L{a_}-{b_}" if lines else "(empty)"))
            for n in range(a_, b_ + 1):
                print(f"{n:>6}  {lines[n - 1]}")
        elif f := ix.file(spec):
            print_file(f)
            for h in f.hunks:
                show_hunk(h)
        else:
            close = difflib.get_close_matches(spec, list(hunks) + [f.path for f in ix.files], n=3)
            hint = f"; in a tour, read a file as {spec}@head or a directory as {spec}@head" if ix.idx.get("tour") else ""
            raise Fail(f"unknown spec {spec!r}" + (f"; did you mean {', '.join(close)}?" if close else hint))
        print()


def parse_lines_spec(args: list[str]) -> tuple[str, str, tuple[int, int] | None] | None:
    """`path@head 10-40`, `path@head:10-40`, `path@base 12`: path, side and an optional line range."""
    m = re.fullmatch(r"(.+)@(head|base)(?::(\d+)(?:-(\d+))?)?", args[0]) if args else None
    if not m:
        return None
    if m[3]:
        a, b = m[3], m[4]
    elif len(args) > 1 and (r := re.fullmatch(r"(\d+)(?:-(\d+))?", args[1])):
        a, b = r[1], r[2]
    else:
        return m[1], m[2], None
    return m[1], m[2], (int(a), int(b or a))


def span(a: int, b: int) -> str:
    return str(a) if a == b else f"{a}-{b}"


def missing(ix: Indexed, sha: str, path: str, side: str) -> str:
    kind = (ix.src.g.try_run("cat-file", "-t", f"{sha}:{path}") or "").strip()
    if kind == "tree":
        return f"{path} is a directory at {side}; @ctx reads files, @tree lists directories"
    if kind == "commit" or ix.src.g.try_run("ls-tree", "--full-tree", sha, "--", path.rstrip("/")):
        return f"{path} is a submodule at {side}; its code lives in another repo"
    return f"{path} doesn't exist at {side}" + rename_hint(ix.files, path, side)


def rename_hint(files: list[FileDiff], path: str, side: str) -> str:
    f = next((f for f in files if f.path == path and f.old_path), None)
    return f"; at base it was {f.old_path}" if f and side == "base" else ""


def show_hunk(h: Hunk) -> None:
    print(f"{h.id}  {h.header}  +{h.adds} −{h.dels}  ({len(h.rows)} rows; rows=a-b counts these)")
    print("   row   old   new")
    for i, r in enumerate(h.rows, 1):
        print(f"{i:>6} {r.old or '':>5} {r.new or '':>5} {r.kind} {r.text}" + ("  [no newline at end of file]" if r.nonl else ""))


# ---------- story.md ----------

KW_RE = re.compile(r"^(rows|id|title|label|note|depth)=(.*)$", re.S)
DIRECTIVES = ("diff", "ctx", "ripple", "also", "tree")
BOXES = ("step", "card", "fork", "branch", "note", "sketch")
NOTE_KINDS = ("note", "mismatch", "question", "finding", "external", "symlink")
REVIEW_NOTES = ("mismatch", "question", "finding")


@dataclass
class Item:
    kind: str  # md, dir, h1, h2, box
    line: int
    text: str = ""
    name: str = ""
    args: list[str] = field(default_factory=list)
    kw: dict[str, str] = field(default_factory=dict)
    children: list[Item] = field(default_factory=list)
    raw: list[str] = field(default_factory=list)


def split_args(raw: str, line: int) -> tuple[list[str], dict[str, str]]:
    try:
        toks = shlex.split(raw)
    except ValueError as e:
        raise Fail(
            f"story.md:{line}: can't read the arguments ({e}). Put a value with spaces or an apostrophe in "
            'double quotes, e.g. title="it\'s the key"'
        )
    args, kw = [], {}
    for t in toks:
        if m := KW_RE.match(t):
            kw[m[1]] = m[2]
        else:
            args.append(t)
    return args, kw


FRONT_KEYS = ("title", "map", "traces", "exclude", "include")


def check_front(front) -> tuple[list[str], list[str]]:
    """Shape errors and unknown-key warnings for the front matter, so neither check nor build can trip on it."""
    errs, warns = [], []
    if not isinstance(front, dict):
        return ["front matter: must be a mapping of keys (title, map, traces, exclude, include)"], []
    is_str = lambda v: isinstance(v, (str, int, float))
    for k in front:
        if k not in FRONT_KEYS:
            close = difflib.get_close_matches(str(k), FRONT_KEYS, n=1)
            warns.append(f"front matter: unknown key {k!r}" + (f"; did you mean {close[0]!r}?" if close else ""))
    if "title" in front and not is_str(front["title"]):
        errs.append("front matter: title is a string")
    m = front.get("map")
    if m is not None and not (isinstance(m, dict) and all(k in ("title", "subtitle") and is_str(v) for k, v in m.items())):
        errs.append("front matter: map has a title and an optional subtitle, e.g. map: {title: Request flow, subtitle: …}")
    tr = front.get("traces")
    if tr is not None and not (
        isinstance(tr, dict) and all(isinstance(v, str) or (isinstance(v, list) and all(isinstance(x, str) for x in v)) for v in tr.values())
    ):
        errs.append("front matter: traces maps a name to a list of identifiers, e.g. user id: [user_id, USER_ID]")
    ex = front.get("exclude")
    if ex is not None and not (isinstance(ex, list) and all(isinstance(r, dict) and isinstance(r.get("path"), str) and isinstance(r.get("reason"), str) and r["reason"].strip() for r in ex)):
        errs.append("front matter: exclude is a list of {path: glob, reason: why}, and every entry needs a reason")
    inc = front.get("include")
    if inc is not None and not (isinstance(inc, list) and all(isinstance(x, str) for x in inc)):
        errs.append("front matter: include is a list of globs")
    return errs, warns


def parse_story(text: str) -> tuple[dict, list[Item]]:
    lines = text.split("\n")
    front: dict = {}
    start = 0
    if lines and lines[0].strip() == "---":
        end = next((i for i in range(1, len(lines)) if lines[i].strip() == "---"), None)
        if end is None:
            raise Fail("story.md: front matter opened with --- but never closed")
        try:
            front = yaml.safe_load("\n".join(lines[1:end])) or {}
        except yaml.YAMLError as e:
            raise Fail(f"story.md: front matter isn't valid YAML: {e}")
        start = end + 1
    root = Item("box", 0, name="root")
    stack = [root]
    md: list[str] = []
    md_line = start + 1
    fence: str | None = None

    def flush() -> None:
        nonlocal md
        if any(x.strip() for x in md):
            stack[-1].children.append(Item("md", md_line, text="\n".join(md)))
        md = []

    for i in range(start, len(lines)):
        ln, s = i + 1, lines[i]
        top = stack[-1]
        if top.name == "sketch" and s.strip() != ":::":
            top.raw.append(s)
            continue
        if fence:
            md.append(s)
            if re.fullmatch(rf" {{0,3}}{re.escape(fence[0])}{{{len(fence)},}}[ \t]*", s):
                fence = None
            continue
        if m := re.match(r"^ {0,3}(`{3,}(?=[^`]*$)|~{3,})", s):
            if not md:
                md_line = ln
            fence = m[1]
            md.append(s)
            continue
        if s.strip() == ":::":
            flush()
            if len(stack) == 1:
                raise Fail(f"story.md:{ln}: ':::' closes nothing")
            stack.pop()
            md_line = ln + 1
            continue
        if m := re.match(r"^:::\s*(\w+)\s*(.*)$", s):
            flush()
            if m[1] not in BOXES:
                raise Fail(f"story.md:{ln}: unknown block '::: {m[1]}' (blocks: {', '.join(BOXES)})")
            box = Item("box", ln, name=m[1], text=m[2].strip())
            top.children.append(box)
            stack.append(box)
            md_line = ln + 1
            continue
        if m := re.match(r"^@(\w+)\b\s*(.*)$", s):
            flush()
            if m[1] not in DIRECTIVES:
                raise Fail(
                    f"story.md:{ln}: unknown directive '@{m[1]}' (directives: {', '.join(DIRECTIVES)}). "
                    "To start a line of prose with @, write \\@"
                )
            args, kw = split_args(m[2], ln)
            top.children.append(Item("dir", ln, name=m[1], args=args, kw=kw))
            md_line = ln + 1
            continue
        if m := re.match(r"^(#{1,2})\s+(.*?)\s*(?:\{([^{}]*)\})?\s*$", s):
            flush()
            if len(stack) > 1:
                raise Fail(f"story.md:{ln}: heading inside '::: {stack[-1].name}' (line {stack[-1].line}); close it first")
            args, kw = split_args(m[3] or "", ln)
            attrs = dict(kw)
            for t in args:
                if t.startswith("#"):
                    attrs["id"] = t[1:]
                elif t.startswith("."):
                    attrs.setdefault("class", []).append(t[1:])
                elif "=" in t:
                    k, v = t.split("=", 1)
                    attrs[k] = v
            item = Item("h1" if m[1] == "#" else "h2", ln, text=m[2])
            item.kw = attrs
            root.children.append(item)
            md_line = ln + 1
            continue
        if not md:
            md_line = ln
        md.append(s)
    flush()
    if len(stack) > 1:
        raise Fail(f"story.md:{stack[-1].line}: '::: {stack[-1].name}' is never closed")
    return front, root.children


# ---------- rendering ----------

SIGN = {" ": " ", "-": "-", "+": "+"}
KIND = {" ": "c", "-": "d", "+": "a"}
X_SVG = '<svg viewBox="0 0 12 12" aria-hidden="true"><path d="M4 4l4 4M8 4l-4 4"/></svg>'
FORK_SVG = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 2v6c0 2 1.5 3 4 3h4M10 9l2 2-2 2"/></svg>'
SYNTAX_DEFAULT = "github-dark"
SYNTAX_THEMES = {
    "github-dark": "GitHub Dark", "one-dark": "One Dark", "dracula": "Dracula", "monokai": "Monokai",
    "night-owl": "Night Owl", "nord": "Nord", "gruvbox-dark": "Gruvbox Dark", "solarized-dark": "Solarized Dark",
    "material": "Material", "lightbulb": "Lightbulb", "native": "Native", "zenburn": "Zenburn",
}


def syntax_themes_css() -> str:
    """Token colours per theme, scoped to body[data-syn]; backgrounds and borders are dropped so the
    diff tints and glass stay the page's own."""
    out = []
    for name in SYNTAX_THEMES:
        sel = f'body[data-syn="{name}"]'
        for line in HtmlFormatter(style=name).get_style_defs("X").splitlines():
            if not line.startswith("X ") or ".hll" in line:
                continue
            rule = re.sub(r"/\*.*?\*/", "", line).strip()
            rule = re.sub(r"(background(-color)?|border):[^;}]+;?\s*", "", rule)
            if rule.startswith("X {"):
                if c := re.search(r"color:\s*([^;}]+)", rule):
                    out.append(f"{sel} :is(.row, .half) code {{ color: {c[1].strip()} }}")
            elif re.search(r"\{\s*\S", rule):
                out.append(f"{sel} code{rule[1:]}")
    return "\n".join(out)


PAGE_IDS = {"files", "side", "map", "help", "trace-pop", "syn-pick", "not-in-story", "def"}


def reserved(i: str) -> bool:
    return i in PAGE_IDS or i.startswith(("fd-", "br-"))


def url_attr(name: str, url: str | None) -> str:
    return f' {name}="{esc(url)}"' if url else ""


def rows_hash(rows: list[Row]) -> str:
    # rows start with " ", "-" or "+", so the marker line can't be mistaken for one
    return digest("".join(f"{r.kind}{r.text}\n" + ("\\ No newline\n" if r.nonl else "") for r in rows))


def esc(s: str) -> str:
    return html.escape(s, quote=True)


def pin_indent(h: str) -> str:
    # indentation as no-break spaces, so a long first token wraps mid-token instead of leaving the line blank
    out, i = [], 0
    while i < len(h):
        if h[i] == "<":
            j = h.index(">", i) + 1
            out.append(h[i:j])
            i = j
        elif h[i] == " ":
            out.append(" ")
            i += 1
        else:
            break
    return "".join(out) + h[i:]


def code_open(text: str) -> str:
    # leading spaces, so wrapped continuation lines hang under the code
    ind = len(text) - len(text.lstrip(" "))
    return f'<code style="--i:{ind}">' if ind else "<code>"


def path_html(path: str) -> str:
    d, _, b = path.rpartition("/")
    d = f'<span class="dir">{esc(d).replace("/", "/<wbr>")}/<wbr></span>' if d else ""
    return f'<span class="path">{d}{esc(b)}</span>'


def stat_html(adds: int, dels: int) -> str:
    return f'<span class="stat"><span class="s-add">+{adds}</span><span class="s-del">−{dels}</span></span>'


FOLD_MAX = 1_500_000  # bytes; a bigger file keeps its frames, but the page can't unfold the rest of it


@dataclass
class Seq:
    """A file as one run of rows the page can unfold: its diff with every unchanged line in place, or the plain file."""

    i: int  # position in the page's list of sources
    path: str
    rows: list[Row] = field(default_factory=list)
    hunks: list[tuple[int, int, int, int]] = field(default_factory=list)  # first row, rows, old and new line it opens at
    full: bool = True  # the unchanged lines are in; without them the page can only fill in the hunks
    sha: str | None = None  # a plain file's commit; a diff reads both sides

    def start(self, h: Hunk) -> int:
        return self.hunks[h.n - 1][0]


def gap(label: str, at: int | None = None, fill: int | None = None) -> str:
    """A break between shown rows. `at` is the next row's place in the file's Seq, so the page knows what the
    break hides; `fill` asks the page to put that many rows after it."""
    attr = ("" if at is None else f' data-at="{at}"') + ("" if fill is None else f' data-len="{fill}"')
    return f'<div class="gap"{attr}><span>{label}</span></div>'


def gap_label(prev: list[Row], nxt: list[Row], skipped: bool = False) -> str:
    # numbered on the new side, so a removed row next to the gap can't skew it
    a = max((r.new for r in prev if r.new), default=0) + 1
    b = min((r.new for r in nxt if r.new), default=a) - 1
    what = "not shown" if skipped else "unchanged"
    return f"line {a} {what}" if a == b else f"lines {a}–{b} {what}" if b > a else ""


# ---------- definitions (D43) ----------

DEF_ROWS = 120  # rows a definition opens with; the rest of its file unfolds from there
OUT_ROWS, OUT_FILES, OUT_FILE_ROWS = 3000, 60, 600  # what a page packs of dbt files from outside the change
CODE = {  # suffix -> the languages whose names can mean each other's definitions
    **dict.fromkeys((".py", ".pyi"), "py"),
    **dict.fromkeys((".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts"), "js"),
    **dict.fromkeys((".c", ".h", ".cc", ".cpp", ".hpp"), "c"),
    **dict.fromkeys((".kt", ".kts"), "kt"),
    **dict.fromkeys((".ex", ".exs"), "ex"),
    **{x: x for x in (".go", ".rs", ".java", ".rb", ".php", ".cs", ".swift", ".scala")},
}
DEF_KINDS = {
    **dict.fromkeys(("def", "function", "func", "fn", "fun", "defp", "defmacro"), "func"),
    **dict.fromkeys(
        ("class", "struct", "enum", "trait", "interface", "type", "module", "object", "defmodule", "protocol"), "class"
    ),
    **dict.fromkeys(("const", "let", "var", "val"), "const"),
}
NAMES = {"n", "nx", "nc", "nf", "no", "na", "nn", "nv"}  # Pygments classes an identifier can carry
USES = NAMES | {"kt"}  # TypeScript's lexer calls every type after a colon a keyword type
JS_MODS = {"static", "async", "private", "public", "protected", "readonly", "override", "abstract", "export"}
COMPOUND = re.compile(r"[A-Za-z0-9]_[A-Za-z0-9]|[a-z0-9][A-Z]")
CLOSER = re.compile(r"\s*(?:[{)\]}]|end\b)")  # a line that goes on with what is above it
ABOVE = re.compile(r"\s*(?:@|#|//|/\*|\*|--|\[)")  # decorators, attributes and comments that belong to the line below
MACRO_RE = re.compile(r"\{%-?\s*macro\s+(\w+)\s*\(")
ENDMACRO_RE = re.compile(r"\{%-?\s*endmacro")
REF_RE = re.compile(r"""\bref\(\s*((['"])[\w.-]+\2)\s*(?:,\s*v(?:ersion)?\s*=[^,)]*)?\)""")
CALL_RE = re.compile(r"(?<![\w.])([A-Za-z_]\w*)\s*\(")


@dataclass(frozen=True)
class Def:
    path: str
    line: int  # the line that names it
    a: int  # what a reader opens: from the decorators and comments above it to the end of its body
    b: int
    kind: str = "func"  # func, class, const, model, macro
    nested: bool = False  # a method, or a function inside another: no other file calls it by its bare name
    inner: bool = False  # nested in a function, not in a class: nothing reaches it through a dot either


def indent(line: str) -> int:
    t = line.expandtabs(4)
    return len(t) - len(t.lstrip())


def extent(raw: list[str], line: int) -> tuple[int, int]:
    """A definition's lines, told by indentation: everything deeper than its first line, and closers at its depth."""
    depth, a, b = indent(raw[line - 1]), line, line
    for j in range(line, len(raw)):
        t = raw[j]
        if not t.strip():
            continue
        if indent(t) <= depth and not (indent(t) == depth and CLOSER.match(t)):
            break
        b = j + 1
    while a > 1 and raw[a - 2].strip() and abs(indent(raw[a - 2]) - depth) <= 1 and ABOVE.match(raw[a - 2]):
        a -= 1
    return a, b


def simple(name: str) -> str:
    return name.replace("_", "").lower()


def closes(sig: list, i: int) -> int:
    """Where the bracket opened at sig[i] closes."""
    depth = 0
    for j in range(i, len(sig)):
        if sig[j][2] in ("p", "o"):
            depth += sig[j][3].count("(") - sig[j][3].count(")")
            if depth <= 0:
                return j
    return len(sig)


def holds(path: str, module: str) -> bool:
    """Whether a file is the module an import names. A relative import was resolved to "/dir/file" and has to
    be that file; any other (src.access, a package, a path alias) only has to end the file's path."""
    stem = posixpath.splitext(path)[0]
    if posixpath.basename(stem) in ("__init__", "index"):
        stem = posixpath.dirname(stem)
    return "/" + stem == module if module.startswith("/") else ("/" + stem).endswith("/" + module)


def imports(sig: list, family: str, path: str) -> tuple[dict[str, tuple[str, str]], dict[int, str], set[int]]:
    """What a file's import lines say: for each name they bring in, its module and what it is called there;
    the module of each name written on an import line (by its place in sig); and the places of the aliases."""
    origin: dict[str, tuple[str, str]] = {}
    at: dict[int, str] = {}
    alias: set[int] = set()
    here = posixpath.dirname(path)

    def beside(rel: str) -> str:
        there = posixpath.normpath(posixpath.join(here, rel))
        return "/" + ("" if there == "." else there)

    def bind(names: list[int], module: str) -> None:
        for k in names:
            if sig[k - 1][3] == "as":
                alias.add(k)
                origin[sig[k][3]] = (module, sig[k - 2][3] if sig[k - 2][2] in NAMES else sig[k][3])
            else:
                at[k] = module
                if not (k + 1 < len(sig) and sig[k + 1][3] == "as"):
                    origin[sig[k][3]] = (module, sig[k][3])

    i = 0
    while i < len(sig):
        n, _, cls, text = sig[i]
        j, names = i + 1, []
        if family == "py" and cls == "kn" and text == "from":
            parts = []
            while j < len(sig) and sig[j][2] == "nn":
                parts.append(sig[j][3])
                j += 1
            if j < len(sig) and sig[j][3] == "import":
                wrapped = j + 1 < len(sig) and sig[j + 1][3] == "("
                j += 1
                while j < len(sig) and (wrapped or sig[j][0] == n) and (sig[j][2] == "n" or sig[j][3] in ("(", ",", "as")):
                    names += [j] if sig[j][2] == "n" else []
                    j += 1
                dotted = "".join(parts)
                module = dotted.lstrip(".").replace(".", "/")
                up = len(dotted) - len(dotted.lstrip("."))
                bind(names, beside("../" * (up - 1) + module) if up else module)
        elif family == "js" and cls.startswith("k") and text in ("import", "export"):
            while j < len(sig) and (sig[j][2] in NAMES or sig[j][3] in ("{", "}", ",", "*", "as", "type")):
                names += [j] if sig[j][2] in NAMES else []
                j += 1
            if j + 1 < len(sig) and sig[j][3] == "from" and sig[j + 1][2].startswith("s"):
                module = re.sub(r"\.[cm]?[jt]sx?$", "", sig[j + 1][3].strip("'\"`"))
                bind(names, beside(module) if module.startswith(".") else re.sub(r"^[@~]/", "", module))
        i = j
    return origin, at, alias


class Dbt:
    """ref() and macro calls in dbt projects. Read as text: Jinja means nothing to the SQL lexer."""

    def __init__(self, src: Source, g: Git, head: str, confs: list[str]) -> None:
        # confs: the dbt_project.yml of each project the page has files of
        self.src, self.head = src, head
        self.projects: list[tuple[str, dict[str, str | None], dict[str, Def | None]]] = []
        self.rows = cache(lambda path: len(src.raw(head, path) or []))
        self.uses = cache(self._uses)
        files = [f for f in g.run("ls-tree", "-r", "--name-only", "-z", head).split("\0") if f.endswith(".sql")]
        for conf in confs:
            root = posixpath.dirname(conf)
            try:
                project = yaml.safe_load(src.text(head, conf) or "")
            except yaml.YAMLError:
                project = None
            project = project if isinstance(project, dict) else {}

            def under(key: str, default: str) -> list[str]:
                dirs = project.get(key) if isinstance(project.get(key), list) else [default]
                found = (posixpath.normpath(posixpath.join(root, str(d))) for d in dirs)
                return ["" if d == "." else d + "/" for d in found]

            model_dirs, macro_dirs = under("model-paths", "models"), under("macro-paths", "macros")
            deepest = lambda dirs, path: max((len(d) for d in dirs if path.startswith(d)), default=-1)
            models: dict[str, str | None] = {}
            macros: dict[str, Def | None] = {}
            for path in files:
                as_model, as_macro = deepest(model_dirs, path), deepest(macro_dirs, path)
                if as_macro > as_model:
                    text = src.text(head, path) or ""
                    for m in MACRO_RE.finditer(text):
                        line = text.count("\n", 0, m.start()) + 1
                        end = ENDMACRO_RE.search(text, m.end())
                        last = text.count("\n", 0, end.start()) + 1 if end else line
                        macros[m[1]] = None if m[1] in macros else Def(path, line, line, last, "macro")
                elif as_model >= 0:
                    stem = posixpath.basename(path)[:-4]
                    models[stem] = None if stem in models else path  # two models of one name: neither is linked
            self.projects.append((root + "/" if root else "", models, macros))
        self.projects.sort(key=lambda x: -len(x[0]))

    def _uses(self, path: str) -> dict[int, list[tuple[int, int, Def]]]:
        """Line -> (start, end, definition) for each ref() and project macro call in a file."""
        out: dict[int, list[tuple[int, int, Def]]] = {}
        project = next((x for x in self.projects if path.startswith(x[0])), None)
        if not project:
            return out
        _, models, macros = project
        inside = False  # whether the line starts within {{ }} or {% %}
        for n, text in enumerate(self.src.raw(self.head, path) or [], 1):
            hits = []
            for m in REF_RE.finditer(text):
                if (target := models.get(m[1][1:-1])) and self.rows(target):
                    hits.append((m.start(1), m.end(1), Def(target, 1, 1, self.rows(target), "model")))
            for m in CALL_RE.finditer(text) if macros else ():
                d, at = macros.get(m[1]), m.start(1)
                opened = max(text.rfind("{{", 0, at), text.rfind("{%", 0, at))
                closed = max(text.rfind("}}", 0, at), text.rfind("%}", 0, at))
                # a macro runs only inside Jinja; outside it the same name is a SQL function
                if d and (opened > closed or (opened == closed and inside)) and (d.path, d.line) != (path, n):
                    hits.append((at, m.end(1), d))
            opened = max(text.rfind("{{"), text.rfind("{%"))
            closed = max(text.rfind("}}"), text.rfind("%}"))
            if opened != closed:
                inside = opened > closed
            if hits:
                out[n] = sorted(hits, key=lambda h: h[0])
        return out


class Defs:
    """Where names are defined, and which of their uses on the page lead there. It reads the highlighter's
    tokens with a few rules per language and follows no imports or types, so a use is linked only when its
    name and the code around it settle where it leads."""

    def __init__(self, src: Source, g: Git, head: str, shown: dict[str, set[int]]) -> None:
        # shown: every file the page packs at head -> its lines that are on the page from the start
        self.src, self.head = src, head
        self.open = set(shown)
        self.outside: list[str] = []  # dbt files packed from outside the change
        self.note = ""
        self.names: dict[tuple[str, str], list[Def]] = {}
        self.sites: set[tuple[str, int, int]] = set()
        self.sigs: dict[str, list[tuple[int, int, str, str]]] = {}
        self.imports: dict[str, tuple[dict[str, tuple[str, str]], dict[int, str], set[int]]] = {}
        self.file_links = cache(self._file_links)
        self.test = cache(lambda path: any(glob_match(path, p) for p in DEFAULT_EXCLUDES["tests"]))
        for path in shown:
            if family := CODE.get(posixpath.splitext(path)[1].lower()):
                self.scan(path, family)
        confs = set()
        for folder in {posixpath.dirname(p) for p in shown if p.endswith(".sql")}:
            while True:
                conf = posixpath.join(folder, "dbt_project.yml")
                if src.text(head, conf) is not None:
                    confs.add(conf)
                if not folder:
                    break
                folder = posixpath.dirname(folder)
        self.dbt = Dbt(src, g, head, sorted(confs)) if confs else None
        if self.dbt:
            self.admit(shown)

    # ---- code ----

    def scan(self, path: str, family: str) -> None:
        raw = self.src.raw(self.head, path) or []
        sig = self.sigs[path] = []
        for n, toks in enumerate(self.src.lines(self.head, path) or [], 1):
            col = 0
            for cls, text in toks:
                if text.strip() and not cls.startswith("c"):
                    sig.append((n, col, cls, text))
                col += len(text)
        self.imports[path] = imports(sig, family, path)
        first: dict[int, int] = {}
        nest: dict[int, int] = {}  # line -> brackets open where it starts
        depth = 0
        for i, t in enumerate(sig):
            if t[0] not in first:
                first[t[0]], nest[t[0]] = i, depth
            if t[2] in ("p", "o"):
                depth += sum(map(t[3].count, "([{")) - sum(map(t[3].count, ")]}"))
        found: dict[int, tuple[str, bool]] = {}  # place in sig -> kind, method
        for i, (n, col, cls, text) in enumerate(sig):
            kind = DEF_KINDS.get(text) if cls.startswith("k") else None
            if kind:
                j, method = i + 1, False
                if text == "func" and j < len(sig) and sig[j][3] == "(":  # Go: func (s *Server) Handle(
                    j, method = closes(sig, j) + 1, True
                while j + 2 < len(sig) and sig[j + 1][3] == "." and sig[j + 2][2] in NAMES:  # def self.make, fun String.ext
                    j += 2
                if j >= len(sig) or sig[j][2] not in NAMES or sig[j][0] != n:
                    continue
                if method and not (j + 1 < len(sig) and sig[j + 1][3].startswith("(")):
                    continue
                top = sig[first[n]][1] == 0 and all(t[2].startswith("k") for t in sig[first[n] : i])
                # C writes `struct foo` at every use; only the one with a body defines it
                named = family != "c" or kind != "class" or (j + 1 < len(sig) and sig[j + 1][3] == "{")
                if named and (kind != "const" or top):
                    found.setdefault(j, (kind, method))
            elif cls == "nf" and family in (".java", "c"):
                found.setdefault(i, ("func", False))
        starts = [*first.values(), len(sig)]
        for k, i in enumerate(starts[:-1]):
            line = sig[i : starts[k + 1]]
            # at the margin and in no open bracket, where a keyword argument can sit too
            if family == "py" and sig[i][1] == 0 and sig[i][2] == "n" and len(line) > 1 and nest[sig[i][0]] <= 0:
                if line[1][3] == "=" or (line[1][3] == ":" and any(t[3] == "=" for t in line)):
                    found.setdefault(i, ("const", False))
            if family == "js" and sig[i][1] > 0:  # a method: name(args) {
                m = 0
                while m < len(line) and line[m][3] in JS_MODS:
                    m += 1
                if m + 1 < len(line) and line[m][2] in NAMES and line[m + 1][3] == "(":
                    rest = line[closes(line, m + 1) + 1 :]
                    if rest and rest[-1][3] == "{" and not any(t[3] in ("(", ")", "=>") for t in rest):
                        found.setdefault(i + m, ("func", True))
        seen = set()
        around: list[tuple[int, int, str]] = []  # the definitions this one sits in: depth, last line, kind
        for i, (kind, method) in sorted(found.items()):
            n, col, _, name = sig[i]
            self.sites.add((path, n, col))
            if kind == "const" and name in seen:  # assigned again: the first is the definition
                continue
            seen.add(name)
            a, b = extent(raw, n)
            depth = indent(raw[n - 1])
            while around and (around[-1][0] >= depth or around[-1][1] < n):
                around.pop()
            home = around[-1][2] if around else "class"
            around.append((depth, b, kind))
            self.names.setdefault((family, name), []).append(
                Def(path, n, a, b, kind, method or depth > 0, depth > 0 and not method and home != "class")
            )

    def code_links(self, path: str, family: str) -> dict[int, list]:
        out: dict[int, list] = {}
        sig = self.sigs[path]
        origin, imported, alias = self.imports[path]
        for i, (n, col, cls, name) in enumerate(sig):
            if cls == "nd" and name.startswith("@"):  # a decorator's token takes its @ along
                col, name, cls = col + 1, name[1:], "n"
            if cls not in USES or len(name) < 3 or i in alias or (path, n, col) in self.sites:
                continue
            local = self.names.get((family, name), ())
            if not local and name not in origin:
                continue
            after = sig[i + 1][3] if i + 1 < len(sig) else ""
            if after == "=":  # a name being assigned or passed by keyword, not this definition's use
                continue
            dot = i > 0 and sig[i - 1][3] in (".", "::", "->", "?.")
            owner = simple(sig[i - 2][3]) if dot and i > 1 else ""
            call = after.startswith("(")
            # an import settles it: the name is what that module defines under the name it has there, or
            # nothing on this page
            module, found = None, local
            if i in imported:
                module = imported[i]
            elif not dot and name in origin and not any(d.path == path for d in local):
                module, real = origin[name]
                found = self.names.get((family, real), ())

            def leads(d: Def) -> bool:
                same = d.path == path
                if self.test(d.path) and not self.test(path):
                    return False
                if same and d.kind != "class" and d.a <= n <= d.b:
                    return False  # written inside itself: super().load(), or a wrapper calling what it wraps
                if module is not None:
                    return not d.nested and holds(d.path, module)
                telling = COMPOUND.search(name) or name.isupper() or (d.kind == "class" and name[0].isupper())
                if not dot:
                    return bool(telling or call) and (same or not d.nested)
                stem = simple(posixpath.basename(d.path).split(".")[0])
                named = owner in (stem, simple(posixpath.basename(posixpath.dirname(d.path))))
                if d.inner:
                    return False
                if not d.nested and d.kind != "class":
                    return named  # a module's own name, reached through a dot: the receiver has to be that module
                # x.get( says nothing by itself: the receiver has to name the file, or be the object itself
                return bool(telling or call) and (bool(telling) or named or (same and owner in ("self", "this", "cls", "super")))

            ds = [d for d in found if leads(d)]
            own = [d for d in ds if d.path == path]
            ds = own if len(own) == 1 else ds
            if 1 <= len(ds) <= 3:
                out.setdefault(n, []).append((col, col + len(name), tuple(ds)))
        return out

    # ---- dbt ----

    def admit(self, shown: dict[str, set[int]]) -> None:
        """Pick the dbt files from outside the change that the page packs, so the most-used ones fit the budget."""
        tally: dict[str, list[int]] = {}  # file -> its uses on the page at load, its uses a reader has to unfold
        for path in shown:
            if path.endswith(".sql"):
                for n, hits in self.dbt.uses(path).items():
                    for _, _, d in hits:
                        if d.path not in shown:
                            tally.setdefault(d.path, [0, 0])[n not in shown[path]] += 1
        rows = self.dbt.rows
        order = sorted(tally, key=lambda p: (not tally[p][0], -(tally[p][0] or tally[p][1]), rows(p), p))
        packed, total, left = [], 0, []
        for p in order:
            fits = len(packed) < OUT_FILES and rows(p) <= OUT_FILE_ROWS and total + rows(p) <= OUT_ROWS
            if fits and len((self.src.text(self.head, p) or "").encode()) <= FOLD_MAX:
                packed.append(p)
                total += rows(p)
            else:
                left.append(p)
        self.open.update(packed)
        self.outside = packed
        if left:
            names = ", ".join(posixpath.basename(p)[:-4] for p in left[:8]) + (", …" if len(left) > 8 else "")
            self.note = (
                f"definitions: packed {len(packed)} dbt files from outside the change ({total} rows); {len(left)} more "
                f"are past the page's budget, so ref() and macro calls to them open nothing: {names}"
            )

    # ---- links ----

    def _file_links(self, path: str) -> dict[int, list]:
        if path not in self.open:
            return {}
        if path in self.sigs:
            return self.code_links(path, CODE[posixpath.splitext(path)[1].lower()])
        out: dict[int, list] = {}
        if self.dbt and path.endswith(".sql"):
            for n, hits in self.dbt.uses(path).items():
                if here := [(a, b, (d,)) for a, b, d in hits if d.path in self.open]:
                    out[n] = here
        return out

    def links(self, path: str, n: int) -> list[tuple[int, int, tuple[Def, ...]]]:
        """(start, end, definitions) for the names on one line that lead somewhere the page can open."""
        return self.file_links(path).get(n, [])


@dataclass
class Frame:
    id: str
    lines: set[int]  # new-side (or file) line numbers a card may point at
    chapter: str


class Renderer:
    def __init__(self, ix: Indexed, front: dict, link: bool = False) -> None:
        self.ix = ix
        self.idx = ix.idx
        self.link = link  # find definitions and link their uses; only a build that writes the page needs it
        self.defs: Defs | None = None
        self.def_ids: dict[Def, int] = {}
        self.wholes: dict[str, bool] = {}
        self.notes: list[str] = []
        self.tour = bool(ix.idx.get("tour"))
        self.front = front
        self.errors: list[str] = []
        self.warnings: list[str] = []
        self.hunks = ix.hunks
        self.covered: set[tuple[str, int]] = set()
        self.referenced: set[str] = set()
        self.used: dict[str, list[str]] = {}
        self.frames: dict[str, Frame] = {}
        self.ids: dict[str, str] = {}  # every id on the page -> where it was first used, for error messages
        self.refs: dict[str, tuple[str, list[str]]] = {}  # anchor ref -> (hash, chapters that use it)
        self.chapter = "hero"
        self.n = 0
        self.last_fid: str | None = None
        self.old_paths = {f.path: f.old_path for f in ix.files if f.old_path}
        self.fd_file: dict[str, str] = {}
        self.fd_hunk: dict[str, str] = {}
        for f in ix.files:
            fd = "fd-" + (slug(f.path) or "file")
            while fd in self.fd_file.values():
                fd += "-2"
            self.fd_file[f.path] = fd
            for h in f.hunks:
                self.fd_hunk[h.id] = f"{fd}--h{h.n}"
        self.md = MarkdownIt("commonmark", {"html": True, "typographer": False}).enable("table")
        self.traces = self.load_traces()
        self.trace_hits: set[str] = set()
        self.counting = True  # off while packing sources: a trace has to show up in the story itself
        self.seqs: dict[str, Seq] = {}
        self.apply_exclusions()
        owner, name = self.idx["owner"], self.idx["name"]
        self.gh = f"https://github.com/{owner}/{name}" if owner else None
        head_pushed = not self.idx["worktree"] and bool(self.gh) and pushed(ix.g, self.idx["head"])
        # a working-tree snapshot isn't on GitHub, even when the story carries a PR's metadata
        self.head_links = bool(self.gh) and not self.idx["worktree"] and (bool(self.idx["pr"]) or head_pushed)
        self.base_links = bool(self.gh) and not self.tour and pushed(ix.g, self.idx["merge_base"])

    # ---- setup ----

    def load_traces(self) -> list[tuple[str, re.Pattern]]:
        traces = self.front.get("traces") or {}
        if not isinstance(traces, dict):
            self.errors.append("front matter: traces must map a name to a list of identifiers")
            return []
        out = []
        self.trace_names = {}
        for name, alts in traces.items():
            alts = [alts] if isinstance(alts, str) else list(alts or [])
            if alts:
                self.trace_names[slug(str(name))] = str(name)
                out.append((slug(str(name)), re.compile(r"(?<![\w-])(" + "|".join(map(re.escape, map(str, alts))) + r")(?![\w-])")))
        return out

    def apply_exclusions(self) -> None:
        if self.tour:
            if self.front.get("exclude") or self.front.get("include"):
                self.warnings.append("front matter: a tour has no coverage, so exclude and include do nothing; remove them")
            return
        for rule in self.front.get("exclude") or []:
            if not isinstance(rule, dict) or not rule.get("path") or not rule.get("reason"):
                self.errors.append("front matter: each exclude needs a path glob and a reason")
                continue
            hits = [f for f in self.ix.files if glob_match(f.path, rule["path"])]
            if not hits:
                self.warnings.append(f"front matter: exclude {rule['path']!r} matches no changed file")
            for f in hits:
                f.excluded = f"story: {rule['reason']}"
        for pat in self.front.get("include") or []:
            hits = [f for f in self.ix.files if glob_match(f.path, pat)]
            if not hits:
                self.warnings.append(f"front matter: include {pat!r} matches no changed file")
            for f in hits:
                f.excluded = None

    # ---- links ----

    def gh_diff(self, path: str) -> str | None:
        if not self.head_links:
            return None
        h = hashlib.sha256(path.encode()).hexdigest()
        if self.idx["pr"]:
            return f"{self.idx['pr']['url']}/files#diff-{h}"
        return f"{self.gh}/compare/{self.idx['merge_base']}...{self.idx['head']}#diff-{h}"

    def gh_blob(self, sha: str, path: str) -> str | None:
        ok = self.base_links if sha == self.idx["merge_base"] else self.head_links and not self.idx["worktree"]
        return f"{self.gh}/blob/{sha}/{quote(path, safe='/')}" if ok else None

    # ---- code ----

    def trace_ranges(self, text: str) -> list[tuple[int, int, str]]:
        out = [(m.start(), m.end(), g) for g, rx in self.traces for m in rx.finditer(text)]
        if self.counting:
            self.trace_hits.update(g for _, _, g in out)
        return out

    def render_code(self, toks, marks, traces, links=()) -> str:
        if not marks and not traces and not links:
            return "".join(f'<span class="{cls}">{esc(val)}</span>' if cls else esc(val) for cls, val in toks)
        bounds = {s for s, _ in marks} | {e for _, e in marks}
        bounds |= {s for s, _, _ in traces} | {e for _, e, _ in traces}
        bounds |= {s for s, _, _ in links} | {e for _, e, _ in links}
        bounds = sorted(bounds)
        links = sorted(links)
        starts = [a for a, _, _ in links]
        out, pos = [], 0
        for cls, val in toks:
            end = pos + len(val)
            cuts = bounds[bisect.bisect_right(bounds, pos) : bisect.bisect_left(bounds, end)] + [end]
            last = pos
            for c in cuts:
                piece = esc(val[last - pos : c - pos])
                k = bisect.bisect_right(starts, last) - 1
                d = f' data-d="{links[k][2]}"' if k >= 0 and c <= links[k][1] else ""
                span = f'<span class="{cls}"{d}>{piece}</span>' if cls else f"<span{d}>{piece}</span>" if d else piece
                g = next((g for a, b, g in traces if a <= last and c <= b), None)
                if g:
                    span = f'<span class="tr" data-tr="{g}">{span}</span>'
                if any(a <= last and c <= b for a, b in marks):
                    span = f"<mark>{span}</mark>"
                out.append(span)
                last = c
            pos = end
        return "".join(out)

    def row_tokens(self, path: str, r: Row) -> list[tuple[str, str]]:
        base = r.kind == "-"
        sha = self.idx["merge_base"] if base else self.idx["head"]
        n = r.old if base else r.new
        lines = self.ix.src.lines(sha, self.old_paths.get(path, path) if base else path)
        text = r.text.removesuffix("\r")
        if lines and n and n <= len(lines):
            toks = lines[n - 1]
            if "".join(t for _, t in toks) == text:
                return toks
        return [("", text)]

    def code(self, toks, text: str, marks=(), nonl: bool = False, links=()) -> str:
        """A line's <code> element: what a row shows now, and what the page unfolds later."""
        body = pin_indent(self.render_code(toks, marks, self.trace_ranges(text), links)) or " "
        badge = '<span class="nonl" title="No newline at end of file">no newline</span>' if nonl else ""
        return f"{code_open(text)}{body}{badge}</code>"

    def def_links(self, sha: str, path: str, n: int | None) -> list[tuple[int, int, str]]:
        """The names on a head line that lead to a definition, each with the ids the page opens."""
        if not self.defs or not n or sha != self.idx["head"]:
            return []
        ids = lambda ds: " ".join(str(self.def_ids.setdefault(d, len(self.def_ids))) for d in ds)
        return [(a, b, ids(ds)) for a, b, ds in self.defs.links(path, n)]

    def row_code(self, path: str, r: Row) -> str:
        links = () if r.kind == "-" else self.def_links(self.idx["head"], path, r.new)
        return self.code(self.row_tokens(path, r), r.text, r.marks, r.nonl, links)

    def line_code(self, sha: str, path: str, n: int) -> str:
        text = self.ix.src.raw(sha, path)[n - 1].removesuffix("\r")
        toks = self.ix.src.lines(sha, path)[n - 1]
        return self.code(toks if "".join(t for _, t in toks) == text else [("", text)], text, links=self.def_links(sha, path, n))

    def row_html(self, path: str, r: Row) -> str:
        return (
            f'<div class="row {KIND[r.kind]}" data-o="{r.old or ""}" data-n="{r.new or ""}">'
            f'<span class="ln">{r.old or ""}</span><span class="ln">{r.new or ""}</span>'
            f'<span class="sg">{SIGN[r.kind]}</span>{self.row_code(path, r)}</div>'
        )

    # ---- sources: each file once, for the page to unfold or fill in ----

    def whole(self, f: FileDiff) -> bool:
        """Whether the page can show the file's unchanged lines around its diff."""
        if f.path in self.wholes:
            return self.wholes[f.path]
        src, head = self.ix.src, self.idx["head"]
        raw = [] if f.status == "D" else src.raw(head, f.path)
        self.wholes[f.path] = (
            raw is not None
            and not (f.symlink or f.submodule or f.status == "T")
            and len((src.text(head, f.path) or "").encode()) <= FOLD_MAX
            # the patch and the blob must agree line for line, or unfolded rows would be numbered wrong
            and all(r.new is None or (r.new <= len(raw) and raw[r.new - 1] == r.text) for h in f.hunks for r in h.rows)
        )
        return self.wholes[f.path]

    def diff_seq(self, f: FileDiff) -> Seq:
        if seq := self.seqs.get("d:" + f.path):
            return seq
        raw = [] if f.status == "D" else self.ix.src.raw(self.idx["head"], f.path)
        full = self.whole(f)
        seq = self.seqs["d:" + f.path] = Seq(len(self.seqs), f.path, full=full)
        n = delta = 0  # head lines placed so far; how far new line numbers run ahead of old ones
        same = lambda a, b: [Row(" ", raw[i], i + 1 - delta, i + 1) for i in range(a, b)] if full else []
        for h in f.hunks:
            news = sum(r.kind != "-" for r in h.rows)
            before = h.new_start - 1 if news else h.new_start
            seq.rows += same(n, before)
            seq.hunks.append((len(seq.rows), len(h.rows), before + 1 - delta, before + 1))
            seq.rows += h.rows
            n, delta = before + news, delta + h.adds - h.dels
        seq.rows += same(n, len(raw or []))
        return seq

    def plain_seq(self, sha: str, path: str) -> Seq | None:
        key = f"p:{sha}:{path}"
        if key not in self.seqs:
            if len(self.ix.src.text(sha, path).encode()) > FOLD_MAX:
                return None
            rows = [Row(" ", t, None, n) for n, t in enumerate(self.ix.src.raw(sha, path), 1)]
            self.seqs[key] = Seq(len(self.seqs), path, rows, sha=sha)
        return self.seqs[key]

    @staticmethod
    def src_attr(seq: Seq | None, at: int) -> str:
        return f' data-src="{seq.i}" data-at="{at}"' if seq and seq.full else ""

    def sources(self) -> str:
        """Every Seq, deflated. The page inflates one when a reader unfolds a file or opens a diff it left out."""
        self.counting = False
        for path in sorted(self.defs.open) if self.defs else ():
            self.def_seq(path)
        meta, blobs = [], []
        for s in self.seqs.values():
            if s.sha:
                lines = [" " + self.line_code(s.sha, s.path, r.new) for r in s.rows]
                meta.append({"n": len(s.rows), "x": 1, "p": 1})
            else:
                lines = [r.kind + self.row_code(s.path, r) for r in s.rows]
                meta.append({"n": len(s.rows), "x": int(s.full), "h": s.hunks})
            data = base64.b64encode(zlib.compress("\n".join(lines).encode(), 9)).decode()
            blobs.append(f'<script type="text/plain" id="_s{s.i}">{data}</script>')
        self.counting = True
        return f'<script type="application/json" id="_src">{json.dumps(meta, separators=(",", ":"))}</script>' + "".join(blobs)

    # ---- definitions: uses carry data-d, a list of places in the manifest the page opens ----

    def find_defs(self, story: list[Item]) -> Defs:
        head, src = self.idx["head"], self.ix.src
        # every file the page packs at head -> its lines the story itself shows
        shown: dict[str, set[int]] = {f.path: set() for f in self.ix.files if f.status != "D" and not f.binary and self.whole(f)}

        def placed(it: Item):
            if it.name in ("diff", "ripple"):
                hs = [self.hunks[a] for a in it.args if a in self.hunks]
                m = re.fullmatch(r"(\d+)-(\d+)", it.kw.get("rows", "")) if len(hs) == 1 else None
                for h in hs:
                    yield h.path, h.rows[int(m[1]) - 1 : int(m[2])] if m else h.rows
            elif it.name == "also" and it.args and (f := self.ix.file(it.args[0])):
                for h in f.hunks:
                    yield f.path, h.rows

        def walk(items: list[Item]) -> None:
            for it in items:
                spec = parse_lines_spec(it.args) if it.kind == "dir" and it.name == "ctx" else None
                if spec and spec[2] and spec[1] == "head":
                    path, _, (a, b) = spec
                    if path in shown or len((src.text(head, path) or "").encode()) in range(1, FOLD_MAX + 1):
                        shown.setdefault(path, set()).update(range(a, b + 1))
                for path, rows in placed(it) if it.kind == "dir" else ():
                    if path in shown:
                        shown[path].update(r.new for r in rows if r.new)
                walk(it.children)

        walk(story)
        defs = Defs(src, self.ix.g, head, shown)
        if defs.note:
            self.notes.append(defs.note)
        return defs

    def def_seq(self, path: str) -> Seq | None:
        """The source a definition in this file opens from: the file's diff when it changed, else the plain file."""
        f = self.ix.file(path)
        seq = self.diff_seq(f) if f else None
        return seq if seq and seq.full else self.plain_seq(self.idx["head"], path)

    def defs_json(self) -> str:
        """Call after sources(): unfolded rows hand out ids too."""
        out = []
        places: dict[int, dict[int, int]] = {}  # source -> head line -> row
        for d in self.def_ids:
            seq = self.def_seq(d.path)
            if seq.i not in places:
                places[seq.i] = {r.new: i for i, r in enumerate(seq.rows) if r.kind != "-"}
            at = places[seq.i][d.a]
            out.append([seq.i, at, min(places[seq.i][d.b] - at + 1, DEF_ROWS), d.path, d.line])
        return f'<script type="application/json" id="_def">{json.dumps(out, separators=(",", ":"))}</script>'

    def anchor(self, ref: str, h: str) -> None:
        self.refs.setdefault(ref, (h, []))[1].append(self.chapter)

    def reference(self, path: str) -> None:
        self.referenced.add(path)
        f = self.ix.file(path)
        if f and f.file_level:
            self.anchor(f"file:{path}", f.fingerprint)

    def cover(self, fid: str, h: Hunk, rows: list[Row]) -> None:
        self.used.setdefault(h.id, []).append(fid)
        self.reference(h.path)
        self.anchor(h.id, h.hash)
        for r in rows:
            if r.kind != " ":
                self.covered.add((h.id, id(r)))

    def new_id(self, given: str | None, line: int) -> str:
        self.n += 1
        if not given:
            # authors' ids start with a letter, so generated ones can't collide with them
            fid = f"_f{self.n}"
        else:
            fid = given
            if not re.fullmatch(r"[A-Za-z][\w-]*", fid):
                self.errors.append(f"story.md:{line}: id {fid!r} must start with a letter and use letters, digits, - or _")
            elif reserved(fid):
                self.errors.append(f"story.md:{line}: id {fid!r} is taken by the page itself; pick another")
        if fid in self.ids:
            self.errors.append(f"story.md:{line}: id {fid!r} is already used by {self.ids[fid]}; frame and chapter ids share one namespace")
        self.ids.setdefault(fid, f"the frame at story.md:{line}")
        self.last_fid = fid
        return fid

    def frame_html(self, fid, kind, path, label, stats, stamp, body, hunk_ids, extra_attr="", fd="", fhash="", meta=None, src="") -> str:
        chip = '<span class="chip">Unchanged</span>' if kind == "ctx" and not self.tour else ""
        chip += f'<span class="chip">{esc(meta)}</span>' if meta else ""
        tools = (
            '<button class="fbtn ico" data-act="files" title="Show in the full diff (f)" aria-label="Show in the full diff">'
            '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 3H3v10h10v-3M9 3h4v4M13 3L7.5 8.5"/></svg></button>'
            '<button class="fbtn rev" data-act="reviewed" aria-pressed="false" title="Mark reviewed (r)" aria-label="Mark reviewed">'
            '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M3.5 8.5l3 3 6-7"/></svg></button>'
            if kind != "ctx" else ""
        )
        return (
            f'<figure class="frame {kind}" id="{fid}" data-frame="{fid}" data-path="{esc(path)}" '
            f'data-hunks="{esc(json.dumps(hunk_ids))}" data-fd="{fd}" data-hash="{fhash}"{extra_attr}>'
            '<figcaption class="fh"><button class="fd-tog fh-tog" data-act="frame-toggle" aria-expanded="true" aria-label="Collapse">'
            '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg></button>'
            f'{path_html(path)}<span class="sym">{esc(label)}</span>{chip}{stats}'
            f'<span class="grow"></span><span class="fh-r">{stamp}{tools}</span></figcaption>'
            f'<div class="code u"{src}>{body}</div></figure>'
        )

    def stamp(self, sha: str, path: str, a: int, b: int, worktree: bool) -> str:
        where = "working tree" if worktree else sha[:7]
        title = "Rendered from the working tree snapshot" if worktree else f"Rendered from git at {sha}"
        url = self.gh_blob(sha, path)
        inner = f"{where}<span>L{a}–{b}</span>"
        if url:
            return f'<a class="stamp" href="{esc(url)}#L{a}-L{b}" target="_blank" rel="noopener" title="{title}">{inner}</a>'
        return f'<span class="stamp" title="{title}">{inner}</span>'

    def lookup(self, hid: str, line: int) -> Hunk | None:
        if hid in self.hunks:
            return self.hunks[hid]
        close = difflib.get_close_matches(hid, list(self.hunks), n=3)
        self.errors.append(f"story.md:{line}: unknown hunk {hid!r}" + (f"; did you mean {', '.join(close)}?" if close else ""))
        return None

    def no_diff(self, it: Item) -> str:
        self.errors.append(f"story.md:{it.line}: a tour has no diff, so @{it.name} has nothing to show; use @ctx path@head a-b or @tree")
        return ""

    def d_diff(self, it: Item) -> str:
        if self.tour:
            return self.no_diff(it)
        if not it.args:
            self.errors.append(f"story.md:{it.line}: @diff needs at least one hunk id")
            return ""
        hs = [h for h in (self.lookup(a, it.line) for a in it.args) if h]
        if len(hs) != len(it.args):
            return ""
        if len({h.path for h in hs}) > 1:
            self.errors.append(f"story.md:{it.line}: one @diff shows one file; split it into one @diff per file")
            return ""
        if [h.n for h in hs] != sorted({h.n for h in hs}):
            self.errors.append(f"story.md:{it.line}: list a file's hunks once each, in file order; use separate @diff lines to show them in another order")
            return ""
        fid = self.new_id(it.kw.get("id"), it.line)
        path = hs[0].path
        f = self.ix.file(path)
        seq = self.diff_seq(f)
        parts, adds, dels, news, olds, shown = [], 0, 0, [], [], []
        prev: list[Row] | None = None
        last, first_at = hs[0], 0
        for h in hs:
            rows, at = h.rows, seq.start(h)
            if "rows" in it.kw:
                if len(hs) > 1:
                    self.errors.append(f"story.md:{it.line}: rows= works with a single hunk")
                    return ""
                m = re.fullmatch(r"(\d+)-(\d+)", it.kw["rows"])
                if not m or not 1 <= int(m[1]) <= int(m[2]) <= len(h.rows):
                    self.errors.append(f"story.md:{it.line}: rows={it.kw['rows']} is outside 1-{len(h.rows)} for {h.id}")
                    return ""
                rows = h.rows[int(m[1]) - 1 : int(m[2])]
                at += int(m[1]) - 1
            if prev is not None:
                parts.append(gap(gap_label(prev, rows, h.n != last.n + 1), at if seq.full else None))
            else:
                first_at = at
            last = h
            parts.extend(self.row_html(h.path, r) for r in rows)
            adds += sum(r.kind == "+" for r in rows)
            dels += sum(r.kind == "-" for r in rows)
            news += [r.new for r in rows if r.new]
            olds += [r.old for r in rows if r.old]
            shown += rows
            self.cover(fid, h, rows)
            prev = rows
        self.frames[fid] = Frame(fid, set(news), self.chapter)
        label = it.kw.get("title") or hs[0].header or ""
        if news:
            stamp = self.stamp(self.idx["head"], path, min(news), max(news), self.idx["worktree"])
        else:
            stamp = self.stamp(self.idx["merge_base"], self.old_paths.get(path, path), min(olds or [1]), max(olds or [1]), False)
        return self.frame_html(
            fid, "diff", path, label, stat_html(adds, dels), stamp, "".join(parts), [h.id for h in hs],
            url_attr("data-gh", self.gh_diff(path)), self.fd_hunk[hs[0].id], rows_hash(shown), f.meta if f else None,
            self.src_attr(seq, first_at),
        )

    def d_ripple(self, it: Item) -> str:
        if self.tour:
            return self.no_diff(it)
        if len(it.args) < 2:
            self.errors.append(f"story.md:{it.line}: @ripple needs a first hunk and at least one more site")
            return ""
        first = self.d_diff(Item("dir", it.line, name="diff", args=it.args[:1], kw={k: v for k, v in it.kw.items() if k != "label"}))
        if not first:
            return ""
        fid = self.last_fid
        first_path = self.hunks[it.args[0]].path
        inner = []
        for hid in it.args[1:]:
            h = self.lookup(hid, it.line)
            if not h:
                return ""
            self.cover(fid, h, h.rows)
            where = f'{path_html(h.path)} ' if h.path != first_path else ""
            inner.append(
                f'<div class="rip-site" data-hunk="{esc(h.id)}" data-path="{esc(h.path)}" data-fd="{self.fd_hunk[h.id]}"'
                f'{url_attr("data-gh", self.gh_diff(h.path))}><div class="rip-sym">{where}{esc(h.header)}</div>'
            )
            seq = self.diff_seq(self.ix.file(h.path))
            inner.append(f'<div class="code u"{self.src_attr(seq, seq.start(h))}>' + "".join(self.row_html(h.path, r) for r in h.rows) + "</div></div>")
        label = it.kw.get("label") or f"{len(it.args) - 1} more sites, same change"
        details = f'<details class="ripple"><summary>{esc(label)}</summary>{"".join(inner)}</details>'
        self.last_fid = fid
        first = re.sub(r'data-hash="(\w+)"', lambda m: f'data-hash="{digest(m[1] + "".join(self.hunks[x].path + self.hunks[x].hash for x in it.args[1:]))}"', first, count=1)
        return first[: -len("</figure>")] + details + "</figure>"

    def d_ctx(self, it: Item) -> str:
        spec = parse_lines_spec(it.args)
        if not spec or not spec[2]:
            self.errors.append(f"story.md:{it.line}: @ctx takes path@head|base and lines, e.g. @ctx src/app.py@head 10-40")
            return ""
        path, side, (a, b) = spec
        if side == "base" and self.tour:
            self.errors.append(f"story.md:{it.line}: a tour has no base; show {path}@head")
            return ""
        sha = self.idx["head"] if side == "head" else self.idx["merge_base"]
        lines, raw = self.ix.src.lines(sha, path), self.ix.src.raw(sha, path)
        if lines is None:
            self.errors.append(f"story.md:{it.line}: " + missing(self.ix, sha, path, side))
            return ""
        if not 1 <= a <= b <= len(lines):
            self.errors.append(f"story.md:{it.line}: {path}@{side} has {len(lines)} lines; {span(a, b)} is out of range")
            return ""
        fid = self.new_id(it.kw.get("id"), it.line)
        rows = [
            f'<div class="row c" data-n="{n}"><span class="ln"></span><span class="ln">{n}</span><span class="sg"> </span>'
            f"{self.line_code(sha, path, n)}</div>"
            for n in range(a, b + 1)
        ]
        h = digest("\n".join(raw[a - 1 : b]))
        self.anchor(f"{path}@{side}:{a}-{b}", h)
        self.frames[fid] = Frame(fid, set(range(a, b + 1)), self.chapter)
        stamp = self.stamp(sha, path, a, b, side == "head" and self.idx["worktree"])
        return self.frame_html(
            fid, "ctx", path, it.kw.get("title", ""), "", stamp, "".join(rows), [],
            url_attr("data-blob", self.gh_blob(sha, path)), self.fd_file.get(path, ""), h,
            src=self.src_attr(self.plain_seq(sha, path), a - 1),
        )

    def d_tree(self, it: Item) -> str:
        depth = it.kw.get("depth", "2")
        if len(it.args) != 1 or not re.fullmatch(r"[1-9]", depth):
            self.errors.append(f"story.md:{it.line}: @tree takes one directory and an optional depth=1-9, e.g. @tree src depth=2 (. is the repo root)")
            return ""
        path = it.args[0].removesuffix("@head")
        sha = self.idx["head"]
        got = tree_entries(self.ix.g, sha, path, int(depth))
        if got is None:
            is_file = self.ix.src.raw(sha, path) is not None
            self.errors.append(
                f"story.md:{it.line}: " + (f"{path} is a file; @tree lists directories, @ctx shows files" if is_file else missing(self.ix, sha, path, "head"))
            )
            return ""
        entries, total = got
        root = posixpath.normpath(path.strip("/") or ".").removeprefix(".")
        fid = self.new_id(it.kw.get("id"), it.line)
        rows = []
        for e, name, count in tree_text(entries, blob_lines(self.ix.g, entries)):
            text = "  " * (e.level - 1) + name + "  " + count
            rows.append(
                f'<div class="trow {e.kind}" style="--lvl:{e.level - 1}" data-path="{esc(e.path)}" data-t="{esc(text)}">'
                f'<span class="tn">{esc(name)}</span><span class="tc">{esc(count)}</span></div>'
            )
        # what the tree shows, minus line counts: a line added to a file mustn't make it stale
        h = digest(f"{total}\n" + "\n".join(f"{e.kind} {e.path} {e.files}" for e in entries))
        self.anchor(f"tree:{root or '.'}@head:{depth}", h)
        self.frames[fid] = Frame(fid, set(), self.chapter)
        where = "working tree" if self.idx["worktree"] else sha[:7]
        title = "Listed from the working tree snapshot" if self.idx["worktree"] else f"Listed from git at {sha}"
        url = f"{self.gh}/tree/{sha}/{quote(root, safe='/')}" if self.head_links and not self.idx["worktree"] else None
        stamp = (
            f'<a class="stamp" href="{esc(url)}" target="_blank" rel="noopener" title="{title}">{where}</a>'
            if url else f'<span class="stamp" title="{title}">{where}</span>'
        )
        return (
            f'<figure class="frame tree" id="{fid}" data-frame="{fid}" data-path="{esc(root)}" data-hash="{h}">'
            f'<figcaption class="fh">{path_html((root or self.idx["name"]) + "/")}<span class="sym">{esc(it.kw.get("title", ""))}</span>'
            f'<span class="stat">{total} file{"" if total == 1 else "s"}</span><span class="grow"></span><span class="fh-r">{stamp}</span></figcaption>'
            f'<div class="tree-body">{"".join(rows)}</div></figure>'
        )

    def file_code(self, f: FileDiff, fid: str, lazy: bool = False) -> str:
        """A file's whole diff. Lazy leaves the rows out and counts nothing as shown: the page fills each hunk in
        from the file's source when the reader opens it."""
        if not f.hunks:
            return f'<div class="code u">{gap(esc(change_record(f)))}</div>'
        seq = self.diff_seq(f)
        parts = [gap(esc(f.meta))] if f.meta else []
        for i, h in enumerate(f.hunks):
            label = gap_label(f.hunks[i - 1].rows, h.rows) if i else ""
            if lazy:
                parts.append(gap(label, seq.start(h), len(h.rows)))
                continue
            if i:
                parts.append(gap(label, seq.start(h) if seq.full else None))
            parts.extend(self.row_html(f.path, r) for r in h.rows)
            self.cover(fid, h, h.rows)
        attr = f' data-src="{seq.i}"' if lazy else self.src_attr(seq, seq.start(f.hunks[0]))
        return f'<div class="code u"{attr}>{"".join(parts)}</div>'

    def d_also(self, it: Item) -> str:
        if self.tour:
            return self.no_diff(it)
        f = self.ix.file(it.args[0]) if it.args else None
        if not f:
            close = difflib.get_close_matches(it.args[0] if it.args else "", [f.path for f in self.ix.files], n=3)
            self.errors.append(f"story.md:{it.line}: @also needs a changed file" + (f"; did you mean {', '.join(close)}?" if close else ""))
            return ""
        fid = self.new_id(it.kw.get("id"), it.line)
        self.reference(f.path)
        if not f.file_level:
            self.anchor(f"file:{f.path}", f.fingerprint)
        note = f'<span class="note-line">{esc(it.kw["note"])}</span>' if "note" in it.kw else ""
        attr = url_attr("data-gh", self.gh_diff(f.path)) + f' data-fd="{self.fd_file[f.path]}" data-hash="{f.fingerprint}" data-path="{esc(f.path)}"'
        return (
            f'<details class="file-item" id="{fid}" data-frame="{fid}"{attr}><summary>{path_html(f.path)}{note}'
            f'<span class="grow"></span>{stat_html(f.adds, f.dels)}</summary>'
            f"{self.file_code(f, fid)}</details>"
        )

    # ---- blocks ----

    def md_html(self, text: str, line: int, cls: str | None = None) -> str:
        tokens = self.md.parse(text)
        self.check_hand_code(text, tokens, line)
        if cls:
            for t in tokens:
                if t.nesting == 1 and t.level == 0:
                    t.attrJoin("class", cls)
        return self.md.renderer.render(tokens, self.md.options, {})

    def check_hand_code(self, text: str, tokens: list, line: int) -> None:
        for t in tokens:
            if t.type not in ("fence", "code_block"):
                continue
            n = len([x for x in t.content.split("\n") if x.strip()])
            if n >= 2:
                at = line + t.map[0]
                self.warnings.append(
                    f"story.md:{at}: hand-typed code block ({n} lines). Real code comes from @diff/@ctx; "
                    "label pseudo-code with '::: sketch'"
                )
        for m in re.finditer(r"<pre\b.*?</pre>", text, re.S | re.I):
            if m[0].count("\n") >= 2:
                at = line + text[: m.start()].count("\n")
                self.warnings.append(f"story.md:{at}: hand-typed <pre> block; real code comes from @diff/@ctx")

    def inline(self, text: str) -> str:
        return self.md.renderInline(text)

    def items(self, items: list[Item], ctx: str) -> str:
        out = []
        for it in items:
            if it.kind == "md":
                out.append(self.md_html(it.text, it.line, "prose" if ctx == "chapter" else None))
            elif it.kind == "dir":
                out.append(getattr(self, f"d_{it.name}")(it))
            elif it.kind == "box":
                out.append(self.box(it, ctx))
        return "\n".join(x for x in out if x)

    def box(self, it: Item, ctx: str) -> str:
        if it.name == "step":
            return self.b_step(it)
        if it.name == "card":
            self.errors.append(f"story.md:{it.line}: '::: card' belongs inside '::: step'")
            return ""
        if it.name == "branch":
            self.errors.append(f"story.md:{it.line}: '::: branch' belongs inside '::: fork'")
            return ""
        if it.name == "fork":
            return self.b_fork(it)
        if it.name == "note":
            return self.b_note(it)
        if it.name == "sketch":
            label = esc(it.text) or "Sketch"
            body = esc("\n".join(it.raw).strip("\n"))
            return f'<figure class="sketch"><figcaption>{label}<span>not code from git</span></figcaption><pre>{body}</pre></figure>'
        return ""

    def b_step(self, it: Item) -> str:
        spine = [c for c in it.children if not (c.kind == "box" and c.name == "card")]
        cards = [c for c in it.children if c.kind == "box" and c.name == "card"]
        if not cards:
            self.errors.append(f"story.md:{it.line}: '::: step' needs at least one '::: card'")
        frames = [c for c in spine if c.kind == "dir" and c.name in ("diff", "ctx", "ripple")]
        if len(frames) != 1:
            self.errors.append(f"story.md:{it.line}: '::: step' needs exactly one @diff, @ctx or @ripple before its cards")
            return ""
        first_card = next((i for i, c in enumerate(it.children) if c.kind == "box" and c.name == "card"), len(it.children))
        if any(not (c.kind == "box" and c.name == "card") for c in it.children[first_card:]):
            self.errors.append(f"story.md:{it.line}: in '::: step', the code comes first and only cards follow")
        parts, target = [], None
        for c in spine:
            parts.append(self.items([c], "spine"))
            if c is frames[0]:
                target = self.last_fid
        spine_html = "\n".join(x for x in parts if x)
        lane = "".join(self.b_card(c, target) for c in cards)
        return f'<div class="step"><div class="spine">{spine_html}</div><div class="lane-r">{lane}</div></div>'

    def b_card(self, it: Item, target: str | None) -> str:
        spec = it.text.strip()
        frame = self.frames.get(target or "")
        if not re.fullmatch(r"\d+(-\d+)?(,\d+(-\d+)?)*", spec):
            self.errors.append(f"story.md:{it.line}: '::: card' takes the step's line numbers it points at, e.g. '::: card 15,21-23'")
        elif frame:
            want = set()
            for part in spec.split(","):
                a, _, b = part.partition("-")
                want |= set(range(int(a), int(b or a) + 1))
            if missing := sorted(want - frame.lines):
                self.errors.append(
                    f"story.md:{it.line}: card points at line(s) {', '.join(map(str, missing))}, "
                    "which the step's code doesn't show (new-side numbers)"
                )
        kids = it.children
        why, rest = "", kids
        if kids and kids[0].kind == "md":
            why, _, rest_md = kids[0].text.strip().partition("\n\n")
            rest = ([Item("md", kids[0].line, text=rest_md)] if rest_md.strip() else []) + kids[1:]
        else:
            self.errors.append(f"story.md:{it.line}: a card starts with one line saying why it's attached")
        return (
            f'<div class="attach" data-to="{target or ""}" data-lines="{esc(spec)}">'
            f'<p class="why"><span class="to"></span>{self.inline(why.strip())}</p>{self.items(rest, "card")}</div>'
        )

    def b_fork(self, it: Item) -> str:
        branches = [c for c in it.children if c.kind == "box" and c.name == "branch"]
        if not branches or len(branches) != len([c for c in it.children if c.kind != "md" or c.text.strip()]):
            self.errors.append(f"story.md:{it.line}: '::: fork' holds only '::: branch' blocks")
        buttons, wraps = [], []
        for b in branches:
            title = b.text or "Branch"
            bid = f"br-{slug(title)}"
            while bid in self.ids:
                bid += "-x"
            self.ids[bid] = f"the branch at story.md:{b.line}"
            buttons.append(f'<button type="button" data-act="branch" aria-controls="{bid}" aria-expanded="false">{esc(title)}</button>')
            wraps.append(
                f'<div class="branch-wrap" id="{bid}" data-branch data-title="{esc(title)}" inert><div class="branch"><div class="branch-in">'
                f'<div class="branch-h"><button class="traffic" data-act="branch-close" title="Close (Esc)" aria-label="Close {esc(title)}">{X_SVG}</button>'
                f"<h4>{self.inline(title)}</h4></div>{self.items(b.children, 'branch')}</div></div></div>"
            )
        return f'<div class="fork" data-fork>{FORK_SVG}<span>{self.inline(it.text)}</span>{"".join(buttons)}</div>' + "".join(wraps)

    def b_note(self, it: Item) -> str:
        kind, _, title = it.text.partition(" ")
        if kind not in NOTE_KINDS:
            kind, title = "note", it.text
        cls = f"note {kind}" + (" review" if kind in REVIEW_NOTES else "")
        head = f'<b class="nt">{self.inline(title.strip())}</b>' if title.strip() else ""
        return f'<div class="{cls}">{head}{self.items(it.children, "note")}</div>'

    # ---- page ----

    def render(self, story: list[Item]) -> dict[str, str]:
        if self.link:
            self.defs = self.find_defs(story)
        h1 = next((i for i in story if i.kind == "h1"), None)
        self.title = re.sub(r"`", "", h1.text) if h1 else ""
        if not h1:
            self.errors.append("story.md: the story needs a '# Title'")
        chapters: list[tuple[Item, list[Item]]] = []
        hero: list[Item] = []
        for it in story:
            if it.kind == "h1":
                continue
            if it.kind == "h2":
                chapters.append((it, []))
            elif chapters:
                chapters[-1][1].append(it)
            else:
                hero.append(it)
        if any(not (i.kind == "md" or i.kind == "box" and i.name == "sketch") for i in hero):
            self.errors.append("story.md: only prose and '::: sketch' go between the title and the first chapter")
        lede = "".join(self.md_html(i.text, i.line, "lede") if i.kind == "md" else self.box(i, "hero") for i in hero)
        hero_html = (
            f'<section class="hero"><h1>{self.inline(h1.text if h1 else "")}</h1>'
            f'{lede}{self.hero_meta()}</section>'
        )
        out, num, seen = [], 0, set()
        for head, body in chapters:
            appendix = "appendix" in head.kw.get("class", [])
            title = head.text
            label = head.kw.get("map") or re.sub(r"`", "", title)
            cid = head.kw.get("id") or slug(label) or f"ch{len(out) + 1}"
            if cid in seen or cid in self.ids:
                self.errors.append(
                    f"story.md:{head.line}: chapter id {cid!r} is already used by {self.ids.get(cid, 'another chapter')}; "
                    "set another with {#id}"
                )
            elif reserved(cid):
                self.errors.append(f"story.md:{head.line}: chapter id {cid!r} is taken by the page itself; set another with {{#id}}")
            seen.add(cid)
            self.ids.setdefault(cid, f"the chapter at story.md:{head.line}")
            self.chapter = label
            inner = self.items(body, "chapter")
            where = esc(head.kw.get("where", ""))
            if appendix:
                out.append(
                    f'<section class="chapter appendix" id="{cid}" data-chapter="appendix" data-title="{esc(label)}" data-where="{where}">'
                    f'<div class="ch-head"><h2>{self.inline(title)}</h2></div>{inner}</section>'
                )
            else:
                num += 1
                out.append(
                    f'<section class="chapter" id="{cid}" data-chapter data-title="{esc(label)}" data-where="{where}">'
                    f'<div class="ch-head"><span class="ch-num">{num}</span><h2>{self.inline(title)}</h2></div>{inner}</section>'
                )
        if not num:
            self.errors.append("story.md: the story needs at least one '## Chapter'")
        out.append(self.not_in_story())
        return {"hero": hero_html, "chapters": "\n".join(x for x in out if x)}

    def hero_meta(self) -> str:
        if self.tour:
            where = "the working tree" if self.idx["worktree"] else f"git at {self.idx['head'][:7]}"
            repo = f"{self.idx['owner'] or 'local'}/{self.idx['name']}" + (f" on {self.idx['branch']}" if self.idx["branch"] else "")
            return f'<div class="hero-meta"><span>{esc(repo)}</span><span>Code rendered from {where}</span></div>'
        files = self.ix.files
        bits = []
        if self.idx["pr"]:
            ref = f"{self.idx['owner']}/{self.idx['name']}#{self.idx['pr']['number']}"
            bits.append(f'<a href="{esc(self.idx["pr"]["url"])}" target="_blank" rel="noopener">{esc(ref)}</a>')
        bits.append(f"<span>{len(files)} files {stat_html(sum(f.adds for f in files), sum(f.dels for f in files))}</span>")
        where = "the working tree" if self.idx["worktree"] else f"git at {self.idx['head'][:7]}"
        bits.append(f"<span>Code rendered from {where}</span>")
        return f'<div class="hero-meta">{"".join(bits)}</div>'

    def not_in_story(self) -> str:
        groups: dict[str, list[str]] = {}
        for f in self.ix.files:
            if not f.excluded:
                continue
            key = f.excluded if f.excluded in GROUP_TITLES else "story"
            note = (
                f'<span class="note-line">{esc(f.excluded.removeprefix("story: "))}</span>' if key == "story" else ""
            )
            attr = url_attr("data-gh", self.gh_diff(f.path)) + f' data-fd="{self.fd_file[f.path]}"'
            fid = self.new_id(None, 0)
            groups.setdefault(key, []).append(
                f'<details class="file-item" id="{fid}"{attr}><summary>{path_html(f.path)}{note}'
                f'<span class="grow"></span>{stat_html(f.adds, f.dels)}</summary>'
                f"{self.file_code(f, fid, lazy=True)}</details>"
            )
        if not groups:
            return ""
        names = {**GROUP_TITLES, "story": "Left out on purpose"}
        body = "".join(
            f'<div class="nis-group"><h4>{names[k]}<span>{len(v)} files</span></h4>{"".join(v)}</div>'
            for k, v in sorted(groups.items(), key=lambda kv: list(names).index(kv[0]))
        )
        where = ", ".join(names[k].lower() for k in sorted(groups, key=lambda k: list(names).index(k)))
        return (
            f'<section class="chapter appendix" id="not-in-story" data-chapter="appendix" data-title="Not in story" '
            f'data-where="{esc(where[:1].upper() + where[1:])}"><div class="ch-head"><h2>Not in story</h2></div>'
            f'<p class="prose">Open any file to see its diff.</p>{body}</section>'
        )

    def fulldiff(self) -> str:
        nav, body = [], []
        for f in self.ix.files:
            fslug = self.fd_file[f.path]
            nav.append(f'<a href="#{fslug}" data-fd="{fslug}">{path_html(f.path)}{stat_html(f.adds, f.dels)}</a>')
            # each hunk is its header alone: the page fills the rows in from the file's source when the diff opens
            hunks = []
            for h in f.hunks:
                seq = self.diff_seq(f)
                backs = "".join(
                    f'<button class="fd-back" data-goto="{x}">In story</button>' for x in dict.fromkeys(self.used.get(h.id, []))
                )
                news = [r.new for r in h.rows if r.new] or [0]
                where = f"Lines {min(news)}–{max(news)}" if max(news) else "Removed lines"
                hunks.append(
                    f'<div class="gap fd-hh" id="{self.fd_hunk[h.id]}" data-at="{seq.start(h)}" data-len="{len(h.rows)}">'
                    f'<span class="wh">{where}</span><code>{esc(h.header)}</code><span class="grow"></span>{backs}</div>'
                )
            if hunks:
                hunks = [f'<div class="code u" data-src="{self.diff_seq(f).i}">{"".join(hunks)}</div>']
            if not f.hunks or f.meta:
                record = f.meta if f.hunks else change_record(f)
                hunks.insert(0, f'<div class="fd-hh"><span class="wh">{esc(record)}</span></div>')
            status = {"A": "added", "D": "deleted", "R": "renamed", "C": "copied", "T": "type changed"}.get(f.status, "")
            attr = url_attr("data-gh", self.gh_diff(f.path))
            body.append(
                f'<section class="fd-file" id="{fslug}"{attr}><header class="fd-head">'
                '<button class="fd-tog" data-act="fd-toggle" aria-expanded="true" aria-label="Collapse file">'
                '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M4 6l4 4 4-4"/></svg></button>'
                f'{path_html(f.path)}{f"<span class=chip>{status}</span>" if status else ""}<span class="grow"></span>'
                f'{stat_html(f.adds, f.dels)}</header><div class="fd-body">{"".join(hunks)}</div></section>'
            )
        return (
            '<aside id="files" class="files" hidden><div class="files-in" role="dialog" aria-modal="true" aria-label="Full diff">'
            f'<div class="files-bar"><button class="traffic" data-act="close-files" title="Close (Esc)" aria-label="Close full diff">{X_SVG}</button>'
            f'<div class="files-title">Full diff<span>{len(self.ix.files)} files</span></div><span class="grow"></span>'
            '<button class="tbtn" data-act="fd-all">Collapse all</button></div>'
            f'<div class="files-main"><nav class="files-nav">{"".join(nav)}</nav>'
            '<div class="files-resize" role="separator" aria-orientation="vertical" aria-label="Resize file list" tabindex="0"></div>'
            f'<div class="files-body">{"".join(body)}</div></div></div></aside>'
        )

    # ---- checks ----

    def coverage_gaps(self) -> list[str]:
        gaps = []
        for f in self.ix.files:
            if f.excluded:
                continue
            if f.file_level:
                if f.path not in self.referenced:
                    gaps.append(f"  {f.path}  ({change_record(f)}): not referenced anywhere")
                continue
            for h in f.hunks:
                missing = [r for r in h.rows if r.kind != " " and (h.id, id(r)) not in self.covered]
                if f.path in self.referenced:
                    missing = [r for r in missing if not auto_covered(h, r)]
                if missing:
                    nums = ", ".join(f"{'L' if r.kind == '-' else 'R'}{r.old if r.kind == '-' else r.new}" for r in missing[:6])
                    gaps.append(f"  {h.id}  {len(missing)} changed lines not shown ({nums}{', …' if len(missing) > 6 else ''})")
        return gaps

    def trace_warnings(self) -> None:
        for g, _ in self.traces:
            if g not in self.trace_hits:
                self.warnings.append(f"front matter: trace {g!r} never appears in the rendered code")


IMPORT_LINE = re.compile(
    r"\s*(?:"
    r"(?:from\s+[\w.]+\s+)?import\s+[\w.]+(?:\s+as\s+\w+)?(?:\s*,\s*[\w.]+(?:\s+as\s+\w+)?)*\s*"  # Python
    r"|import\s+(?:type\s+)?(?:[\w$*{}\s,]+\s+from\s+)?['\"][^'\"]+['\"]\s*;?\s*"  # JS/TS
    r"|import\s+(?:static\s+)?[\w.]+(?:\.\*)?\s*;?\s*"  # Java, Kotlin, Scala, Go single
    r"|#include\s*[<\"][^>\"]+[>\"]\s*"  # C, C++
    r"|using\s+(?:static\s+)?[\w.]+(?:\s*=\s*[\w.<>]+)?\s*;\s*"  # C#
    r"|use\s+[\w:\\{}, *]+(?:\s+as\s+\w+)?\s*;\s*"  # Rust, PHP
    r")(?://.*|#.*)?"
)


def change_runs(h: Hunk):
    """Each run of removed rows with the added rows right after it."""
    rows, i = h.rows, 0
    while i < len(rows):
        if rows[i].kind == " ":
            i += 1
            continue
        j = i
        while j < len(rows) and rows[j].kind == "-":
            j += 1
        k = j
        while k < len(rows) and rows[k].kind == "+":
            k += 1
        yield rows[i:j], rows[j:k]
        i = max(k, i + 1)


def auto_covered(h: Hunk, r: Row) -> bool:
    """D19, kept narrow: blank lines, trailing-whitespace edits of a line that stays in place, and hunks that
    only add, drop or reorder whole import statements count as shown once their file is in the story."""
    if not r.text.strip():
        return True
    for dels, adds in change_runs(h):
        if r in dels or r in adds:
            if len(dels) == len(adds):
                mine, other = (dels, adds) if r in dels else (adds, dels)
                if other[mine.index(r)].text.rstrip() == r.text.rstrip():
                    return True
            break
    changed = [x for x in h.rows if x.kind != " " and x.text.strip()]
    if changed and all(IMPORT_LINE.fullmatch(x.text) for x in changed):
        removed = sorted(x.text.rstrip() for x in changed if x.kind == "-")
        added = sorted(x.text.rstrip() for x in changed if x.kind == "+")
        return not removed or not added or removed == added
    return False


def change_record(f: FileDiff) -> str:
    if f.submodule:
        return "submodule pointer changed"
    if f.symlink:
        return "symlink " + {"A": "added", "D": "removed"}.get(f.status, "changed")
    if f.binary:
        return "binary file " + {"A": "added", "D": "deleted"}.get(f.status, "changed")
    if not f.hunks and f.old_path:
        return f"renamed from {f.old_path}, content unchanged"
    if f.status in ("A", "D"):
        return ("added" if f.status == "A" else "deleted") + ("" if f.hunks else ", empty")
    if not f.hunks and f.old_mode != f.new_mode:
        return f"mode {f.old_mode} -> {f.new_mode}"
    return "changed"


# ---------- build ----------


class TextView(HTMLParser):
    """The story as plain text, for an agent that can't look at the page: prose, frame headers, code rows
    with their line numbers, cards with the lines they point at, notes and branches."""

    SKIP = {"svg", "button", "script", "style"}
    BLOCK = {"p", "li", "h1", "h2", "h3", "h4", "figcaption", "summary", "pre", "tr"}
    VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.out: list[str] = []
        self.skip = 0
        self.row: list[str] | None = None
        self.quiet = 0  # inside a span whose text the view replaces: line numbers, signs, the no-newline badge
        self.pre = 0
        self.sep = False  # a " · " owed before the next label, dropped if the label turns out empty
        self.tagged = False  # a frame or file tag was just written; its caption continues the line
        self.stack: list[str] = []
        self.cls_stack: list[str] = []
        self.parent = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        self.parent = self.cls_stack[-1] if self.cls_stack else ""
        under = self.stack[-1] if self.stack else ""
        if tag not in self.VOID:
            self.cls_stack.append(" ".join(cls))
            self.stack.append(tag)
        if tag in self.SKIP or self.skip:
            self.skip += tag not in self.VOID
            return
        n0 = len(self.out)
        self._start(tag, cls, a, under)
        if self.row is not None or any("\n" in x for x in self.out[n0:]):
            self.sep = False  # a separator never crosses into a new line or a code row
        if tag == "pre":
            self.pre += 1

    def _start(self, tag, cls, a, under):
        tagged, self.tagged = self.tagged, False
        if "row" in cls:
            kind = {"c": " ", "d": "-", "a": "+"}.get(cls[1] if len(cls) > 1 else "c", " ")
            self.row = [f"{a.get('data-o') or '':>5} {a.get('data-n') or '':>5} {kind} "]
        elif "ln" in cls or "sg" in cls:
            self.quiet += 1
        elif "nonl" in cls:
            self.quiet += 1
            self.out.append("  [no newline at end of file]") if self.row is None else self.row.append(" [no newline]")
        elif tag == "section" and "chapter" in cls:
            self.out.append("\n\n## ")
        elif tag in ("h1", "h2"):
            self.out.append("\n# " if tag == "h1" else "" if self.out and self.out[-1].endswith(" ") else " ")
        elif tag == "figure":
            label = "pseudo-code" if "sketch" in cls else "tree" if "tree" in cls else "code"
            self.out.append(f"\n\n[{label}{' #' + a['id'] if a.get('id') else ''}] ")
            self.tagged = True
        elif tag == "details" and "file-item" in cls:
            self.out.append("\n\n[collapsed on the page] ")
            self.tagged = True
        elif "trow" in cls:
            self.out.append("\n  " + a.get("data-t", ""))
            self.skip += 1  # the row's own spans repeat what data-t says
        elif tag == "div" and "file-item" in self.parent:
            self.skip += 1  # a collapsed file's rows; the summary line above stands for them
        elif "attach" in cls:
            self.out.append(f"\n\n→ card on lines {a.get('data-lines', '')} of #{a.get('data-to', '')}: ")
        elif "note" in cls:
            kinds = [c for c in cls if c not in ("note", "review")]
            self.out.append(f"\n\n[{' '.join(kinds + ['note'])}] ")
        elif "hero-meta" in cls:
            self.out.append("\n\n")
        elif "branch-wrap" in cls:
            self.out.append(f"\n\n[branch: {a.get('data-title', '')}]")
        elif "fork" in cls:
            self.out.append("\n\n[fork] ")
        elif tag == "span" and self.parent == "stamp":
            self.out.append(" ")
        elif (
            set(cls) & {"sym", "chip", "stat", "stamp", "note-line"}
            or (tag == "span" and not cls and under in ("figcaption", "h4"))
            or (tag in ("a", "span") and under == "div" and "hero-meta" in self.parent)
        ):
            self.sep = not "".join(self.out[-1:]).endswith("\n")  # the first item on a line takes no separator
        elif tag == "table":
            self.out.append("\n")
        elif tag in ("td", "th"):
            if self.out and not self.out[-1].strip(" "):
                self.out.pop()
            if self.out and not self.out[-1].endswith("\n"):
                self.out[-1] = self.out[-1].rstrip(" ")
                self.out.append(" | ")
        elif "gap" in cls:
            self.out.append("\n  ⋯ ")
        elif "rip-site" in cls:
            self.out.append(f"\n  [more site: {a.get('data-path', '')}] ")
        elif tag in self.BLOCK and not (tagged and tag in ("figcaption", "summary")):
            self.out.append("\n\n" if tag in ("p", "h4") else "\n")

    def handle_endtag(self, tag):
        if tag in self.VOID:
            return
        if self.stack:
            self.stack.pop()
            self.cls_stack.pop()
        if self.skip:
            self.skip -= 1
            return
        if tag == "div" and self.row is not None and not self.quiet:
            # a row ends at its own closing div; code holds no divs
            self.out.append("\n" + "".join(self.row).rstrip())
            self.row = None
        elif tag == "span" and self.quiet:
            self.quiet -= 1
        elif tag == "pre" and self.pre:
            self.pre -= 1

    def handle_data(self, data):
        if self.skip or self.quiet:
            return
        if self.row is not None:
            self.row.append(data.replace("\u00a0", " "))
        elif self.pre:
            self.out.append(data)
        else:
            if self.sep and data.strip():
                if self.out:
                    self.out[-1] = self.out[-1].rstrip(" ")
                self.out.append(" · ")
                self.sep = False
            self.out.append(re.sub(r"\s+", " ", data))

    def text(self) -> str:
        s = re.sub(r"(?m)[ \t]+$", "", "".join(self.out))
        return re.sub(r"\n{3,}", "\n\n", s).strip() + "\n"


def text_view(fragment: str) -> str:
    v = TextView()
    v.feed(fragment)
    return v.text()


def page_header(idx: dict, story_title: str) -> tuple[str, str, str, str]:
    if idx.get("tour"):
        head = "working tree" if idx["worktree"] else idx["head"][:7]
        refs = (f"{esc(idx['branch'])} " if idx["branch"] else "") + f"<b>{head}</b>"
        return story_title or f"Tour of {idx['name']}", esc(story_title or f"Tour of {idx['name']}"), refs, f"The code at {head}"
    pr = idx["pr"]
    title = story_title or (pr["title"] if pr else idx["branch"] or idx["head_ref"])
    hdr = esc(title)
    if pr:
        hdr = f'<a href="{esc(pr["url"])}" target="_blank" rel="noopener">#{pr["number"]}</a>{hdr}'
    base_name = re.sub(r"^origin/", "", idx["base_ref"])
    head = "working tree" if idx["worktree"] else idx["head"][:7]
    arrow = '<svg class="i" viewBox="0 0 16 16" style="width:12px;height:12px"><path d="M3 8h10M9 4l4 4-4 4"/></svg>'
    refs = f"{esc(base_name)} <b>{idx['merge_base'][:7]}</b>{arrow}<b>{head}</b>"
    refs_title = f"Diff from the merge-base {idx['merge_base'][:7]} to {head}"
    return title, hdr, refs, refs_title


ACCEPT_AGAIN = "--accept applies to a build that succeeds; pass it again once the errors above are fixed"


def cmd_build(a: argparse.Namespace, write: bool = True) -> None:
    try:
        build(a, write)
    except Fail as e:
        raise Fail(f"{e}\n{ACCEPT_AGAIN}") if getattr(a, "accept", False) else e


def build(a: argparse.Namespace, write: bool) -> None:
    ix = load(a.dir, marks=write)
    sp = ix.dir / "story.md"
    if not sp.exists():
        raise Fail(f"{sp} not found; write the story first")
    front, story = parse_story(sp.read_text())
    front_errors, front_warnings = check_front(front)
    if front_errors:
        if getattr(a, "accept", False):
            front_errors.append(ACCEPT_AGAIN)
        print("\n".join(f"error: {e}" for e in front_errors), file=sys.stderr)
        raise SystemExit(1)
    r = Renderer(ix, front, link=write)
    r.warnings += front_warnings
    parts = r.render(story)
    fulldiff = r.fulldiff()
    r.trace_warnings()
    gaps = r.coverage_gaps()
    stale = [] if getattr(a, "accept", False) else stale_refs(ix, r.refs)
    for w in r.warnings:
        print(f"warning: {w}")
    for n in r.notes:
        print(f"note: {n}")
    problems = list(r.errors)
    if stale:
        problems.append(
            "the code under these anchors changed since the last build. Re-read each with `show`, update the "
            "chapters that describe it, then run build again with --accept:\n" + "\n".join(stale)
        )
    if gaps:
        problems.append(
            "coverage: these changes aren't in the story. Place them with @diff in the chapter they belong to, "
            "show a whole file with @also (an appendix suits files outside the walk), or exclude it in front "
            "matter with a reason:\n" + "\n".join(gaps)
        )
    if problems:
        if getattr(a, "accept", False):
            problems.append(ACCEPT_AGAIN)
        print("\n".join(f"error: {p}" for p in problems), file=sys.stderr)
        raise SystemExit(1)
    if not write:
        print("check ok")
        return
    idx = ix.idx
    title, hdr, refs, refs_title = page_header(idx, r.title)
    m = front.get("map") or {}
    map_title = esc(str(m.get("title") or "Story")) + (f"<span>{esc(str(m['subtitle']))}</span>" if m.get("subtitle") else "")
    # stable across pushes, so reader settings survive; reviewed marks are keyed by frame content instead
    story_id = f"{idx['owner'] or 'local'}/{idx['name']}" + (
        f"#{idx['pr']['number']}" if idx["pr"] else ":tour" if idx.get("tour") else f":{idx['branch'] or idx['head_ref']}"
    )
    values = {
        "page_title": esc(str(front.get("title") or title)),
        "css": (ASSETS / "story.css").read_text() + "\n" + syntax_themes_css(),
        "js": (ASSETS / "story.js").read_text(),
        "story_id": esc(story_id),
        "mode": "tour" if idx.get("tour") else "change",
        "traces_json": esc(json.dumps(r.trace_names)),
        "syn_json": esc(json.dumps(SYNTAX_THEMES)),
        "syn_default": SYNTAX_DEFAULT,
        "hdr_title": hdr,
        "refs": refs,
        "refs_title": esc(refs_title),
        "map_title": map_title,
        "hero": parts["hero"],
        "chapters": parts["chapters"],
        "fulldiff": fulldiff,
        "sources": r.sources() + r.defs_json(),
    }
    tpl = (ASSETS / "template.html").read_text()
    page = re.sub(r"\{\{(\w+)\}\}", lambda mm: values[mm[1]], tpl)
    out = ix.dir / "story.html"
    out.write_text(page)
    (ix.dir / "story.txt").write_text(text_view(parts["hero"] + parts["chapters"]))
    (ix.dir / "anchors.json").write_text(
        json.dumps({"merge_base": idx["merge_base"], "head": idx["head"], "refs": {k: v[0] for k, v in r.refs.items()}}, indent=1)
    )
    print(f"built {out}")
    if getattr(a, "open", False):
        webbrowser.open(out.as_uri())


def stale_refs(ix: Indexed, refs: dict[str, tuple[str, list[str]]]) -> list[str]:
    """Anchors whose code differs from the last build's, wherever the base or head moved."""
    p = ix.dir / "anchors.json"
    if not p.exists():
        return []
    old = json.loads(p.read_text()).get("refs", {})
    stale = {ref: list(chs) for ref, (h, chs) in refs.items() if ref in old and old[ref] != h}
    for ref in [r for r in stale if not r.startswith("file:")]:
        if (f := "file:" + ref.rpartition("#")[0]) in stale:
            stale[f] += stale.pop(ref)
    return [f"  {ref}  (chapters: {', '.join(dict.fromkeys(chs))})" for ref, chs in stale.items()]


# ---------- cli ----------


def main() -> None:
    p = argparse.ArgumentParser(prog="codestory", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    i = sub.add_parser("index", help="index a change and print its hunks")
    i.add_argument("--repo", default=".")
    i.add_argument("--base", help="base ref (default: the PR's base, else origin's default branch)")
    i.add_argument("--head", help=f"head ref, or {WORKTREE} for uncommitted work (default: the PR head, else HEAD)")
    i.add_argument("--pr", help="GitHub PR URL, read with gh for intent only")
    i.add_argument("--tour", action="store_true", help="a tour of the code at one commit instead of a change (no base, no diff)")
    i.add_argument("--out", help="story folder (default: ~/.code-story/<owner>/<repo>/<pr-N|branch>/)")
    s = sub.add_parser("show", help="print hunks with row numbers, or file lines")
    s.add_argument("dir")
    s.add_argument("spec", nargs="+")
    b = sub.add_parser("build", help="build story.html from story.md")
    b.add_argument("dir")
    b.add_argument("--open", action="store_true", help="open the page in the browser")
    b.add_argument("--accept", action="store_true", help="the prose was updated for changed anchors; record the new ones")
    c = sub.add_parser("check", help="run build's checks without writing")
    c.add_argument("dir")
    c.add_argument("--accept", action="store_true", help="check as build --accept would")
    a = p.parse_args()
    try:
        if a.cmd == "index":
            cmd_index(a)
        elif a.cmd == "show":
            cmd_show(a)
        elif a.cmd == "build":
            cmd_build(a)
        else:
            cmd_build(a, write=False)
    except Fail as e:
        print(f"error: {e}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
