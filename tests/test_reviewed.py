import hashlib
import re
from html.parser import HTMLParser

from conftest import LINES


def test_frame_hash_survives_earlier_hunk_and_changes_with_content(repo):
    repo.commit({"app.py": LINES})
    repo.commit({"app.py": LINES.replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    repo.story("@diff app.py#h1 id=target")
    repo.build()
    original = repo.frame("target")["data-hash"]
    repo.commit({"app.py": (repo.path / "app.py").read_text().replace("value_2 = 2", "value_2 = 200")})
    repo.index()
    repo.story("@diff app.py#h1\n@diff app.py#h2 id=target")
    repo.build("--accept")
    assert repo.frame("target")["data-hash"] == original
    repo.commit({"app.py": (repo.path / "app.py").read_text().replace("value_25 = 250", "value_25 = 251")})
    repo.index()
    repo.build("--accept")
    assert repo.frame("target")["data-hash"] != original


def test_ripple_hash_survives_folded_hunk_renumbering_but_tracks_content(repo):
    repo.commit({"a.py": "old\n", "b.py": LINES})
    repo.commit({"a.py": "new\n", "b.py": LINES.replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    repo.story("@ripple a.py#h1 b.py#h1 id=target")
    repo.build()
    original = repo.frame("target")["data-hash"]
    repo.commit({"b.py": (repo.path / "b.py").read_text().replace("value_2 = 2", "value_2 = 200")})
    repo.index()
    repo.story("@diff b.py#h1\n@ripple a.py#h1 b.py#h2 id=target")
    repo.build("--accept")
    assert repo.frame("target")["data-hash"] == original
    repo.commit({"b.py": (repo.path / "b.py").read_text().replace("value_25 = 250", "value_25 = 251")})
    repo.index()
    repo.build("--accept")
    assert repo.frame("target")["data-hash"] != original


def test_ripple_hash_includes_folded_site_path(repo):
    repo.commit({"a.py": "old\n", "b.py": "old\n", "c.py": "old\n"})
    repo.commit({"a.py": "new\n", "b.py": "new\n", "c.py": "new\n"})
    repo.index()
    repo.story("@ripple a.py#h1 b.py#h1 id=target\n@also c.py")
    repo.build()
    original = repo.frame("target")["data-hash"]
    repo.story("@ripple a.py#h1 c.py#h1 id=target\n@also b.py")
    repo.build()
    assert repo.frame("target")["data-hash"] != original


def test_full_diff_file_and_hunk_ids_are_unique(repo):
    paths = ["a", "a-h1", "a-b.py", "a_b.py", "日本.py", "中文.py"]
    repo.commit({path: "old\n" for path in paths})
    repo.commit({path: "new\n" for path in paths})
    repo.index()
    repo.story("\n".join(f"@also {path}" for path in paths))
    repo.build()
    ids = [a["id"] for a in repo.tags() if a.get("id", "").startswith("fd-")]
    assert len(ids) == len(set(ids)) == 2 * len(paths)
    assert all(a["data-fd"] in ids for a in repo.tags() if a.get("data-fd"))


def test_every_frame_header_carries_its_fold_button(changed):
    changed.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two\n@ctx src/context.py@head 2 id=ctx")
    changed.build()
    folds = [a for a in changed.tags("button") if a.get("data-act") == "frame-toggle"]
    assert len(folds) == len(changed.tags("figure", "frame")) == 3
    assert all(a["aria-expanded"] == "true" for a in folds)


# ---- what a mark holds: the snippet's hash, and where its rows sit to tell twins apart (D44) ----

BLOCK = "".join(f"step_{n} = {n}\n" for n in range(1, 9))


def two_hunks(repo):
    """app.py with eight lines added after line 5 and one changed at line 25."""
    repo.commit({"app.py": LINES})
    new = LINES.replace("value_5 = 5\n", "value_5 = 5\n" + BLOCK).replace("value_25 = 25", "value_25 = 250")
    repo.commit({"app.py": new})
    repo.index()
    return new


class Rows(HTMLParser):
    """The places in their file's diff (data-i) of a frame's rows, None for a row without one."""

    def __init__(self, html, fid):
        super().__init__()
        self.fid, self.inside, self.rows = fid, False, []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "figure":
            self.inside = a.get("id") == self.fid
        elif self.inside and "row" in a.get("class", "").split():
            self.rows.append(int(a["data-i"]) if "data-i" in a else None)

    def handle_endtag(self, tag):
        if tag == "figure":
            self.inside = False


def places(repo, fid):
    return Rows(repo.read("story.html"), fid).rows


def test_a_snippet_hash_is_80_bits_and_starts_with_the_old_one(repo):
    repo.commit({"a.py": "old\n", "b.py": "old\n"})
    repo.commit({"a.py": "new\n", "b.py": "new\n"})
    repo.index()
    repo.story("@diff a.py#h1 id=one\n@ripple a.py#h1 b.py#h1 id=rip")
    repo.build()
    one, rip = repo.frame("one")["data-hash"], repo.frame("rip")["data-hash"]
    assert re.fullmatch(r"[0-9a-f]{20}", one) and re.fullmatch(r"[0-9a-f]{20}", rip)
    # what main stored: 8 characters of the same digests, so a legacy mark still finds its snippet
    old = hashlib.sha1(b"-old\n+new\n").hexdigest()[:8]
    assert one[:8] == old
    assert repo.frame("rip")["data-was"] == hashlib.sha1((old + "b.py" + old).encode()).hexdigest()[:8]


def test_a_ripple_hash_tells_apart_sites_whose_short_hashes_collide(repo):
    seen = {}
    for n in range(10**7):
        short = hashlib.sha1(f"-old\n+v{n}\n".encode()).hexdigest()[:8]
        if short in seen:
            break
        seen[short] = n
    repo.commit({"a.py": "old\n", "b.py": "old\n"})
    repo.commit({"a.py": "new\n", "b.py": f"v{seen[short]}\n"})
    repo.index()
    repo.story("@ripple a.py#h1 b.py#h1 id=rip")
    repo.build()
    before = repo.frame("rip")
    repo.commit({"b.py": f"v{n}\n"})
    repo.index()
    repo.build("--accept")
    after = repo.frame("rip")
    assert before["data-was"] == after["data-was"]
    assert before["data-hash"] != after["data-hash"]


def test_every_row_a_snippet_shows_carries_its_place(repo):
    repo.commit({"app.py": LINES, "b.py": "old\n"})
    new = LINES.replace("value_5 = 5\n", "value_5 = 5\n" + BLOCK).replace("value_25 = 25", "value_25 = 250")
    repo.commit({"app.py": new, "b.py": "new\n"})
    repo.index()
    repo.story("@diff app.py#h1 app.py#h2 id=both\n@diff app.py#h1 rows=3-5 id=part\n@ripple app.py#h2 b.py#h1 id=rip")
    repo.build()
    assert places(repo, "both") == list(range(22))
    assert places(repo, "part") == [2, 3, 4]
    assert places(repo, "rip") == list(range(14, 22)) + [None, None]


def test_places_shift_with_an_earlier_hunk_and_hashes_stay(repo):
    new = two_hunks(repo)
    repo.story("@diff app.py#h1\n@diff app.py#h2 id=target")
    repo.build()
    target = repo.frame("target")["data-hash"]
    assert places(repo, "target")[0] == 14
    repo.commit({"app.py": new.replace("value_15 = 15", "value_15 = 150")})
    repo.index()
    repo.story("@diff app.py#h1\n@diff app.py#h2\n@diff app.py#h3 id=target")
    repo.build("--accept")
    assert repo.frame("target")["data-hash"] == target
    assert places(repo, "target")[0] == 22


def test_a_branch_and_its_working_tree_give_the_same_marks(repo, tmp_path):
    repo.commit({"app.py": LINES})
    repo.git("checkout", "-q", "-b", "feature")
    repo.write({"app.py": LINES.replace("value_9 = 9", "value_9 = 90")})
    repo.index(head="WORKTREE")
    repo.story("@diff app.py#h1 id=target")
    repo.build()
    worktree = repo.frame("target")["data-hash"], places(repo, "target"), scope(repo)
    repo.commit()
    repo.out = tmp_path / "branch"
    repo.index()
    repo.story("@diff app.py#h1 id=target")
    repo.build()
    assert (repo.frame("target")["data-hash"], places(repo, "target"), scope(repo)) == worktree
    assert re.fullmatch(r"local/repo@[0-9a-f]{8}:feature", scope(repo))
    assert "_rk" not in repo.read("story.html")


# ---- whose marks a page reads: one change, whichever way it was indexed (D44) ----


def scope(repo):
    return repo.tags("body")[0]["data-marks"]


def test_a_pr_its_branch_and_its_working_tree_share_marks(repo, tmp_path):
    from test_regressions import fake_gh, pr_json

    base = repo.commit({"app.py": LINES})
    repo.git("remote", "add", "origin", "https://github.com/example/story.git")
    repo.git("checkout", "-q", "-b", "feature")
    head = repo.commit({"app.py": LINES.replace("value_9 = 9", "value_9 = 90")})
    fake_gh(repo, pr_json(base, head))
    found = []
    for name, args in [
        ("pr", ["--pr", "https://github.com/example/story/pull/7"]),
        ("branch", ["--base", base, "--head", "feature"]),
        ("remote", ["--base", base, "--head", "origin/feature"]),
        ("tree", ["--base", base, "--head", "WORKTREE"]),
    ]:
        if name == "remote":
            repo.git("update-ref", "refs/remotes/origin/feature", head)
        repo.out = tmp_path / name
        repo.run("index", "--repo", repo.path, *args, "--out", repo.out)
        repo.story("@diff app.py#h1 id=one")
        repo.build()
        found.append(scope(repo))
    assert found == ["example/story:feature"] * 4


def test_two_branches_or_a_fork_never_share_marks(repo, tmp_path):
    from test_regressions import fake_gh, pr_json

    base = repo.commit({"app.py": LINES})
    repo.git("remote", "add", "origin", "https://github.com/example/story.git")
    found = []
    for branch in ("one", "two"):
        repo.git("checkout", "-q", "-B", branch, base)
        repo.commit({"app.py": LINES.replace("value_9 = 9", f"value_9 = {branch}")})
        repo.out = tmp_path / branch
        repo.index(head=branch, base=base)
        repo.story("@diff app.py#h1")
        repo.build()
        found.append(scope(repo))
    pr = pr_json(base, repo.git("rev-parse", "HEAD")) | {"isCrossRepository": True, "headRepositoryOwner": {"login": "someone"}}
    fake_gh(repo, pr)
    repo.out = tmp_path / "fork"
    repo.run("index", "--repo", repo.path, "--pr", pr["url"], "--out", repo.out)
    repo.story("@diff app.py#h1")
    repo.build()
    found.append(scope(repo))
    assert found == ["example/story:one", "example/story:two", "example/story:someone:feature"]


def test_a_detached_head_and_same_named_local_repos_keep_apart(tmp_path):
    from conftest import Repo

    found = []
    for n in ("a", "b"):
        (tmp_path / n).mkdir()
        repo = Repo(tmp_path / n)
        repo.commit({"app.py": LINES})
        head = repo.commit({"app.py": LINES.replace("value_9 = 9", "value_9 = 90")})
        repo.git("checkout", "-q", "--detach")
        repo.index()
        repo.story("@diff app.py#h1")
        repo.build()
        found.append((scope(repo), head))
    (a, ha), (b, hb) = found
    assert a.startswith("local/repo@") and b.startswith("local/repo@") and a.split(":")[0] != b.split(":")[0]
    assert a.endswith(f"@{ha[:12]}") and b.endswith(f"@{hb[:12]}")
