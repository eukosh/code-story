"""Reviewed marks in the page: a snippet's path, hash and place among its twins, kept per change (D44)."""
import json

import pytest

from conftest import LINES
from test_reviewed import BLOCK, two_hunks

KEY = "`code-story:reviewed:${document.body.dataset.marks}`"
LEGACY = "`${document.body.dataset.story}:reviewed`"
TWO = "@diff app.py#h1 id=one\n@diff app.py#h2 id=two"
ONE = "@diff a.py#h1 id=one"


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


def new():
    return {"state": "new", "label": None, "folded": False, "bars": []}


def reviewed():
    return {"state": "reviewed", "label": None, "folded": True, "bars": []}


def changed(*bars):
    return {"state": "changed", "label": "Changed since review", "folded": False, "bars": list(bars)}


def mark(page, fid):
    page.locator(f'#{fid} .fh [data-act="reviewed"]').click()


def marks(page):
    return page.evaluate(f"JSON.parse(localStorage.getItem({KEY}) || '{{}}')")


def places(page, path):
    """Which of how many twins each mark of a file is."""
    return [x[2:4] for x in marks(page)[path]]


def edit_store(page, js):
    """Runs `js` on the stored marks `m`, with today's day number as `day`, and saves them."""
    page.evaluate(f"""(() => {{
        const day = Math.floor(Date.now() / 864e5), m = JSON.parse(localStorage.getItem({KEY}) || "{{}}");
        {js};
        localStorage.setItem({KEY}, JSON.stringify(m));
    }})()""")


def change(repo, path, base, edited):
    repo.commit({path: base})
    repo.commit({path: edited})
    repo.index()


def opened(repo, story_page, story, *marked):
    """The story built and open, with these snippets marked reviewed."""
    repo.story(story)
    repo.build()
    page = story_page(repo)
    for fid in marked:
        mark(page, fid)
    return page


def again(repo, story_page, page, files=None, story=None):
    """The next pass over the change: a commit, a story cut another way, or both, in the same tab."""
    if files:
        repo.commit(files)
        repo.index()
    if story:
        repo.story(story)
    repo.build(*(["--accept"] if files else []))
    return story_page(repo, page)


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
    change(repo, "job.py", base, base.replace("step_5()\n", "step_5()\n        extra()\n", 2 if both else 1))
    return base


# ---- what stays reviewed ----


@pytest.mark.parametrize("marked, files, story, fresh", [
    ("one", {"other.py": "x = 1\n"}, TWO + "\n@also other.py", "two"),
    ("one", None, "@diff app.py#h2 id=two\n@diff app.py#h1 id=one", "two"),
    ("two", "an edit between the hunks", "@diff app.py#h1 id=one\n@diff app.py#h2 id=mid\n@diff app.py#h3 id=two", "mid"),
], ids=["an unrelated commit", "snippets in another order", "hunks renumbered"])
def test_a_mark_survives(repo, story_page, marked, files, story, fresh):
    text = two_hunks(repo)
    page = opened(repo, story_page, TWO, marked)
    again(repo, story_page, page, {"app.py": text.replace("value_15 = 15", "value_15 = 150")} if isinstance(files, str) else files, story)
    assert state(page, marked) == reviewed()
    assert state(page, fresh) == new()
    assert page.locator(".progress .p-chg").is_hidden()


def test_one_hunk_in_two_chapters_is_marked_in_both(repo, story_page):
    two_hunks(repo)
    page = opened(repo, story_page, "@diff app.py#h1 id=first\n@diff app.py#h2\n\n## Again {#later}\n\n@diff app.py#h1 id=again", "first")
    assert state(page, "first") == state(page, "again") == reviewed()
    mark(page, "again")
    assert state(page, "first") == state(page, "again") == new()


def test_a_branch_and_its_working_tree_share_marks(repo, tmp_path, story_page):
    base = repo.commit({"app.py": LINES})
    repo.git("checkout", "-q", "-b", "feature")
    repo.commit({"app.py": LINES.replace("value_9 = 9", "value_9 = 90")})
    repo.index(head="feature", base=base)
    opened(repo, story_page, "@diff app.py#h1 id=one", "one")
    repo.out = tmp_path / "tree"
    repo.index(head="WORKTREE", base=base)
    assert state(opened(repo, story_page, "@diff app.py#h1 id=late"), "late") == reviewed()


