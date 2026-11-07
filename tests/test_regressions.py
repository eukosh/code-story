import importlib.util
import json
import sys

from conftest import ENGINE, LINES


def fake_gh(repo, pr):
    bin_dir = repo.path.parent / "bin"
    bin_dir.mkdir()
    gh = bin_dir / "gh"
    gh.write_text(f"#!/bin/sh\ncat <<'EOF'\n{json.dumps(pr)}\nEOF\n")
    gh.chmod(0o755)
    repo.env["PATH"] = f"{bin_dir}:{repo.env['PATH']}"


def pr_json(base_sha, head_sha):
    return {
        "number": 7, "title": "Change", "body": "", "url": "https://github.com/example/story/pull/7",
        "baseRefName": "main", "baseRefOid": base_sha, "headRefName": "feature", "headRefOid": head_sha,
    }


def test_pr_base_is_githubs_base_commit_not_a_stale_remote_branch(repo):
    old = repo.commit({"app.py": "a = 1\n"})
    base = repo.commit({"lib.py": "b = 1\n"})
    head = repo.commit({"app.py": "a = 2\n"})
    repo.git("remote", "add", "origin", "https://github.com/example/story.git")
    repo.git("update-ref", "refs/remotes/origin/main", old)
    fake_gh(repo, pr_json(base, head))
    repo.run("index", "--repo", repo.path, "--pr", "https://github.com/example/story/pull/7", "--out", repo.out)
    index = repo.json("index.json")
    assert index["merge_base"] == base
    assert [f["path"] for f in index["files"]] == ["app.py"]


def test_worktree_story_with_pr_has_no_head_links(repo):
    base = repo.commit({"app.py": "a = 1\n"})
    head = repo.commit({"app.py": "a = 2\n"})
    repo.git("remote", "add", "origin", "https://github.com/example/story.git")
    repo.git("update-ref", "refs/remotes/origin/main", head)
    repo.write({"app.py": "a = 3\n"})
    fake_gh(repo, pr_json(base, head))
    repo.run("index", "--repo", repo.path, "--pr", "https://github.com/example/story/pull/7",
             "--head", "WORKTREE", "--out", repo.out)
    repo.story("@diff app.py#h1")
    repo.build()
    html = repo.read("story.html")
    assert "pull/7/files" not in html
    assert not [a for a in repo.tags() if "/blob/" in a.get("data-blob", "") and base not in a["data-blob"]]


def test_base_links_need_the_merge_base_on_a_remote(repo):
    base = repo.commit({"app.py": "a = 1\nb = 1\n"})
    repo.commit({"app.py": "a = 2\nb = 1\n"})
    repo.git("remote", "add", "origin", "https://github.com/example/story.git")
    repo.index()
    repo.story("@diff app.py#h1\n@ctx app.py@base 2 id=old")
    repo.build()
    assert "data-blob" not in str(repo.frame("old"))
    repo.git("update-ref", "refs/remotes/origin/main", base)
    repo.build()
    assert f"/blob/{base}/app.py" in repo.frame("old").get("data-blob", "")


def test_removed_only_frame_is_stamped_at_the_merge_base(repo):
    base = repo.commit({"app.py": LINES})
    repo.commit({"app.py": LINES.replace("value_12 = 12\n", "")})
    repo.index()
    repo.story("@diff app.py#h1 rows=4-4 id=gone\n\n@diff app.py#h1")
    repo.build()
    caption = next(l for l in repo.read("story.txt").splitlines() if l.startswith("[code #gone]"))
    assert f"{base[:7]} L12–12" in caption


def test_lone_carriage_return_keeps_highlighting_after_it(repo):
    repo.commit({"app.py": b"a = 1\nmid = 1\rtail\nnext_value = 2\n"})
    repo.commit({"app.py": b"a = 3\nmid = 1\rtail\nnext_value = 2\n"})
    repo.index()
    repo.story("@diff app.py#h1\n@ctx app.py@head 3")
    repo.build()
    assert 'class="n">next_value</span>' in repo.read("story.html")


def test_csharp_using_statement_is_not_an_import(repo):
    far = "".join(f"x{n} = {n};\n" for n in range(20))
    repo.commit({"app.cs": "a = 1;\n" + far})
    repo.commit({"app.cs": "a = 2;\n" + far + "using (var s = Open())\nusing System.Text;\n"})
    repo.index()
    repo.story("@diff app.cs#h1")
    gaps = repo.build(ok=False).stderr
    assert "app.cs#h2  2 changed lines" in gaps


def test_csharp_using_directive_alone_is_an_import(repo):
    far = "".join(f"x{n} = {n};\n" for n in range(20))
    repo.commit({"app.cs": "a = 1;\n" + far})
    repo.commit({"app.cs": "a = 2;\n" + far + "using System.Text;\n"})
    repo.index()
    repo.story("@diff app.cs#h1")
    repo.build()


def test_text_view_does_not_stack_void_tags():
    spec = importlib.util.spec_from_file_location("codestory", ENGINE)
    engine = importlib.util.module_from_spec(spec)
    sys.modules["codestory"] = engine
    spec.loader.exec_module(engine)
    view = engine.TextView()
    view.feed('<div class="x"><span class="path">dir/<wbr>file.py<br></span><hr></div>')
    assert view.stack == [] and view.cls_stack == []
