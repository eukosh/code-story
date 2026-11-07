import pytest

from conftest import LINES


def test_missing_hunk_is_a_coverage_gap(changed):
    changed.story("@diff app.py#h1")
    message = changed.build(ok=False).stderr
    assert "coverage: these changes aren't in the story" in message
    assert "app.py#h2  2 changed lines not shown (L25, R25)" in message
    assert not (changed.out / "anchors.json").exists()


@pytest.mark.parametrize(("before", "after"), [
    ("\n", "\n\n"),
    ("value = 1\n", "value = 1  \t\n"),
    ("import os\n", "import os\nimport sys\n"),
    ("import os\nimport sys\n", "import os\n"),
    ("import os\nimport sys\n", "import sys\nimport os\n"),
], ids=["blank", "trailing-whitespace", "import-add", "import-drop", "import-reorder"])
def test_mechanical_hunk_auto_covers_only_after_file_is_referenced(repo, before, after):
    repo.commit({"app.py": before + LINES})
    repo.commit({"app.py": after + LINES.replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    assert len(repo.json("index.json")["files"][0]["hunks"]) == 2
    repo.story("")
    assert "app.py#h1" in repo.build(ok=False).stderr
    repo.story("@diff app.py#h2")
    repo.build()
    assert "app.py#h2" in repo.json("anchors.json")["refs"]


@pytest.mark.parametrize(("before", "after"), [
    ("from auth import token\n", "from auth_v2 import token\n"),
    ("if ready:\n    import os\n", "if ready:\nimport os\n"),
    ("import os\n", "import os; allowed = True\n"),
    ("if ready:\n    run()\n", "if ready:\nrun()\n"),
    ('name = "a b"\n', 'name = "ab"\n'),
    ("left()\nright()\n", "right()\nleft()\n"),
], ids=["edited-import", "dedented-import", "import-with-statement", "dedented-code", "string-space", "reordered-code"])
def test_semantic_changes_are_not_auto_covered(repo, before, after):
    repo.commit({"app.py": before + LINES})
    repo.commit({"app.py": after + LINES.replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    repo.story("@diff app.py#h2")
    assert "app.py#h1" in repo.build(ok=False).stderr


@pytest.mark.parametrize("path", ["guide.md", "guide.mdx", "guide.rst", "guide.adoc"])
def test_docs_are_covered_as_a_whole(repo, path):
    repo.commit({path: LINES})
    repo.commit({path: LINES.replace("value_2 = 2", "value_2 = 200").replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    repo.story(f"@diff {path}#h1")
    repo.build()
    assert f"file:{path}" in repo.json("anchors.json")["refs"]


@pytest.mark.parametrize("path", ["CMakeLists.txt", "requirements.txt"])
def test_txt_code_files_need_every_hunk(repo, path):
    repo.commit({path: LINES})
    repo.commit({path: LINES.replace("value_2 = 2", "value_2 = 200").replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    repo.story(f"@diff {path}#h1")
    assert f"{path}#h2" in repo.build(ok=False).stderr


@pytest.mark.parametrize("deleted", [False, True])
def test_added_and_deleted_files_are_covered_as_a_whole(repo, deleted):
    repo.commit({"app.py": LINES} if deleted else {"keep.py": "keep\n"})
    repo.commit({"app.py": None if deleted else LINES})
    repo.index()
    repo.story("@diff app.py#h1 rows=1-1")
    repo.build()
    assert "file:app.py" in repo.json("anchors.json")["refs"]


def test_excluded_files_have_no_anchors_or_story_back_links(repo):
    repo.commit({"app.py": "old\n", "tests/test_app.py": "hidden_old\n"})
    repo.commit({"app.py": "new\n", "tests/test_app.py": "hidden_new\n"})
    repo.index()
    repo.story("@diff app.py#h1")
    repo.build()
    assert set(repo.json("anchors.json")["refs"]) == {"app.py#h1"}
    assert len(repo.tags("button", "fd-back")) == 1
    assert "[collapsed on the page] tests/test_app.py" in repo.read("story.txt")
    assert "hidden_new" not in repo.read("story.txt")
    repo.commit({"tests/test_app.py": "hidden_later\n"})
    repo.index()
    repo.build()
    assert set(repo.json("anchors.json")["refs"]) == {"app.py#h1"}


def test_include_restores_default_excluded_file_to_coverage(repo):
    repo.commit({"tests/test_app.py": "old\n"})
    repo.commit({"tests/test_app.py": "new\n"})
    repo.index()
    repo.story("", front="include: [tests/test_app.py]")
    assert "tests/test_app.py#h1" in repo.build(ok=False).stderr
    repo.story("@also tests/test_app.py", front="include: [tests/test_app.py]")
    repo.build()
    assert "file:tests/test_app.py" in repo.json("anchors.json")["refs"]


def test_explicit_exclusion_renders_reason_and_needs_no_placement(changed):
    changed.story("", front="exclude:\n  - path: app.py\n    reason: Demonstrated elsewhere")
    changed.build()
    assert "Demonstrated elsewhere" in changed.read("story.txt")
    assert changed.json("anchors.json")["refs"] == {}