def test_another_pr_of_the_repo_takes_nothing_from_these_marks(repo, tmp_path, story_page):
    """Two branches make the same edit, each in another of two twin methods: the same path, rows and place."""
    body = "".join(f"        step_{n}()\n" for n in range(1, 10))
    base = "class Job:\n    def daily(self):\n" + body + "\n    def hourly(self):\n" + body
    main = repo.commit({"job.py": base})
    edit = lambda at: base[:at] + "step_5()\n        extra()\n" + base[at + len("step_5()\n"):]
    pages = []
    for name, at in (("one", base.index("step_5()\n")), ("two", base.rindex("step_5()\n"))):
        repo.git("checkout", "-q", "-B", name, main)
        repo.commit({"job.py": edit(at)})
        repo.out = tmp_path / name
        repo.index(head=name, base=main)
        pages.append(opened(repo, story_page, "@diff job.py#h1 id=snip", *(["snip"] if name == "one" else [])))
    assert state(pages[1], "snip") == new()
    assert marks(pages[1]) == {}


# ---- twins: the same rows at two places ----


def test_marking_one_of_two_twins_marks_only_that_one(repo, story_page):
    twins(repo)
    page = opened(repo, story_page, "@diff job.py#h1 id=daily\n@diff job.py#h2 id=hourly", "daily")
    assert repo.frame("daily")["data-hash"] == repo.frame("hourly")["data-hash"]
    assert state(page, "daily") == reviewed() and state(page, "hourly") == new()
    mark(page, "hourly")
    assert places(page, "job.py") == [[1, 2], [2, 2]]
    story_page(repo, page)
    assert state(page, "daily") == state(page, "hourly") == reviewed()
    mark(page, "hourly")
    assert state(page, "daily") == reviewed() and state(page, "hourly") == new()


def test_twins_are_counted_in_file_order_and_one_hunk_shown_twice_is_one_of_them(repo, story_page):
    twins(repo)
    page = opened(repo, story_page, "@diff job.py#h2 id=hourly\n@diff job.py#h1 id=daily\n\n## Again {#later}\n\n@diff job.py#h2 id=again", "hourly")
    assert state(page, "hourly") == state(page, "again") == reviewed() and state(page, "daily") == new()
    assert places(page, "job.py") == [[2, 2]]
    again(repo, story_page, page, story="@diff job.py#h1 id=daily\n@diff job.py#h2 id=hourly")
    assert state(page, "hourly") == reviewed() and state(page, "daily") == new()


def test_a_twin_that_appears_later_voids_the_mark(repo, story_page):
    base = twins(repo, both=False)
    page = opened(repo, story_page, "@diff job.py#h1 id=daily", "daily")
    again(repo, story_page, page, {"job.py": base.replace("step_5()\n", "step_5()\n        extra()\n")},
          "@diff job.py#h1 id=daily\n@diff job.py#h2 id=hourly")
    assert state(page, "daily") == state(page, "hourly") == new()
    assert page.locator(".progress .p-chg").is_hidden()
    mark(page, "daily")
    assert state(page, "daily") == reviewed() and state(page, "hourly") == new()
    assert places(page, "job.py") == [[1, 2]]  # the void mark of the same rows went


# ---- code edited under a mark: "Changed since review", or plain unreviewed ----


def test_an_edited_line_is_changed_since_review(repo, story_page):
    text = two_hunks(repo)
    page = opened(repo, story_page, TWO, "one", "two")
    again(repo, story_page, page, {"app.py": text.replace("step_4 = 4", "step_4 = 44")})
    assert state(page, "one") == changed("step_4 = 44")
    assert state(page, "two") == reviewed()
    assert page.locator("#one .fh .chip.chg").get_attribute("title") == (
        "The code changed after you marked it reviewed. Bars mark the lines that differ from what you marked, "
        "and the lines either side of one that was removed"
    )
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


ADDED = LINES.replace("value_5 = 5\n", "value_5 = 5\n" + BLOCK)
V0 = "".join(f"v{n} = {n}\n" for n in range(30))
V1 = V0.replace("v10 = 10\n", "v10 = 100\n")
AUTH = "def handle(req):\n    log(req)\n    verify_token(req)\n    return run(req)\n"
LONG = "def handle(req):\n    log(req)\n    user = load_user(req)\n    verify_token(req)\n    audit(user)\n    return run(req, user)\n"
SHORT = "".join(f"v{n} = {n}\n" for n in range(5))
STEPS = [f"step_{n}()\n" for n in range(1, 9)]
BIG = [f"line {n}\n" for n in range(1001)]
swapped = lambda s: s.replace("    verify_token(req)\n", "    verify_token_v2(req)\n")
kept = lambda s: s.replace("    verify_token(req)\n", "    verify_token(req)\n    verify_token_v2(req)\n")

