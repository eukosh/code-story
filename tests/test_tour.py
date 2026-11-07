import os

import pytest

from conftest import LINES

APP = {
    "app.py": "def main():\n    serve()\n\n\ndef serve():\n    pass\n",
    "src/handlers/users.py": "def get_user():\n    return 1\n",
    "src/handlers/orders.py": "x = 1\n",
    "src/db.py": LINES,
    "logo.png": b"\x89PNG\x00\x01\x02",
    "README.md": "# App\n",
}


def tour(repo, *args, ok=True):
    return repo.run("index", "--repo", repo.path, "--tour", "--out", repo.out, *args, ok=ok)


@pytest.fixture
def toured(repo):
    repo.commit(APP)
    tour(repo)
    return repo


def test_tour_pins_one_commit_without_a_diff(toured):
    index = toured.json("index.json")
    assert index["tour"] is True
    assert index["head"] == toured.git("rev-parse", "HEAD")
    assert index["merge_base"] is None and index["files"] == []


def test_tour_index_prints_the_layout(repo):
    repo.commit(APP)
    out = tour(repo).stdout
    assert "6 files\n" in out
    assert "src/  3 files\n  handlers/  2 files\n  db.py\n" in out


def test_one_tour_per_repo(repo):
    repo.commit(APP)
    out = repo.run("index", "--repo", repo.path, "--tour").stdout
    assert "/stories/local/repo/tour/" in out


@pytest.mark.parametrize("extra", [["--base", "HEAD"], ["--pr", "https://github.com/o/r/pull/1"]])
def test_tour_takes_no_base_or_pr(repo, extra):
    repo.commit(APP)
    assert "a tour shows the code at one commit" in tour(repo, *extra, ok=False).stderr


def test_tour_page_has_no_diff_chrome(toured):
    toured.story("@ctx app.py@head 1-2 id=entry")
    toured.build()
    body = toured.tags("body")[0]
    assert body["data-mode"] == "tour"
    assert body["data-story"] == "local/repo:tour"
    html = toured.read("story.html")
    assert 'class="chip">Unchanged' not in html
    assert "Code rendered from git at" in toured.read("story.txt")


def test_change_story_page_is_in_change_mode(changed):
    changed.story("@diff app.py#h1\n@diff app.py#h2\n@ctx src/context.py@head 1")
    changed.build()
    assert changed.tags("body")[0]["data-mode"] == "change"
    assert 'class="chip">Unchanged' in changed.read("story.html")


@pytest.mark.parametrize("line, message", [
    ("@diff app.py#h1", "a tour has no diff, so @diff has nothing to show"),
    ("@ripple app.py#h1 app.py#h2", "a tour has no diff, so @ripple has nothing to show"),
    ("@also app.py", "a tour has no diff, so @also has nothing to show"),
    ("@ctx app.py@base 1", "a tour has no base; show app.py@head"),
])
def test_tour_refuses_what_needs_a_diff(toured, line, message):
    toured.story(line)
    assert message in toured.build(ok=False).stderr


def test_tour_needs_no_coverage(toured):
    toured.story("@ctx app.py@head 1")
    toured.build()


def test_tree_lists_dirs_first_with_counts(toured):
    toured.story("@tree . depth=2 id=layout")
    toured.build()
    text = toured.read("story.txt")
    assert "[tree #layout] repo/ · 6 files" in text
    listing = text[text.index("[tree #layout]"):].splitlines()[1:9]
    assert listing == [
        "  src/  3 files",
        "    handlers/  2 files",
        "    db.py  30 lines",
        "  app.py  6 lines",
        "  logo.png  binary",
        "  README.md  1 line",
    ] + listing[6:]


def test_tree_of_a_subdirectory_at_depth_one(toured):
    toured.story("@tree src depth=1")
    toured.build()
    text = toured.read("story.txt")
    assert "src/ · 3 files" in text
    assert "  handlers/  2 files" in text and "users.py" not in text


