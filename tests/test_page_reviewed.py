"""Reviewed marks in the page: a snippet's path, hash and place among its twins, kept per change (D44)."""
import json

import pytest

from conftest import LINES
from test_reviewed import BLOCK, two_hunks

KEY = "`code-story:reviewed:${document.body.dataset.marks}`"


def state(page, fid):
    f = page.locator(f"#{fid}")
    cls = f.get_attribute("class").split()
    chip = f.locator(".fh .chip.chg")
    return {
        "state": "reviewed" if "reviewed" in cls else "changed" if "changed" in cls else "new",
        "label": chip.inner_text() if chip.count() and chip.is_visible() else None,
        "folded": "collapsed" in cls,
        "bars": [t.replace("\xa0", " ") for t in f.locator(".code.u .row.unseen code").all_inner_texts()],
    }


def new(folded=False):
    return {"state": "new", "label": None, "folded": folded, "bars": []}


def reviewed():
    return {"state": "reviewed", "label": None, "folded": True, "bars": []}


def changed(*bars):
    return {"state": "changed", "label": "Changed since review", "folded": False, "bars": list(bars)}


def mark(page, fid):
    page.locator(f'#{fid} .fh [data-act="reviewed"]').click()


def marks(page):
    return page.evaluate(f"JSON.parse(localStorage.getItem({KEY}) || '{{}}')")


def today(page):
    return page.evaluate("Math.floor(Date.now() / 864e5)")


def rebuild(repo, files, story=None):
    repo.commit(files)
    repo.index()
    if story:
        repo.story(story)
    repo.build("--accept")


@pytest.fixture
def writes(context):
    """Counts the page's writes to the marks store, from before its script runs."""
    context.add_init_script("""(() => {
        const set = Storage.prototype.setItem;
        window.__writes = 0;
        Storage.prototype.setItem = function (k, v) {
            if (String(k).startsWith("code-story:reviewed:")) window.__writes++;
            return set.call(this, k, v);
        };
    })()""")
    return lambda page: page.evaluate("window.__writes")


def twins(repo, both=True):
    """job.py with two methods of one class whose bodies are the same, and the same edit in one or both."""
    body = "".join(f"        step_{n}()\n" for n in range(1, 10))
    base = "class Job:\n    def daily(self):\n" + body + "\n    def hourly(self):\n" + body
    repo.commit({"job.py": base})
    repo.commit({"job.py": base.replace("step_5()\n", "step_5()\n        extra()\n", 2 if both else 1)})
    repo.index()
    return base


def other_branch(repo, tmp_path, name, base, files):
    """A second branch off `base` with its own story, as another PR of the same repo would be."""
    repo.git("checkout", "-q", "-B", name, base)
    repo.commit(files)
    repo.out = tmp_path / name
    repo.index(head=name, base=base)


# ---- what stays reviewed ----