# what the file was, what was marked, what it became, and how the snippet reads then
EDITS = {
    "a removed line bars the lines either side": (LINES, ADDED, ADDED.replace("step_4 = 4\n", ""), changed("step_3 = 3", "step_5 = 5")),
    "a line added at the end of the hunk": (V0, V1, V1.replace("v13 = 13\n", "v13 = 13\nrm_all()\n"), changed("rm_all()", "v14 = 14", "v15 = 15", "v16 = 16")),
    "a line added just above the hunk": (V0, V1, V1.replace("v6 = 6\n", "v6 = 6\nrm_all()\n"), changed("v4 = 4", "v5 = 5", "v6 = 6", "rm_all()")),
    "a removal taken back": (AUTH, swapped(AUTH), kept(AUTH), changed("    verify_token(req)")),
    "a removal taken back that moves the hunk's start": (LONG, swapped(LONG), kept(LONG), changed("    verify_token(req)")),
    "a newline added at the end of the file": (SHORT, SHORT + "y = 2", SHORT + "y = 2\n", changed("y = 2")),
    "a newline added at the end of a two-line file": ("x = 1\n", "x = 1\ny = 2", "x = 1\ny = 2\n", changed("y = 2")),
    "a rewrite": (LINES, ADDED, ADDED.replace(BLOCK, "".join(f"other_{n} = {n}\n" for n in range(9))), new()),
    # every row is shared, but in order only two of eight: less than half, so not the code it was
    "the same lines in another order": ("", "".join(STEPS), STEPS[0] + "".join(reversed(STEPS[1:])), new()),
    "one line edited in a thousand": ("", "".join(BIG), "".join(BIG).replace("line 500\n", "line 500!\n"), changed("line 500!")),
}


def test_code_edited_under_a_mark(repo, story_page):
    """Each case in a file of its own, all in one story: one build before and one after."""
    ids = [f"c{i}" for i in range(len(EDITS))]
    files = lambda k: {f"{c}.py": case[k] for c, case in zip(ids, EDITS.values())}
    repo.commit(files(0))
    repo.commit(files(1))
    repo.index()
    page = opened(repo, story_page, "\n".join(f"@diff {c}.py#h1 id={c}" for c in ids), *ids)
    again(repo, story_page, page, files(2))
    assert {name: state(page, c) for name, c in zip(EDITS, ids)} == {name: case[3] for name, case in EDITS.items()}


def test_to_revisit_reaches_every_snippet_on_a_page_too_short_to_scroll(repo, story_page):
    files = dict.fromkeys(("f0.py", "f1.py", "f2.py"), "a = 1\nb = 2\n")
    repo.commit(dict.fromkeys(files, "a = 1\n"))
    repo.commit(files)
    repo.index()
    page = opened(repo, story_page, "\n".join(f"@diff f{i}.py#h1 id=s{i}" for i in range(3)), "s0", "s1", "s2")
    again(repo, story_page, page, dict.fromkeys(files, "a = 1\nb = 3\n"))
    seen = []
    for _ in range(3):
        page.locator(".progress .p-chg").click()
        seen.append(page.locator(".toast").inner_text()[-6:])
    assert sorted(seen) == ["1 of 3", "2 of 3", "3 of 3"]


def test_a_snippet_whose_short_hash_collides_is_changed(repo, story_page):
    """The nonce was found in 17 seconds on a laptop: the snippet's hash starts like the reviewed one's."""
    base = AUTH.replace("verify_token", "check")
    change(repo, "a.py", base, AUTH)
    page = opened(repo, story_page, ONE, "one")
    before = repo.frame("one")["data-hash"]
    again(repo, story_page, page, {"a.py": base.replace("    check(req)\n", "    skip_verify(req)  # 00003833f3cc\n")})
    after = repo.frame("one")["data-hash"]
    assert before[:8] == after[:8] and before != after
    assert state(page, "one") == changed("    skip_verify(req)  # 00003833f3cc")