def test_tree_marks_symlinks(repo):
    repo.commit(APP)
    os.symlink("app.py", repo.path / "link.py")
    repo.commit()
    tour(repo)
    repo.story("@tree . depth=1")
    repo.build()
    assert "  link.py  symlink" in repo.read("story.txt")


@pytest.mark.parametrize("line, message", [
    ("@tree app.py", "app.py is a file; @tree lists directories, @ctx shows files"),
    ("@tree nowhere", "nowhere doesn't exist at head"),
    ("@tree src depth=0", "@tree takes one directory and an optional depth=1-9"),
    ("@tree", "@tree takes one directory"),
])
def test_tree_errors(toured, line, message):
    toured.story(line)
    assert message in toured.build(ok=False).stderr


def test_tree_rows_carry_paths_for_links(toured):
    toured.story("@tree src depth=2\n\n@ctx src/db.py@head 1-2 id=db")
    toured.build()
    rows = toured.tags("div", "trow")
    assert [r["data-path"] for r in rows] == ["src/handlers", "src/handlers/orders.py", "src/handlers/users.py", "src/db.py"]
    assert toured.frame("db")["data-path"] == "src/db.py"


def test_tree_goes_stale_on_new_files_not_on_edits(repo):
    repo.commit(APP)
    tour(repo)
    repo.out.joinpath("story.md").write_text("# Tour\n\nLede.\n\n## Layout {#layout}\n\n@tree src depth=2\n")
    repo.build()
    repo.commit({"src/db.py": LINES + "extra = 1\n"})
    tour(repo)
    repo.build()
    repo.commit({"src/cache.py": "c = 1\n"})
    tour(repo)
    message = repo.build(ok=False).stderr
    assert "tree:src@head:2  (chapters: Layout)" in message
    repo.build("--accept")
    repo.build()


def test_tour_context_goes_stale_when_its_lines_change(repo):
    repo.commit(APP)
    tour(repo)
    repo.story("@ctx app.py@head 1-2")
    repo.build()
    repo.commit({"app.py": APP["app.py"].replace("serve()\n", "serve(port=80)\n", 1)})
    tour(repo)
    assert "app.py@head:1-2  (chapters: Flow)" in repo.build(ok=False).stderr


def test_tour_of_the_working_tree(repo):
    repo.commit(APP)
    repo.write({"notes.txt": "draft\n"})
    out = repo.path.parent / "wt-tour"
    repo.run("index", "--repo", repo.path, "--tour", "--head", "WORKTREE", "--out", out)
    (out / "story.md").write_text("# Tour\n\nLede.\n\n## Layout\n\n@tree . depth=1\n")
    repo.run("build", out)
    text = (out / "story.txt").read_text()
    assert "  notes.txt  1 line" in text
    assert "Code rendered from the working tree" in text


def test_tree_in_a_change_story(changed):
    changed.story("@diff app.py#h1\n@diff app.py#h2\n\n@tree src")
    changed.build()
    assert "  context.py  3 lines" in changed.read("story.txt")


def test_show_lists_a_directory(toured):
    out = toured.run("show", toured.out, "src@head").stdout
    assert out.startswith("src@head  3 files\n")
    assert "handlers/" in out and "db.py" in out and "30 lines" in out


def test_show_has_no_base_in_a_tour(toured):
    assert "a tour has no base; read app.py@head" in toured.run("show", toured.out, "app.py@base", ok=False).stderr


def test_tree_goes_stale_when_a_folded_dir_gains_a_file(repo):
    repo.commit(APP)
    tour(repo)
    repo.story("@tree . depth=1")
    repo.build()
    repo.commit({"src/handlers/admin.py": "a = 1\n"})
    tour(repo)
    assert "tree:.@head:1" in repo.build(ok=False).stderr


def test_working_tree_tour_reuses_the_one_tour(repo):
    repo.commit(APP)
    first = repo.run("index", "--repo", repo.path, "--tour").stdout
    second = repo.run("index", "--repo", repo.path, "--tour", "--head", "WORKTREE").stdout
    assert "/stories/local/repo/tour/" in first and "/stories/local/repo/tour/" in second


