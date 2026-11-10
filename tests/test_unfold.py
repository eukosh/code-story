import base64
import html
import json
import re
import zlib

from conftest import LINES


def sources(repo):
    """The files packed into the page, inflated: each one's metadata and its rows as (sign, text)."""
    page = repo.read("story.html")
    meta = json.loads(re.search(r'<script type="application/json" id="_src">(.*?)</script>', page).group(1))
    blobs = dict(re.findall(r'<script type="text/plain" id="_s(\d+)">(.*?)</script>', page))
    out = []
    for i, m in enumerate(meta):
        lines = zlib.decompress(base64.b64decode(blobs[str(i)])).decode().split("\n")
        rows = [(ln[0], html.unescape(re.sub(r"<[^>]+>", "", ln[1:])).replace("\xa0", " ")) for ln in lines]
        out.append({**m, "rows": rows})
    return out


def code_boxes(repo):
    return [a for a in repo.tags("div", "code") if "data-src" in a]


def test_diff_source_is_the_full_context_diff(repo):
    old = [f"line_{n} = {n}" for n in range(1, 61)]
    new = list(old)
    new[2] = "line_3 = 'changed'"
    del new[30:33]
    new.insert(45, "added = True")
    new.append("tail = 1")
    new.insert(0, "head = 0")
    repo.commit({"app.py": "\n".join(old) + "\n"})
    repo.commit({"app.py": "\n".join(new) + "\n"})
    repo.index()
    repo.story("@also app.py")
    repo.build()
    patch = repo.git("diff", "-U9999", "--no-color", repo.base, "HEAD", "--", "app.py").split("\n")
    want = [(ln[0], ln[1:]) for ln in patch[next(i for i, ln in enumerate(patch) if ln.startswith("@@")) + 1 :]]
    (src,) = sources(repo)
    assert src["rows"] == want
    assert (src["n"], src["x"]) == (len(want), 1)
    assert len(src["h"]) > 2
    for start, length, o, n in src["h"]:
        before = [kind for kind, _ in want[:start]]
        assert o == 1 + sum(k != "+" for k in before)
        assert n == 1 + sum(k != "-" for k in before)
        assert want[start][0] == " " or start == 0
        assert any(kind != " " for kind, _ in want[start : start + length])
    box = code_boxes(repo)[0]
    starts = [h[0] for h in src["h"]]
    assert int(box["data-at"]) == starts[0]
    assert [int(a["data-at"]) for a in repo.tags("div", "gap") if "data-at" in a and "data-len" not in a] == starts[1:]


def test_frame_knows_where_its_rows_sit_in_the_file(changed):
    changed.story("@diff app.py#h1 rows=2-4 id=part\n@diff app.py#h1 rows=1-1\n@diff app.py#h1 rows=5-6\n@diff app.py#h2 id=second")
    changed.build()
    src = sources(changed)[0]
    boxes = code_boxes(changed)
    assert [int(b["data-at"]) for b in boxes[:4]] == [1, 0, 4, src["h"][1][0]]
    # 30 lines and two removed ones; the second hunk opens at line 22, one row later for the line removed above it
    assert src["n"] == 32
    assert src["h"] == [[0, 6, 1, 1], [22, 8, 22, 22]]


def test_full_diff_and_left_out_files_ship_no_rows(repo):
    repo.commit({"app.py": LINES, "tests/test_app.py": "hidden_old\n"})
    repo.commit({"app.py": LINES.replace("value_2 = 2", "value_2 = 200"), "tests/test_app.py": "hidden_new\n"})
    repo.index()
    repo.story("@diff app.py#h1")
    repo.build()
    page = repo.read("story.html")
    assert "hidden_new" not in page
    assert len(repo.tags("div", "row")) == 6
    # each hunk the page fills in later: twice in the full diff, once under "Not in story"
    assert sorted(int(a["data-len"]) for a in repo.tags("div", "gap") if "data-len" in a) == [2, 2, 6]
    assert any(("+", "hidden_new") in s["rows"] for s in sources(repo))


def test_ctx_frame_unfolds_the_plain_file(changed):
    changed.story("@diff app.py#h1 app.py#h2\n@ctx src/context.py@head 2 id=ctx")
    changed.build()
    diff, plain = sources(changed)
    assert plain["p"] == 1 and "h" not in plain
    assert plain["rows"] == [(" ", "first = 1"), (" ", "second = 2"), (" ", "third = 3")]
    assert [(b["data-src"], b["data-at"]) for b in code_boxes(changed)[:2]] == [("0", "0"), ("1", "1")]


def test_deleted_and_renamed_files_have_sources(repo):
    repo.commit({"gone.py": "a = 1\nb = 2\n", "old.py": LINES})
    repo.git("mv", "old.py", "new.py")
    repo.commit({"gone.py": None, "new.py": LINES.replace("value_20 = 20", "value_20 = 2000")})
    repo.index()
    repo.story("@also gone.py\n@also new.py")
    repo.build()
    gone, moved = sources(repo)
    assert gone["rows"] == [("-", "a = 1"), ("-", "b = 2")]
    assert (moved["n"], moved["x"]) == (31, 1)
    assert moved["rows"][19:21] == [("-", "value_20 = 20"), ("+", "value_20 = 2000")]


def test_a_huge_file_keeps_its_hunks_but_cannot_unfold(repo):
    big = "".join(f"row {n:06d} {'x' * 40}\n" for n in range(32_000))
    repo.commit({"big.txt": big})
    repo.commit({"big.txt": big.replace("row 000010 ", "row changed ")})
    repo.index()
    repo.story("@diff big.txt#h1 id=big")
    repo.build()
    (src,) = sources(repo)
    assert (src["n"], src["x"]) == (8, 0)
    # the story's frame can't unfold; only the full diff still fills its rows from the source
    assert len(code_boxes(repo)) == 1
    assert len(repo.read("story.html")) < 400_000


def test_a_trace_must_show_up_in_the_story_itself(repo):
    repo.commit({"app.py": "value = 1\n", "tests/test_app.py": "secret_name = 1\n"})
    repo.commit({"app.py": "value = 2\n", "tests/test_app.py": "secret_name = 2\n"})
    repo.index()
    repo.story("@diff app.py#h1", front="traces:\n  secret: [secret_name]")
    assert "trace 'secret' never appears" in repo.build().stdout


def test_the_size_limit_counts_bytes(repo):
    wide = "".join(f"строка {n:06d} {'ж' * 40}\n" for n in range(16_000))
    assert len(wide) < 1_500_000 < len(wide.encode())
    repo.commit({"wide.txt": wide})
    repo.commit({"wide.txt": wide.replace("строка 000010 ", "строка другая ")})
    repo.index()
    repo.story("@diff wide.txt#h1")
    repo.build()
    (src,) = sources(repo)
    assert src["x"] == 0


def test_a_name_ending_in_a_carriage_return_is_still_read(repo):
    repo.commit({"app.py": "value = 1\n", "tests/odd\r": "kept = 1\n"})
    repo.commit({"app.py": "value = 2\n", "tests/odd\r": "kept = 2\n"})
    repo.index()
    repo.story("@diff app.py#h1")
    repo.build()
    odd = next(s for s in sources(repo) if ("+", "kept = 2") in s["rows"])
    assert odd["x"] == 1


def test_very_long_lines_go_without_word_marks(repo):
    old = "name " * 3000
    repo.commit({"data.txt": old + "end\n"})
    repo.commit({"data.txt": old + "END\n"})
    repo.index()
    repo.story("@diff data.txt#h1")
    repo.build()
    assert "<mark>" not in repo.read("story.html")