def test_the_marked_rows_of_a_grown_hunk_shown_alone_are_reviewed(repo, story_page):
    change(repo, "a.py", V0, V1)
    page = opened(repo, story_page, ONE, "one")
    again(repo, story_page, page, {"a.py": V1.replace("v13 = 13\n", "v13 = 13\nrm_all()\n")},
          "@diff a.py#h1 rows=1-8 id=seen\n@diff a.py#h1 rows=9-12 id=added")
    assert state(page, "seen") == reviewed() and state(page, "added") == new()


def test_changed_code_goes_to_one_snippet_only(repo, story_page):
    """Both twins edited again after one was marked: the first that shares the most rows takes the hint."""
    base = twins(repo)
    page = opened(repo, story_page, "@diff job.py#h1 id=daily\n@diff job.py#h2 id=hourly", "daily")
    again(repo, story_page, page, {"job.py": base.replace("step_5()\n", "step_5()\n        extra(1)\n")})
    assert state(page, "daily") == changed("        extra(1)")
    assert state(page, "hourly") == new()


def test_changed_code_goes_to_a_snippet_of_its_own_file(repo, story_page):
    edit = LINES.replace("value_9 = 9", "value_9 = 90")
    repo.commit({"a.py": LINES, "constructor": LINES})  # a name every JavaScript object answers to
    repo.commit({"a.py": edit, "constructor": edit})
    repo.index()
    page = opened(repo, story_page, "@diff a.py#h1 id=a\n@diff constructor#h1 id=b", "a")
    again(repo, story_page, page, {"a.py": LINES.replace("value_9 = 9", "value_9 = 91")})
    assert state(page, "a") == changed("value_9 = 91")
    assert state(page, "b") == new()


def test_changed_code_never_goes_to_a_reviewed_snippet(repo, story_page):
    body = "    a = load()\n    b = parse(a)\n    c = check(b)\n    d = send(c)\n    e = log(d)\n    f = done(e)\n    return f\n"
    base = "def one():\n" + body + "\n\ndef two():\n" + body
    edited = base.replace("    c = check(b)\n", "    c = check(b, strict=True)\n")
    change(repo, "app.py", base, edited)
    page = opened(repo, story_page, "@diff app.py#h2 id=two\n@diff app.py#h1 rows=2-8 id=one", "two", "one")
    again(repo, story_page, page, {"app.py": edited.replace("strict=True", "strict=False", 1)})
    assert state(page, "two") == reviewed()
    assert state(page, "one") == changed("    c = check(b, strict=False)")


def test_row_hashes_alone_never_make_a_snippet_reviewed(repo, story_page):
    two_hunks(repo)
    page = opened(repo, story_page, TWO, "one")
    edit_store(page, 'm["app.py"][0][1] = "0".repeat(20)')
    story_page(repo, page)
    assert state(page, "one") == new()


# ---- the same code cut into other snippets: unreviewed, and nothing changed ----


def test_a_slice_of_a_marked_snippet_is_unreviewed_with_no_chip(repo, story_page):
    two_hunks(repo)
    page = opened(repo, story_page, TWO, "one")
    again(repo, story_page, page, story="@diff app.py#h1 rows=6-14 id=late\n@diff app.py#h2 id=two\n@diff app.py#h1 rows=1-5 id=early")
    assert state(page, "late") == state(page, "early") == state(page, "two") == new()
    assert page.locator(".progress .p-chg").is_hidden()


def test_slices_or_hunks_marked_apart_and_shown_as_one_are_unreviewed_with_no_chip(repo, story_page):
    two_hunks(repo)
    page = opened(repo, story_page, "@diff app.py#h1 rows=1-5 id=top\n@diff app.py#h1 rows=6-14 id=rest\n@diff app.py#h2 id=two", "top", "rest", "two")
    again(repo, story_page, page, story="@diff app.py#h1 id=whole\n@diff app.py#h2 id=two")
    assert state(page, "whole") == new()
    assert state(page, "two") == reviewed()
    again(repo, story_page, page, story="@diff app.py#h1 app.py#h2 id=both")
    assert state(page, "both") == new()


# ---- the store ----

FAKE = '"a".repeat(20), 1, 1'  # a mark of nothing on the page: its hash and place


