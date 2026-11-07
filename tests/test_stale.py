import pytest

from conftest import LINES


def test_changed_hunk_names_every_chapter_and_accept_is_explicit(changed):
    repo = changed
    repo.story("@diff app.py#h1\n@diff app.py#h2\n\n## Second {#second}\n@diff app.py#h1")
    repo.build()
    old_anchors = repo.read("anchors.json")
    old_html = repo.read("story.html")
    repo.commit({"app.py": (repo.path / "app.py").read_text().replace("value_2 = 200", "value_2 = 201")})
    repo.index()
    message = repo.build(ok=False).stderr
    assert "code under these anchors changed" in message
    assert "app.py#h1  (chapters: Flow, Second)" in message
    assert "check ok" in repo.run("check", repo.out, "--accept").stdout
    assert repo.read("anchors.json") == old_anchors
    assert repo.read("story.html") == old_html
    repo.run("check", repo.out, ok=False)
    repo.build("--accept")
    assert repo.read("anchors.json") != old_anchors
    assert "check ok" in repo.run("check", repo.out).stdout


def test_base_movement_invalidates_context_even_with_same_head(repo):
    base = repo.commit({"app.py": "original\n", "context.py": "before\n"})
    moved_base = repo.commit({"context.py": "after\n"})
    head = repo.commit({"app.py": "changed\n"})
    repo.index(base=base)
    repo.story("@also app.py\n@also context.py\n@ctx context.py@base 1")
    repo.build()
    repo.index(base=moved_base)
    repo.story("@also app.py\n@ctx context.py@base 1")
    assert repo.json("index.json")["head"] == head
    assert "context.py@base:1-1  (chapters: Flow)" in repo.build(ok=False).stderr


def test_also_becomes_stale_when_file_gains_a_hunk(repo):
    repo.commit({"app.py": LINES})
    repo.commit({"app.py": LINES.replace("value_2 = 2", "value_2 = 200")})
    repo.index()
    repo.story("@also app.py")
    repo.build()
    repo.commit({"app.py": (repo.path / "app.py").read_text().replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    assert len(repo.json("index.json")["files"][0]["hunks"]) == 2
    assert "file:app.py  (chapters: Flow)" in repo.build(ok=False).stderr


def test_also_becomes_stale_on_mode_change(changed):
    changed.story("@also app.py")
    changed.build()
    (changed.path / "app.py").chmod(0o755)
    changed.commit()
    changed.index()
    assert "file:app.py  (chapters: Flow)" in changed.build(ok=False).stderr


def test_no_newline_only_change_invalidates_anchor(repo):
    repo.commit({"app.py": "before\n"})
    repo.commit({"app.py": "after"})
    repo.index()
    repo.story("@diff app.py#h1")
    repo.build()
    old = repo.json("anchors.json")["refs"]["app.py#h1"]
    repo.commit({"app.py": "after\n"})
    repo.index()
    assert "app.py#h1  (chapters: Flow)" in repo.build(ok=False).stderr
    repo.build("--accept")
    assert repo.json("anchors.json")["refs"]["app.py#h1"] != old


def test_literal_backslash_does_not_collide_with_no_newline_marker(repo):
    repo.commit({"app.py": "before\n"})
    repo.commit({"app.py": "after"})
    repo.index()
    repo.story("@diff app.py#h1")
    repo.build()
    old = repo.frame("_f1")["data-hash"]
    repo.commit({"app.py": "after\\\n"})
    repo.index()
    assert "code under these anchors changed" in repo.build(ok=False).stderr
    repo.build("--accept")
    assert repo.frame("_f1")["data-hash"] != old


def test_stale_file_and_hunk_dedupe_keeps_all_chapters(changed):
    repo = changed
    repo.story("@diff app.py#h1\n\n## Repeated {#repeated}\n@diff app.py#h1\n\n## Appendix {#appendix}\n@also app.py")
    repo.build()
    repo.commit({"app.py": (repo.path / "app.py").read_text().replace("value_2 = 200", "value_2 = 201")})
    repo.index()
    message = repo.build(ok=False).stderr
    stale_lines = [line for line in message.splitlines() if "(chapters:" in line]
    assert len(stale_lines) == 1
    assert "file:app.py" in stale_lines[0]
    for chapter in ("Flow", "Repeated", "Appendix"):
        assert chapter in stale_lines[0]


@pytest.mark.parametrize("body", [
    "---\nmap: [\n---\n",
    "---\ntitle: Never closed\n",
    "---\n- invalid-root\n---\n",
    "---\ntraces: {token: 42}\n---\n",
    "---\nmap: label\n---\n",
    "---\nexclude: [{path: app.py}]\n---\n",
    "# Story\n## Flow\n@diff nonexistent#h1\n",
    "# Story\n## Flow\nNo coverage.\n",
], ids=["yaml", "unclosed-front", "front-shape", "traces-shape", "map-shape", "missing-reason", "unknown-hunk", "coverage"])
@pytest.mark.parametrize("command", ["build", "check"])
def test_accept_failure_always_explains_retry(changed, body, command):
    (changed.out / "story.md").write_text(body)
    message = changed.run(command, changed.out, "--accept", ok=False).stderr
    assert "--accept applies to a build that succeeds; pass it again" in message
    assert not (changed.out / "anchors.json").exists()


def test_failed_accept_keeps_previous_anchors(changed):
    changed.story("@also app.py")
    changed.build()
    original = changed.read("anchors.json")
    changed.commit({"app.py": (changed.path / "app.py").read_text().replace("value_2 = 200", "value_2 = 201")})
    changed.index()
    changed.story("@diff app.py#h1")
    assert "pass it again" in changed.build("--accept", ok=False).stderr
    assert changed.read("anchors.json") == original
    changed.story("@also app.py")
    assert "code under these anchors changed" in changed.build(ok=False).stderr


def test_accept_note_also_covers_load_failure(changed):
    (changed.out / "index.json").unlink()
    assert "pass it again" in changed.build("--accept", ok=False).stderr
