import json
import shlex
from urllib.parse import quote

import pytest

from conftest import LINES


def test_rename_with_edits_keeps_metadata_and_requires_every_hunk(repo):
    repo.commit({"old.py": LINES})
    repo.git("mv", "old.py", "new.py")
    repo.commit({"new.py": LINES.replace("value_2 = 2", "value_2 = 200").replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    file = repo.json("index.json")["files"][0]
    assert (file["status"], file["old_path"], len(file["hunks"])) == ("R", "old.py", 2)
    repo.story("@diff new.py#h1")
    assert "new.py#h2" in repo.build(ok=False).stderr
    repo.story("@diff new.py#h1 new.py#h2")
    repo.build()
    assert "renamed from old.py" in repo.read("story.txt")
    assert "at base it was old.py" in repo.run("show", repo.out, "new.py@base", ok=False).stderr
    assert '<span class="sg">-</span><code><span class="n">value_2</span>' in repo.read("story.html")


@pytest.mark.parametrize("edited", [False, True])
def test_mode_change_is_visible_and_edits_remain_strict(repo, edited):
    repo.commit({"app.py": LINES})
    (repo.path / "app.py").chmod(0o755)
    if edited:
        repo.write({"app.py": LINES.replace("value_2 = 2", "value_2 = 200").replace("value_25 = 25", "value_25 = 250")})
    repo.commit()
    repo.index()
    file = repo.json("index.json")["files"][0]
    assert (file["old_mode"], file["new_mode"]) == ("100644", "100755")
    repo.story("@diff app.py#h1" if edited else "")
    assert "coverage:" in repo.build(ok=False).stderr
    repo.story("@diff app.py#h1 app.py#h2" if edited else "@also app.py")
    repo.build()
    if edited:
        assert "app.py · mode 100644 → 100755" in repo.read("story.txt")
    else:
        assert "mode 100644 -&gt; 100755" in repo.read("story.html")


def test_file_to_symlink_merges_patch_sections_without_unchanged_gap(repo):
    repo.commit({"app.py": "original\n"})
    (repo.path / "app.py").unlink()
    (repo.path / "app.py").symlink_to("target.py")
    repo.commit()
    repo.index()
    files = repo.json("index.json")["files"]
    assert len(files) == 1
    assert (files[0]["status"], files[0]["old_mode"], files[0]["new_mode"]) == ("T", "100644", "120000")
    repo.story("@diff app.py#h1 app.py#h2")
    repo.build()
    text = repo.read("story.txt")
    assert "original" in text and "target.py" in text
    assert "file → symlink" in text
    assert "unchanged" not in text


def test_binary_requires_placement_and_records_file_anchor(repo):
    repo.commit({"asset.bin": b"old\x00blob"})
    repo.commit({"asset.bin": b"new\x00blob"})
    repo.index()
    assert repo.json("index.json")["files"][0]["binary"] is True
    repo.story("")
    assert "asset.bin" in repo.build(ok=False).stderr
    repo.story("@also asset.bin")
    repo.build()
    assert "file:asset.bin" in repo.json("anchors.json")["refs"]
    assert "binary file changed" in repo.read("story.html")


def test_no_newline_marker_survives_show_text_and_html(repo):
    repo.commit({"app.py": "value = 1"})
    repo.commit({"app.py": "value = 1\n"})
    repo.index()
    assert repo.run("show", repo.out, "app.py#h1").stdout.count("[no newline at end of file]") == 1
    repo.story("@diff app.py#h1")
    repo.build()
    text = repo.read("story.txt")
    assert text.count("[no newline]") == 1
    assert "[no newline]no newline" not in text
    assert 'class="nonl"' in repo.read("story.html")


@pytest.mark.parametrize("path", ['space name.py', 'quote"name.py', 'café.py', 'hash#name.py'])
def test_odd_paths_round_trip_through_diff_directives_and_html(repo, path):
    repo.commit({path: "value = 1\n"})
    head = repo.commit({path: "value = 2\n"})
    repo.git("remote", "add", "origin", "https://github.com/example/story.git")
    repo.git("update-ref", "refs/remotes/origin/main", head)
    repo.index()
    assert repo.json("index.json")["files"][0]["path"] == path
    repo.story(f"@diff {shlex.quote(path + '#h1')} id=odd\n@ctx {shlex.quote(path + '@head')} 1")
    repo.build()
    assert repo.frame("odd")["data-path"] == path
    assert json.loads(repo.frame("odd")["data-hunks"]) == [path + "#h1"]
    urls = [a[key] for a in repo.tags() for key in ("href", "data-blob") if key in a]
    assert any(f"/blob/{head}/{quote(path)}" in url for url in urls)
    assert "value = 2" in repo.read("story.txt")


def test_crlf_keeps_line_numbers_and_highlighting(repo):
    repo.commit({"app.py": b"value = 1\r\nnext_value = 2\r\n"})
    repo.commit({"app.py": b"value = 3\r\nnext_value = 2\r\n"})
    repo.index()
    repo.story("@diff app.py#h1\n@ctx app.py@head:2 id=context")
    repo.build()
    html = repo.read("story.html")
    assert 'class="n">next_value</span>' in html
    assert "\r" not in (repo.out / "story.html").read_bytes().decode()
    assert "L2–2" in repo.read("story.txt")
    assert "next_value = 2" in repo.read("story.txt")


def test_textconv_is_never_executed(repo):
    repo.commit({".gitattributes": "*.foo diff=convert\n", "app.foo": "before\n"})
    repo.commit({"app.foo": "after\n"})
    marker = repo.path.parent / "textconv-ran"
    converter = repo.path.parent / "convert.sh"
    converter.write_text(f"#!/bin/sh\ntouch {shlex.quote(str(marker))}\necho converted\n")
    converter.chmod(0o755)
    repo.git("config", "diff.convert.textconv", str(converter))
    repo.index()
    output = repo.run("show", repo.out, "app.foo", "app.foo@head").stdout
    assert "before" in output and "after" in output
    assert not marker.exists()


def test_suppress_blank_empty_cannot_renumber_rows(repo):
    repo.commit({"app.py": "a = 1\n\nb = 2\n\nc = 3\n"})
    repo.commit({"app.py": "a = 1\n\nb = 2\n\nc = 4\n"})
    repo.index()
    rows = repo.json("index.json")["files"][0]["hunks"][0]["rows"]
    repo.git("config", "diff.suppressBlankEmpty", "true")
    repo.index()
    assert repo.json("index.json")["files"][0]["hunks"][0]["rows"] == rows == 5


def test_diff_configuration_cannot_renumber_hunks(changed):
    repo = changed
    original = repo.json("index.json")["files"]
    for key, value in {
        "diff.suppressBlankEmpty": "true", "diff.relative": "true",
        "diff.algorithm": "histogram", "diff.interHunkContext": "100",
        "diff.noprefix": "true", "diff.renames": "false",
    }.items():
        repo.git("config", key, value)
    repo.index()
    assert repo.json("index.json")["files"] == original
    assert len(original[0]["hunks"]) == 2