@pytest.mark.parametrize("before, after, story, was", [
    ({"app.py": LINES}, {"app.py": LINES.replace("value_9 = 9", "value_9 = 90")}, "@diff app.py#h1 id=one", "one.dataset.hash.slice(0, 8)"),
    ({"a.py": "old\n", "b.py": "old\n"}, {"a.py": "new\n", "b.py": "new\n"}, "@ripple a.py#h1 b.py#h1 id=one", "one.dataset.was"),
], ids=["a snippet", "a ripple"])
def test_legacy_marks_carry_over(repo, story_page, before, after, story, was):
    repo.commit(before)
    repo.commit(after)
    repo.index()
    page = opened(repo, story_page, story)
    legacy = page.evaluate(f"[`${{one.dataset.path}}:${{{was}}}`, 'gone.py:12345678']")
    page.evaluate(f"localStorage.setItem({LEGACY}, {json.dumps(json.dumps(legacy))})")
    story_page(repo, page)
    assert state(page, "one") == reviewed()
    [[day, h, k, n, rows]] = next(iter(marks(page).values()))
    assert [day, h, k, n] == [page.evaluate("Math.floor(Date.now() / 864e5)"), repo.frame("one")["data-hash"], 1, 1]
    assert page.evaluate(f"JSON.parse(localStorage.getItem({LEGACY}))") == ["gone.py:12345678"]


def test_a_legacy_mark_that_twins_share_marks_neither(repo, story_page):
    twins(repo)
    page = opened(repo, story_page, "@diff job.py#h1 id=daily\n@diff job.py#h2 id=hourly")
    page.evaluate(f"localStorage.setItem({LEGACY}, JSON.stringify([`${{daily.dataset.path}}:${{daily.dataset.hash.slice(0, 8)}}`]))")
    story_page(repo, page)
    assert state(page, "daily") == state(page, "hourly") == new()
    assert page.evaluate(f"localStorage.getItem({LEGACY})") is None


def test_a_load_writes_only_when_something_changed(repo, story_page, writes):
    two_hunks(repo)
    page = opened(repo, story_page, TWO)
    assert writes(page) == 0
    assert page.locator(".progress .p-txt").inner_text() == "0/2 reviewed"
    mark(page, "one")
    story_page(repo, page)
    assert writes(page) == 0
    edit_store(page, f'm["app.py"][0][0] -= 3; m["elsewhere.py"] = [[day - 3, {FAKE}, "aaa bbb"]]')
    story_page(repo, page)
    assert writes(page) == 1
    today = page.evaluate("Math.floor(Date.now() / 864e5)")
    assert marks(page)["app.py"][0][0] == today
    assert marks(page)["elsewhere.py"][0][0] == today - 3  # not on this page: left alone
    story_page(repo, page)
    assert writes(page) == 0


def test_marks_are_pruned_by_age_not_by_absence(repo, story_page):
    two_hunks(repo)
    page = opened(repo, story_page, TWO)
    edit_store(page, f'm["elsewhere.py"] = [[day - 10, {FAKE}, "a"]]; m["ancient.py"] = [[day - 200, {FAKE}, "b"]]')
    story_page(repo, page)
    mark(page, "one")
    assert sorted(marks(page)) == ["app.py", "elsewhere.py"]


def test_the_store_keeps_under_its_ceiling_by_dropping_the_oldest(repo, story_page):
    two_hunks(repo)
    page = opened(repo, story_page, TWO)
    edit_store(page, f'for (let i = 0; i < 60; i++) m[`f${{i}}.py`] = [[day - 60 + i, {FAKE}, "aaaaaaaaaaaaaa ".repeat(470).trim()]]')
    mark(page, "one")
    kept = marks(page)
    assert len(json.dumps(kept, separators=(",", ":"))) <= 300_000
    assert "app.py" in kept and "f59.py" in kept and "f0.py" not in kept


def test_other_changes_stores_go_when_old_or_when_all_are_too_big(repo, story_page):
    two_hunks(repo)
    page = opened(repo, story_page, TWO)
    put = f"""(([name, d, n]) => localStorage.setItem(`code-story:reviewed:x/y:${{name}}`,
        JSON.stringify({{"a.py": [[Math.floor(Date.now() / 864e5) - d, {FAKE}, "aaaaaaaaaaaaaa ".repeat(n).trim()]]}})))"""
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
    a = opened(repo, story_page, "@diff a.py#h1 id=one\n@diff a.py#h2 id=two")
    b = story_page(repo)
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