def test_working_tree_tour_needs_no_commit(repo):
    repo.write({"main.py": "print(1)\n"})
    out = repo.path.parent / "fresh"
    repo.run("index", "--repo", repo.path, "--tour", "--head", "WORKTREE", "--out", out)
    (out / "story.md").write_text("# Tour\n\nLede.\n\n## Start\n\n@ctx main.py@head 1\n")
    repo.run("build", out)


def test_hero_takes_a_sketch(toured):
    toured.out.joinpath("story.md").write_text(
        "# Tour\n\nWhat the app does.\n\n::: sketch The main flow\nrequest -> handler -> db\n:::\n\n## Start\n\n@ctx app.py@head 1\n"
    )
    toured.build()
    text = toured.read("story.txt")
    assert text.index("What the app does.") < text.index("[pseudo-code] The main flow") < text.index("## 1 Start")


def test_tree_counts_lines_of_any_filename(repo):
    repo.commit({**APP, "odd\nname.py": "a = 1\nb = 2\n"})
    tour(repo)
    repo.story("@tree . depth=1")
    repo.build()
    rows = {r["data-path"]: r["data-t"] for r in repo.tags("div", "trow")}
    assert rows["odd\nname.py"].endswith("2 lines")


def test_tour_of_an_empty_repo_points_at_the_working_tree(repo):
    assert "tour the working tree with --head WORKTREE" in tour(repo, ok=False).stderr


def test_tree_shows_big_files_by_size(repo):
    repo.commit({**APP, "data.csv": "x\n" * 1_500_000})
    tour(repo)
    repo.story("@tree . depth=1")
    repo.build()
    assert "  data.csv  3 MB" in repo.read("story.txt")


@pytest.mark.parametrize("spelling", ["./src", "src/", "src/handlers/.."])
def test_tree_paths_have_one_spelling(toured, spelling):
    toured.story(f"@tree {spelling} depth=1\n\n@ctx src/db.py@head 1")
    toured.build()
    assert toured.tags("figure", "tree")[0]["data-path"] == "src"
    assert {r["data-path"] for r in toured.tags("div", "trow")} == {"src/handlers", "src/db.py"}
    assert "tree:src@head:1" in toured.json("anchors.json")["refs"]


def test_show_lists_the_root(toured):
    assert toured.run("show", toured.out, ".@head").stdout.startswith(".@head  6 files\n")


def test_submodules_are_named_as_such(repo):
    sha = repo.commit(APP)
    repo.git("update-index", "--add", "--cacheinfo", f"160000,{sha},vendor/sub")
    repo.git("commit", "--quiet", "-m", "sub")
    tour(repo)
    repo.story("@tree vendor/sub")
    assert "vendor/sub is a submodule at head" in repo.build(ok=False).stderr
    assert "vendor/sub is a submodule at head" in repo.run("show", repo.out, "vendor/sub@head", ok=False).stderr


def test_tour_warns_that_exclusions_do_nothing(toured):
    toured.story("@ctx app.py@head 1", front='exclude:\n  - path: "*.md"\n    reason: docs')
    assert "a tour has no coverage, so exclude and include do nothing" in toured.build().stdout


def test_show_hints_at_head_in_a_tour(toured):
    message = toured.run("show", toured.out, "app.py", ok=False).stderr
    assert "in a tour, read a file as app.py@head" in message


def test_tour_at_an_older_ref_reads_that_commit(repo):
    first = repo.commit(APP)
    repo.commit({"app.py": "def main():\n    start()\n"})
    tour(repo, "--head", first)
    repo.story("@ctx app.py@head 2")
    repo.build()
    assert "serve()" in repo.read("story.txt") and "start()" not in repo.read("story.txt")
    tour(repo)
    assert "app.py@head:2-2  (chapters: Flow)" in repo.build(ok=False).stderr