def test_marks_survive_a_rebuild_after_an_unrelated_commit(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    assert state(page, "one") == reviewed()
    repo.commit({"other.py": "x = 1\n"})
    repo.index()
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two\n@also other.py")
    repo.build()
    story_page(repo, page)
    assert state(page, "one") == reviewed()
    assert state(page, "two") == new()
    assert page.locator(".progress .p-txt").inner_text() == "1/2 reviewed"
    assert page.locator(".progress .p-chg").is_hidden()


def test_reordered_snippets_stay_reviewed(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    repo.story("@diff app.py#h2 id=two\n@diff app.py#h1 id=one")
    repo.build()
    story_page(repo, page)
    assert state(page, "one") == reviewed()
    assert state(page, "two") == new()


def test_renumbered_hunks_keep_their_marks(repo, story_page):
    new_text = two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    mark(page, "two")
    rebuild(repo, {"app.py": new_text.replace("value_15 = 15", "value_15 = 150")},
            "@diff app.py#h1 id=one\n@diff app.py#h2 id=mid\n@diff app.py#h3 id=two")
    story_page(repo, page)
    assert state(page, "two") == reviewed()
    assert state(page, "mid") == new()


def test_one_hunk_in_two_chapters_is_marked_in_both(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=first\n@diff app.py#h2\n\n## Again {#later}\n\n@diff app.py#h1 id=again")
    repo.build()
    page = story_page(repo)
    mark(page, "first")
    assert state(page, "first") == state(page, "again") == reviewed()
    mark(page, "again")
    assert state(page, "first") == state(page, "again") == new()


def test_a_branch_and_its_working_tree_share_marks(repo, tmp_path, story_page):
    base = repo.commit({"app.py": LINES})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit({"app.py": LINES.replace("value_9 = 9", "value_9 = 90")})
    repo.index(head="feature", base=base)
    repo.story("@diff app.py#h1 id=one")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    repo.out = tmp_path / "tree"
    repo.index(head="WORKTREE", base=base)
    repo.story("@diff app.py#h1 id=late")
    repo.build()
    assert state(story_page(repo), "late") == reviewed()


def test_l4_marks_survive_the_base_editing_the_line_git_heads_the_hunk_with(repo, story_page):
    body = "".join(f"        step_{n}()\n" for n in range(1, 12))
    base = "class Job(Base):\n    def run(self):\n" + body
    main = repo.commit({"job.py": base})
    repo.git("checkout", "-q", "-b", "feat")
    repo.commit({"job.py": base.replace("step_6()", "step_6(fast=True)")})
    repo.index(head="feat", base=main)
    repo.story("@diff job.py#h1 id=one")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    repo.git("checkout", "-q", "main")
    main2 = repo.commit({"job.py": base.replace("class Job(Base):", "class Job(Base, Mixin):")})
    repo.git("checkout", "-q", "feat")
    repo.git("rebase", "-q", "main")
    repo.index(head="feat", base=main2)
    repo.build("--accept")
    story_page(repo, page)
    assert "Mixin" in page.locator("#one .fh").inner_text()
    assert state(page, "one") == reviewed()


# ---- twins: the same rows at two places ----


def test_a3_marking_one_of_two_twins_marks_only_that_one(repo, story_page):
    twins(repo)
    repo.story("@diff job.py#h1 id=daily\n@diff job.py#h2 id=hourly")
    repo.build()
    page = story_page(repo)
    assert repo.frame("daily")["data-hash"] == repo.frame("hourly")["data-hash"]
    mark(page, "daily")
    assert state(page, "daily") == reviewed()
    assert state(page, "hourly") == new()
    mark(page, "hourly")
    assert state(page, "daily") == state(page, "hourly") == reviewed()
    assert [x[2:4] for x in marks(page)["job.py"]] == [[1, 2], [2, 2]]
    story_page(repo, page)
    assert state(page, "daily") == state(page, "hourly") == reviewed()
    mark(page, "hourly")
    assert state(page, "daily") == reviewed() and state(page, "hourly") == new()


def test_twins_are_counted_in_file_order_and_one_hunk_shown_twice_is_one_of_them(repo, story_page):
    twins(repo)
    repo.story("@diff job.py#h2 id=hourly\n@diff job.py#h1 id=daily\n\n## Again {#later}\n\n@diff job.py#h2 id=again")
    repo.build()
    page = story_page(repo)
    mark(page, "hourly")
    assert state(page, "hourly") == state(page, "again") == reviewed() and state(page, "daily") == new()
    assert [x[2:4] for x in marks(page)["job.py"]] == [[2, 2]]
    repo.story("@diff job.py#h1 id=daily\n@diff job.py#h2 id=hourly")
    repo.build()
    story_page(repo, page)
    assert state(page, "hourly") == reviewed() and state(page, "daily") == new()


def test_a_twin_that_appears_later_voids_the_mark(repo, story_page):
    base = twins(repo, both=False)
    repo.story("@diff job.py#h1 id=daily")
    repo.build()
    page = story_page(repo)
    mark(page, "daily")
    rebuild(repo, {"job.py": base.replace("step_5()\n", "step_5()\n        extra()\n")},
            "@diff job.py#h1 id=daily\n@diff job.py#h2 id=hourly")
    story_page(repo, page)
    assert state(page, "daily") == state(page, "hourly") == new()
    assert page.locator(".progress .p-chg").is_hidden()
    mark(page, "daily")
    assert state(page, "daily") == reviewed() and state(page, "hourly") == new()
    assert [x[2:4] for x in marks(page)["job.py"]] == [[1, 2]]  # the void mark of the same rows went


def test_a1_a_look_alike_job_in_the_same_file_is_not_reviewed(repo, story_page):
    job = ("    runs-on: ubuntu-latest\n    steps:\n      - uses: actions/checkout@v4\n      - uses: actions/setup-python@v5\n"
           "        with:\n          python-version: \"3.11\"\n      - run: pip install -r requirements.txt\n      - run: make check\n")
    base = "name: ci\non: push\njobs:\n  lint:\n" + job + "  test:\n" + job
    repo.commit({".github/workflows/ci.yml": base})
    repo.commit({".github/workflows/ci.yml": base.replace('"3.11"', '"3.12"')})
    repo.index()
    repo.story("@diff .github/workflows/ci.yml#h1 id=lint\n@diff .github/workflows/ci.yml#h2 id=test")
    repo.build()
    page = story_page(repo)
    mark(page, "lint")
    assert state(page, "test") == new()


def test_l1_a_slice_that_occurs_in_another_function_is_not_reviewed(repo, story_page):
    body = "    a = load()\n    b = parse(a)\n    c = check(b)\n    d = send(c)\n    e = log(d)\n    f = done(e)\n    return f\n"
    base = "def one():\n" + body + "\n\ndef two():\n" + body
    repo.commit({"app.py": base})
    repo.commit({"app.py": base.replace("    c = check(b)\n", "    c = check(b, strict=True)\n")})
    repo.index()
    repo.story("@diff app.py#h1 rows=3-6 id=slice\n@diff app.py#h1 rows=1-2 id=rest1\n@diff app.py#h1 rows=7-8 id=rest2\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    mark(page, "slice")
    assert state(page, "slice") == reviewed()
    assert state(page, "two") == state(page, "rest1") == state(page, "rest2") == new()


def test_s2_the_same_line_added_above_reviewed_code_takes_nothing_from_it(repo, story_page):
    filler = "".join(f"# note {n}\n" for n in range(12))
    base = "[cache]\nttl = 60\n\n" + filler + "[auth]\nttl = 60\n\n" + filler
    v1 = base.replace("[auth]\nttl = 60\n", "[auth]\nttl = 60\nretries = 0\n")
    repo.commit({"cfg.ini": base})
    repo.commit({"cfg.ini": v1})
    repo.index()
    repo.story("@diff cfg.ini#h1 id=auth")
    repo.build()
    page = story_page(repo)
    mark(page, "auth")
    rebuild(repo, {"cfg.ini": v1.replace("[cache]\nttl = 60\n", "[cache]\nttl = 60\nretries = 0\n")},
            "@diff cfg.ini#h1 id=cache\n@diff cfg.ini#h2 id=auth")
    story_page(repo, page)
    assert state(page, "auth") == reviewed()
    assert state(page, "cache") == new()


# ---- another change: its marks have no effect ----


def test_a2_a3b_another_pr_of_the_repo_takes_nothing_from_these_marks(repo, tmp_path, story_page):
    body = "".join(f"        step_{n}()\n" for n in range(1, 10))
    base = "class Job:\n    def daily(self):\n" + body + "\n    def hourly(self):\n" + body
    main = repo.commit({"job.py": base})
    edit = lambda s, at: s[:at] + "step_5()\n        extra()\n" + s[at + len("step_5()\n"):]
    other_branch(repo, tmp_path, "one", main, {"job.py": edit(base, base.index("step_5()\n"))})
    repo.story("@diff job.py#h1 id=a")
    repo.build()
    page = story_page(repo)
    mark(page, "a")
    other_branch(repo, tmp_path, "two", main, {"job.py": edit(base, base.rindex("step_5()\n"))})
    repo.story("@diff job.py#h1 id=b")
    repo.build()
    other = story_page(repo)
    assert state(other, "b") == new()
    assert marks(other) == {}
    assert other.locator(".progress .p-chg").is_hidden()


# ---- what changed since review ----


def test_an_edited_line_is_changed_since_review(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    mark(page, "two")
    rebuild(repo, {"app.py": (repo.path / "app.py").read_text().replace("step_4 = 4", "step_4 = 44")})
    story_page(repo, page)
    assert state(page, "one") == changed("step_4 = 44")
    assert state(page, "two") == reviewed()
    assert page.locator(".progress .p-txt").inner_text() == "1/2 reviewed"
    assert page.locator(".progress .p-chg").inner_text() == "1 to revisit"
    assert page.locator(".map li.changed").count() == 1

    page.locator(".progress .p-chg").click()
    assert page.locator(".toast").inner_text() == "Changed since review: snippet 1 of 1"
    page.locator('.seg [data-view="split"]').click()
    assert page.locator("#one .half.unseen").count() == 1
    mark(page, "one")
    assert state(page, "one") == reviewed()
    assert page.locator(".progress .p-chg").is_hidden()
    assert len(marks(page)["app.py"]) == 2  # the changed mark went with the new one


def test_a_removed_line_bars_the_lines_either_side(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    rebuild(repo, {"app.py": (repo.path / "app.py").read_text().replace("step_4 = 4\n", "")})
    story_page(repo, page)
    assert state(page, "one") == changed("step_3 = 3", "step_5 = 5")


def test_collision_a_snippet_with_the_same_32_bit_hash_is_changed(repo, story_page):
    """The nonce was found in 17 seconds on a laptop: the snippet's hash starts like the reviewed one's."""
    base = "def handle(req):\n    log(req)\n    check(req)\n    return run(req)\n"
    repo.commit({"app.py": base})
    repo.commit({"app.py": base.replace("    check(req)\n", "    verify_token(req)\n")})
    repo.index()
    repo.story("@diff app.py#h1 id=auth")
    repo.build()
    before = repo.frame("auth")["data-hash"]
    page = story_page(repo)
    mark(page, "auth")
    rebuild(repo, {"app.py": base.replace("    check(req)\n", "    skip_verify(req)  # 00003833f3cc\n")})
    after = repo.frame("auth")["data-hash"]
    assert before[:8] == after[:8] and before != after
    story_page(repo, page)
    assert state(page, "auth") == changed("    skip_verify(req)  # 00003833f3cc")


def test_l2_a_line_added_at_the_end_of_a_reviewed_hunk_is_changed(repo, story_page):
    base = "".join(f"v{n} = {n}\n" for n in range(30))
    repo.commit({"a.py": base})
    repo.commit({"a.py": base.replace("v10 = 10\n", "v10 = 100\n")})
    repo.index()
    repo.story("@diff a.py#h1 id=one")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    rebuild(repo, {"a.py": base.replace("v10 = 10\n", "v10 = 100\n").replace("v13 = 13\n", "v13 = 13\nrm_all()\n")})
    story_page(repo, page)
    assert state(page, "one") == changed("rm_all()", "v14 = 14", "v15 = 15", "v16 = 16")
    assert page.locator("#one .fh .chip.chg").get_attribute("title") == (
        "The code changed after you marked it reviewed. Bars mark the lines that differ from what you marked, "
        "and the lines either side of one that was removed"
    )
    # the rows the reader marked, shown alone, are the same snippet again
    repo.story("@diff a.py#h1 rows=1-8 id=seen\n@diff a.py#h1 rows=9-12 id=added")
    repo.build()
    story_page(repo, page)
    assert state(page, "seen") == reviewed()
    assert state(page, "added") == new()


def test_a_line_added_just_above_a_reviewed_hunk_is_changed(repo, story_page):
    base = "".join(f"v{n} = {n}\n" for n in range(30))
    repo.commit({"a.py": base})
    repo.commit({"a.py": base.replace("v10 = 10\n", "v10 = 100\n")})
    repo.index()
    repo.story("@diff a.py#h1 id=one")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    rebuild(repo, {"a.py": base.replace("v10 = 10\n", "v10 = 100\n").replace("v6 = 6\n", "v6 = 6\nrm_all()\n")})
    story_page(repo, page)
    assert state(page, "one") == changed("v4 = 4", "v5 = 5", "v6 = 6", "rm_all()")


def test_s1_a_removal_taken_back_is_changed(repo, story_page):
    """Replacing verify_token with verify_token_v2 was reviewed; now the old call stays and the new one is added."""
    base = "def handle(req):\n    log(req)\n    verify_token(req)\n    return run(req)\n"
    repo.commit({"app.py": base})
    repo.commit({"app.py": base.replace("    verify_token(req)\n", "    verify_token_v2(req)\n")})
    repo.index()
    repo.story("@diff app.py#h1 id=auth")
    repo.build()
    page = story_page(repo)
    mark(page, "auth")
    rebuild(repo, {"app.py": base.replace("    verify_token(req)\n", "    verify_token(req)\n    verify_token_v2(req)\n")})
    story_page(repo, page)
    assert state(page, "auth") == changed("    verify_token(req)")


def test_an_edit_that_moves_the_hunks_start_is_still_changed(repo, story_page):
    """Taking the removal back moves the hunk's first row below `def`: the rows past that end are only not shown."""
    base = "def handle(req):\n    log(req)\n    user = load_user(req)\n    verify_token(req)\n    audit(user)\n    return run(req, user)\n"
    repo.commit({"app.py": base})
    repo.commit({"app.py": base.replace("    verify_token(req)\n", "    verify_token_v2(req)\n")})
    repo.index()
    repo.story("@diff app.py#h1 id=auth")
    repo.build()
    page = story_page(repo)
    mark(page, "auth")
    rebuild(repo, {"app.py": base.replace("    verify_token(req)\n", "    verify_token(req)\n    verify_token_v2(req)\n")})
    story_page(repo, page)
    assert state(page, "auth") == changed("    verify_token(req)")


def test_s3_a_newline_added_at_the_end_of_the_file(repo, story_page):
    head = "".join(f"v{n} = {n}\n" for n in range(5))
    repo.commit({"a.py": head, "b.py": "x = 1\n"})
    repo.commit({"a.py": head + "y = 2", "b.py": "x = 1\ny = 2"})
    repo.index()
    repo.story("@diff a.py#h1 id=long\n@diff b.py#h1 id=short")
    repo.build()
    page = story_page(repo)
    mark(page, "long")
    mark(page, "short")
    rebuild(repo, {"a.py": head + "y = 2\n", "b.py": "x = 1\ny = 2\n"})
    story_page(repo, page)
    assert state(page, "long") == state(page, "short") == changed("y = 2")


def test_changed_code_goes_to_one_snippet_only(repo, story_page):
    """Both twins edited again after one was marked: the first that shares the most rows takes the hint."""
    base = twins(repo)
    repo.story("@diff job.py#h1 id=daily\n@diff job.py#h2 id=hourly")
    repo.build()
    page = story_page(repo)
    mark(page, "daily")
    rebuild(repo, {"job.py": base.replace("step_5()\n", "step_5()\n        extra(1)\n")})
    story_page(repo, page)
    assert state(page, "daily") == changed("        extra(1)")
    assert state(page, "hourly") == new()


def test_changed_code_goes_to_a_snippet_of_its_own_file(repo, story_page):
    repo.commit({"a.py": LINES, "b.py": LINES})
    repo.commit({"a.py": LINES.replace("value_9 = 9", "value_9 = 90"), "b.py": LINES.replace("value_9 = 9", "value_9 = 90")})
    repo.index()
    repo.story("@diff a.py#h1 id=a\n@diff b.py#h1 id=b")
    repo.build()
    page = story_page(repo)
    mark(page, "a")
    rebuild(repo, {"a.py": LINES.replace("value_9 = 9", "value_9 = 91")})
    story_page(repo, page)
    assert state(page, "a") == changed("value_9 = 91")
    assert state(page, "b") == new()


def test_changed_code_never_goes_to_a_reviewed_snippet(repo, story_page):
    body = "    a = load()\n    b = parse(a)\n    c = check(b)\n    d = send(c)\n    e = log(d)\n    f = done(e)\n    return f\n"
    base = "def one():\n" + body + "\n\ndef two():\n" + body
    edited = base.replace("    c = check(b)\n", "    c = check(b, strict=True)\n")
    repo.commit({"app.py": base})
    repo.commit({"app.py": edited})
    repo.index()
    repo.story("@diff app.py#h2 id=two\n@diff app.py#h1 rows=2-8 id=one")
    repo.build()
    page = story_page(repo)
    mark(page, "two")
    mark(page, "one")
    rebuild(repo, {"app.py": edited.replace("strict=True", "strict=False", 1)})
    story_page(repo, page)
    assert state(page, "two") == reviewed()
    assert state(page, "one") == changed("    c = check(b, strict=False)")


def test_a_rewrite_is_unreviewed(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    rebuild(repo, {"app.py": (repo.path / "app.py").read_text().replace(BLOCK, "".join(f"other_{n} = {n}\n" for n in range(9)))})
    story_page(repo, page)
    assert state(page, "one") == new()


def test_row_hashes_alone_never_make_a_snippet_reviewed(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    page.evaluate(f"""(() => {{
        const m = JSON.parse(localStorage.getItem({KEY}));
        m["app.py"][0][1] = "0".repeat(20);
        localStorage.setItem({KEY}, JSON.stringify(m));
    }})()""")
    story_page(repo, page)
    assert state(page, "one") == new()


def test_the_same_lines_in_another_order_are_unreviewed(repo, story_page):
    """They share every row with the snapshot, but in order only two of eight: less than half, so not the code it was."""
    lines = "".join(f"step_{n}()\n" for n in range(1, 9))
    repo.commit({"old.py": "x = 1\n"})
    repo.commit({"new.py": lines})
    repo.index()
    repo.story("@diff new.py#h1 id=one")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    first, *rest = lines.splitlines(True)
    rebuild(repo, {"new.py": first + "".join(reversed(rest))})
    story_page(repo, page)
    assert state(page, "one") == new()


# ---- the same code cut into other snippets: unreviewed, and nothing changed ----


def test_a_slice_of_a_marked_snippet_is_unreviewed_with_no_chip(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    mark(page, "one")
    repo.story("@diff app.py#h1 rows=6-14 id=late\n@diff app.py#h2 id=two\n@diff app.py#h1 rows=1-5 id=early")
    repo.build()
    story_page(repo, page)
    assert state(page, "late") == state(page, "early") == state(page, "two") == new()
    assert page.locator(".progress .p-chg").is_hidden()


def test_slices_or_hunks_marked_apart_and_shown_as_one_are_unreviewed_with_no_chip(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 rows=1-5 id=top\n@diff app.py#h1 rows=6-14 id=rest\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    for fid in ("top", "rest", "two"):
        mark(page, fid)
    repo.story("@diff app.py#h1 id=whole\n@diff app.py#h2 id=two")
    repo.build()
    story_page(repo, page)
    assert state(page, "whole") == new()
    assert state(page, "two") == reviewed()
    repo.story("@diff app.py#h1 app.py#h2 id=both")
    repo.build()
    story_page(repo, page)
    assert state(page, "both") == new()


# ---- the store ----


def test_legacy_marks_carry_over(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    legacy = page.evaluate("[`${one.dataset.path}:${one.dataset.hash.slice(0, 8)}`, 'gone.py:12345678']")
    page.evaluate(f"localStorage.setItem(`${{document.body.dataset.story}}:reviewed`, {json.dumps(json.dumps(legacy))})")
    story_page(repo, page)
    assert state(page, "one") == reviewed() and state(page, "two") == new()
    [[day, h, k, n, rows]] = marks(page)["app.py"]
    assert [day, h, k, n, len(rows.split())] == [today(page), repo.frame("one")["data-hash"], 1, 1, 14]
    left = page.evaluate("JSON.parse(localStorage.getItem(`${document.body.dataset.story}:reviewed`))")
    assert left == ["gone.py:12345678"]


def test_a_legacy_ripple_mark_carries_over(repo, story_page):
    repo.commit({"a.py": "old\n", "b.py": "old\n"})
    repo.commit({"a.py": "new\n", "b.py": "new\n"})
    repo.index()
    repo.story("@ripple a.py#h1 b.py#h1 id=rip")
    repo.build()
    page = story_page(repo)
    legacy = page.evaluate("[`${rip.dataset.path}:${rip.dataset.was}`]")
    page.evaluate(f"localStorage.setItem(`${{document.body.dataset.story}}:reviewed`, {json.dumps(json.dumps(legacy))})")
    story_page(repo, page)
    assert state(page, "rip") == reviewed()


def test_a_load_writes_only_when_something_changed(repo, story_page, writes):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    assert writes(page) == 0
    mark(page, "one")
    story_page(repo, page)
    assert writes(page) == 0
    page.evaluate(f"""(() => {{
        const m = JSON.parse(localStorage.getItem({KEY}));
        m["app.py"][0][0] -= 3;
        m["elsewhere.py"] = [[m["app.py"][0][0], "aaaaaaaaaaaaaaaaaaaa", 1, 1, "aaa bbb"]];
        localStorage.setItem({KEY}, JSON.stringify(m));
    }})()""")
    story_page(repo, page)
    assert writes(page) == 1
    assert marks(page)["app.py"][0][0] == today(page)
    assert marks(page)["elsewhere.py"][0][0] == today(page) - 3  # not on this page: left alone
    story_page(repo, page)
    assert writes(page) == 0


def test_marks_are_pruned_by_age_not_by_absence(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    page.evaluate(f"""(() => {{
        const day = Math.floor(Date.now() / 864e5);
        localStorage.setItem({KEY}, JSON.stringify({{
            "elsewhere.py": [[day - 10, "aaaaaaaaaaaaaaaaaaaa", 1, 1, "a"]], "ancient.py": [[day - 200, "bbbbbbbbbbbbbbbbbbbb", 1, 1, "b"]],
        }}));
    }})()""")
    story_page(repo, page)
    mark(page, "one")
    assert sorted(marks(page)) == ["app.py", "elsewhere.py"]


def test_the_store_keeps_under_its_ceiling_by_dropping_the_oldest(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    page.evaluate(f"""(() => {{
        const day = Math.floor(Date.now() / 864e5);
        const m = {{}};
        for (let i = 0; i < 60; i++) m[`f${{i}}.py`] = [[day - 60 + i, "aaaaaaaaaaaaaaaaaaaa", 1, 1, "aaaaaaaaaaaaaa ".repeat(470).trim()]];
        localStorage.setItem({KEY}, JSON.stringify(m));
    }})()""")
    mark(page, "one")
    kept = marks(page)
    assert len(json.dumps(kept, separators=(",", ":"))) <= 300_000
    assert "app.py" in kept and "f59.py" in kept and "f0.py" not in kept


def test_other_changes_stores_go_when_old_or_when_all_are_too_big(repo, story_page):
    two_hunks(repo)
    repo.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    repo.build()
    page = story_page(repo)
    put = """(([name, d, n]) => localStorage.setItem(`code-story:reviewed:x/y:${name}`,
        JSON.stringify({"a.py": [[Math.floor(Date.now() / 864e5) - d, "aaaaaaaaaaaaaaaaaaaa", 1, 1, "aaaaaaaaaaaaaa ".repeat(n).trim()]]})))"""
    left = lambda: page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('code-story:reviewed:x/y:')).sort()")
    page.evaluate(put, ["ancient", 200, 1])
    page.evaluate(put, ["small", 20, 1])
    mark(page, "one")
    assert left() == ["code-story:reviewed:x/y:small"]  # unused for 120 days
    page.evaluate(put, ["older", 10, 70000])
    page.evaluate(put, ["newer", 5, 70000])
    mark(page, "two")
    # past 2,000,000 characters in all: the least recently used go until it fits
    assert left() == ["code-story:reviewed:x/y:newer"]
    assert sorted(marks(page)) == ["app.py"] and len(marks(page)["app.py"]) == 2


def test_another_tab_folds_and_opens_what_it_marks(repo, story_page):
    repo.commit({"a.py": "".join(f"v{n} = {n}\n" for n in range(40))})
    repo.commit({"a.py": "".join(f"v{n} = {n * (7 if n in (3, 30) else 1)}\n" for n in range(40))})
    repo.index()
    repo.story("@diff a.py#h1 id=one\n@diff a.py#h2 id=two")
    repo.build()
    a, b = story_page(repo), story_page(repo)
    mark(a, "one")
    b.wait_for_function("one.classList.contains('collapsed')")
    assert state(b, "one") == reviewed()
    assert b.locator(".progress .p-txt").inner_text() == "1/2 reviewed"
    mark(b, "one")
    a.wait_for_function("!one.classList.contains('collapsed')")
    assert state(a, "one") == new()


def test_a_tour_never_touches_the_store(repo, story_page, writes):
    repo.commit({"app.py": LINES})
    repo.run("index", "--repo", repo.path, "--tour", "--out", repo.out)
    (repo.out / "story.md").write_text("# A tour\n\nLede.\n\n## Start {#start}\n\n@ctx app.py@head 1-5\n")
    repo.build()
    page = story_page(repo)
    assert writes(page) == 0
    assert not page.evaluate("Object.keys(localStorage).filter(k => k.startsWith('code-story:reviewed:'))")
