import json

import pytest


def test_multi_hunk_diff_preserves_file_order_and_gap(changed):
    changed.story("@diff app.py#h1 app.py#h2 id=whole")
    changed.build()
    assert json.loads(changed.frame("whole")["data-hunks"]) == ["app.py#h1", "app.py#h2"]
    text = changed.read("story.txt")
    assert text.index("value_2 = 200") < text.index("unchanged") < text.index("value_25 = 250")


@pytest.mark.parametrize("hunks", ["app.py#h2 app.py#h1", "app.py#h1 app.py#h1"])
def test_multi_hunk_diff_rejects_reversed_or_duplicate_hunks(changed, hunks):
    changed.story(f"@diff {hunks}")
    assert "list a file's hunks once each, in file order" in changed.build(ok=False).stderr


def test_rows_can_split_changed_rows_across_chapters(changed):
    changed.story("@diff app.py#h1 rows=1-2 id=removed\n\n## Added {#added}\n@diff app.py#h1 rows=3-6 id=added-code\n@diff app.py#h2")
    changed.build()
    assert changed.frame("removed")["data-hash"] != changed.frame("added-code")["data-hash"]
    assert "value_2 = 200" in changed.read("story.txt")
    changed.story("@diff app.py#h1 rows=1-2\n@diff app.py#h2")
    assert "1 changed lines not shown (R2)" in changed.build(ok=False).stderr


@pytest.mark.parametrize("rows", ["0-2", "3-2", "1-999"])
def test_rows_outside_hunk_are_rejected(changed, rows):
    changed.story(f"@diff app.py#h1 rows={rows}\n@diff app.py#h2")
    assert f"rows={rows} is outside 1-6" in changed.build(ok=False).stderr


@pytest.mark.parametrize("spec", ["src/context.py@head 1-2", "src/context.py@head:1-2", "src/context.py@base 2", "src/context.py@base:2"])
def test_context_accepts_ranges_and_single_lines(changed, spec):
    changed.story(f"@also app.py\n@ctx {spec} id=context")
    changed.build()
    assert "ctx" in changed.frame("context")["class"].split()
    assert "Unchanged" in changed.read("story.txt")
    assert "second = 2" in changed.read("story.txt")
    assert "third = 3" not in changed.read("story.txt")
    anchor = "src/context.py@head:1-2" if "head" in spec else "src/context.py@base:2-2"
    assert anchor in changed.json("anchors.json")["refs"]


def test_context_on_directory_names_the_problem(changed):
    changed.story("@also app.py\n@ctx src@head 1-2")
    assert "src is a directory at head" in changed.build(ok=False).stderr


def test_context_single_line_error_preserves_written_range(changed):
    changed.story("@also app.py\n@ctx src/context.py@head 9000")
    message = changed.build(ok=False).stderr
    assert "9000 is out of range" in message
    assert "9000-9000" not in message


def test_ripple_covers_sites_with_their_own_paths(repo):
    repo.commit({"a.py": "old\n", "b.py": "old\n"})
    repo.commit({"a.py": "new\n", "b.py": "new\n"})
    repo.index()
    repo.story('@ripple a.py#h1 b.py#h1 id=ripple label="Another caller"')
    repo.build()
    assert set(repo.json("anchors.json")["refs"]) == {"a.py#h1", "b.py#h1"}
    assert repo.tags(cls="rip-site")[0]["data-path"] == "b.py"
    assert repo.tags(cls="rip-site")[0]["data-hunk"] == "b.py#h1"
    assert "Another caller" in repo.read("story.txt")


def test_also_covers_every_hunk_and_fingerprints_file(changed):
    changed.story('@also app.py note="Supporting change"')
    changed.build()
    assert set(changed.json("anchors.json")["refs"]) == {"file:app.py", "app.py#h1", "app.py#h2"}
    assert "Supporting change" in changed.read("story.txt")


def test_escaped_at_sign_stays_prose(changed):
    changed.story("\\@someone reads this.\n\n@also app.py")
    changed.build()
    assert "@someone reads this." in changed.read("story.txt")
    changed.story("@someone reads this.\n@also app.py")
    assert "To start a line of prose with @, write \\@" in changed.build(ok=False).stderr


@pytest.mark.parametrize("fence", ["```", "~~~~"])
def test_only_valid_closing_fence_exposes_directives(changed, fence):
    changed.story(f"{fence}\n@diff nonexistent#h1\n{fence}not-a-close\n@diff still-nonexistent#h1\n{fence[0] * (len(fence) + 1)}\n\n@also app.py")
    result = changed.build()
    assert "story.md:7: hand-typed code block" in result.stdout
    assert "@diff still-nonexistent#h1" in changed.read("story.txt")


def test_indented_code_block_counts_as_hand_typed(changed):
    changed.story("Prose.\n\n    first = 1\n    second = 2\n\n@also app.py")
    assert "story.md:9: hand-typed code block" in changed.build().stdout


def test_unknown_hunk_suggests_existing_id_and_story_line(changed):
    changed.story("@diff app.py#h9")
    message = changed.build(ok=False).stderr
    assert "story.md:7: unknown hunk 'app.py#h9'; did you mean" in message
    assert "app.py#h1" in message


def test_duplicate_id_identifies_first_owner(changed):
    changed.story("@diff app.py#h1 id=flow\n@diff app.py#h2")
    message = changed.build(ok=False).stderr
    assert "id 'flow' is already used by" in message
    assert "the chapter at story.md:5" in message


@pytest.mark.parametrize("reserved", ["files", "side", "map", "help", "trace-pop", "syn-pick", "not-in-story", "def", "fd-custom", "br-custom"])
def test_page_ids_are_reserved(changed, reserved):
    changed.story(f"@also app.py id={reserved}")
    assert f"id '{reserved}' is taken by the page itself" in changed.build(ok=False).stderr


def test_generated_frame_ids_do_not_collide_with_author_ids(changed):
    changed.story("@diff app.py#h1\n@diff app.py#h2 id=f1")
    changed.build()
    ids = [a["id"] for a in changed.tags() if "id" in a]
    assert len(ids) == len(set(ids))


def test_cards_target_spine_even_after_nested_frame(changed):
    changed.story("""::: step
@diff app.py#h1 id=spine
::: note Supporting context
@ctx src/context.py@head 1 id=nested
:::
::: card 2
The value changes here.
:::
:::
@diff app.py#h2""")
    changed.build()
    assert changed.tags(cls="attach")[0]["data-to"] == "spine"
    assert changed.tags(cls="attach")[0]["data-lines"] == "2"


def test_card_cannot_target_lines_outside_spine(changed):
    changed.story("::: step\n@diff app.py#h1\n::: card 25\nWrong target.\n:::\n:::\n@diff app.py#h2")
    assert "card points at line(s) 25" in changed.build(ok=False).stderr
