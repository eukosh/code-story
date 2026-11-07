import os

import pytest


def test_explicit_base_head_uses_merge_base_and_pinned_objects(repo):
    root = repo.commit({"app.py": "old\n"})
    repo.git("checkout", "-qb", "feature")
    head = repo.commit({"app.py": "new\n"})
    repo.git("checkout", "main")
    base = repo.commit({"base-only.py": "unrelated\n"})
    repo.write({"app.py": "dirty\n"})
    repo.index(head=head, base=base)
    ix = repo.json("index.json")
    assert (ix["base"], ix["merge_base"], ix["head"]) == (base, root, head)
    assert ix["pr"] is None
    assert [f["path"] for f in ix["files"]] == ["app.py"]
    assert "new" in repo.run("show", repo.out, "app.py@head").stdout
    assert "dirty" not in repo.run("show", repo.out, "app.py@head").stdout


def test_worktree_snapshots_staged_untracked_and_force_added_ignored_files(repo):
    repo.commit({".gitignore": "ignored*\n", "app.py": "old\n"})
    repo.write({"staged.py": "staged\n", "ignored-kept.py": "forced\n"})
    repo.git("add", "staged.py")
    repo.git("add", "-f", "ignored-kept.py")
    repo.write({"app.py": "unstaged\n", "new.py": "untracked\n", "ignored-dropped.py": "hidden\n"})
    index = repo.path / ".git/index"
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    repo.index(head="WORKTREE")
    assert {f["path"] for f in repo.json("index.json")["files"]} == {
        "app.py", "staged.py", "ignored-kept.py", "new.py",
    }
    repo.story("\n".join(f"@also {p}" for p in ("app.py", "staged.py", "ignored-kept.py", "new.py")))
    repo.build()
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
    for path, text in [("staged.py", "staged"), ("new.py", "untracked"), ("ignored-kept.py", "forced"), ("app.py", "unstaged")]:
        assert text in repo.run("show", repo.out, f"{path}@head").stdout
    repo.write({"new.py": "changed again\n"})
    assert "working tree changed since index" in repo.run("check", repo.out, ok=False).stderr


def test_worktree_detects_assume_unchanged_and_preserves_real_index(repo):
    repo.commit({"app.py": "old\n"})
    repo.git("update-index", "--assume-unchanged", "app.py")
    repo.write({"app.py": "new\n"})
    index = repo.path / ".git/index"
    before = (index.read_bytes(), index.stat().st_mtime_ns)
    repo.index(head="WORKTREE")
    assert "new" in repo.run("show", repo.out, "app.py@head").stdout
    repo.story("@diff app.py#h1")
    repo.build()
    assert (index.read_bytes(), index.stat().st_mtime_ns) == before
    assert repo.git("ls-files", "-v") == "h app.py"
    repo.write({"app.py": "yet\n"})
    assert "working tree changed since index" in repo.run("check", repo.out, ok=False).stderr


def test_worktree_detects_same_second_same_size_edit(repo):
    repo.git("config", "core.trustctime", "false")
    repo.commit({"app.py": "old\n"})
    path = repo.path / "app.py"
    timestamp = path.stat().st_mtime_ns
    repo.write({"app.py": "new\n"})
    # Equal cached stat data forces Git's racy-clean path, independent of the machine's speed.
    os.utime(path, ns=(timestamp, timestamp))
    os.utime(repo.path / ".git/index", ns=(timestamp, timestamp))
    repo.index(head="WORKTREE")
    assert "new" in repo.run("show", repo.out, "app.py@head").stdout


def test_worktree_refuses_output_inside_repo(repo):
    repo.commit({"app.py": "old\n"})
    repo.write({"app.py": "new\n"})
    result = repo.index(head="WORKTREE", out=repo.path / "story", ok=False)
    assert "is inside the repo" in result.stderr
    assert "pick a folder outside" in result.stderr
    assert not (repo.path / "story").exists()


@pytest.mark.parametrize("head", ["HEAD", "WORKTREE"])
def test_unborn_head_has_actionable_message(repo, head):
    assert "repo has no commits yet" in repo.index(head=head, ok=False).stderr


def test_detached_head_default_folder_uses_short_sha(changed):
    repo = changed
    repo.git("checkout", "--detach")
    sha = repo.git("rev-parse", "HEAD")
    result = repo.run("index", "--repo", repo.path, "--base", repo.base)
    expected = f"{repo.env['CODE_STORY_HOME']}/local/repo/{sha[:7]}"
    assert f"story     {expected}/" in result.stdout


def test_worktree_generated_attributes_come_from_snapshot(repo):
    repo.commit({"app.py": "old\n"})
    repo.write({"app.py": "new\n", ".gitattributes": "app.py linguist-generated\n"})
    repo.index(head="WORKTREE")
    files = {f["path"]: f for f in repo.json("index.json")["files"]}
    assert files["app.py"]["excluded"] == "generated"
