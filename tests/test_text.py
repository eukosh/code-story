import re


def test_frame_tag_shares_caption_line(changed):
    changed.story('@diff app.py#h1 id=first title="First change"\n@diff app.py#h2')
    changed.build()
    text = changed.read("story.txt")
    assert re.search(r"^\[code #first\] app.py.*First change", text, re.M)
    assert "·  ·" not in text


def test_collapsed_file_is_one_line_without_rows(changed):
    changed.story('@also app.py note="Supporting change"')
    changed.build()
    text = changed.read("story.txt")
    lines = [line for line in text.splitlines() if "[collapsed on the page]" in line]
    assert len(lines) == 1
    assert "app.py" in lines[0] and "Supporting change" in lines[0]
    assert "+2" in lines[0] and "−2" in lines[0]
    assert "value_2" not in text and "value_25" not in text


def test_sketch_and_bracket_only_lines_are_verbatim(changed):
    changed.story("""[prose label]
next prose line

::: sketch Flow diagram
[start]
  first -> second
[code #pretend]
[collapsed on the page]
end
:::

@also app.py""")
    changed.build()
    text = changed.read("story.txt")
    assert "[prose label] next prose line" in text  # one Markdown paragraph, as on the page
    assert "[start]\n  first -> second\n[code #pretend]\n[collapsed on the page]\nend" in text
    assert "Flow diagram · not code from git" in text


def test_code_middle_dot_sequences_are_untouched(repo):
    repo.commit({"app.py": 'label = "before"\n'})
    repo.commit({"app.py": 'label = "one · · two"\n'})
    repo.index()
    repo.story("@diff app.py#h1")
    repo.build()
    assert 'label = "one · · two"' in repo.read("story.txt")


def test_hero_metadata_starts_its_own_line(changed):
    changed.story("@also app.py")
    changed.build()
    text = changed.read("story.txt")
    assert "A short lede.\n\n1 files" in text
    assert "A short lede. ·" not in text


def test_note_table_and_nested_paths_keep_separators(repo):
    repo.commit({"src/deep/app.py": "old\n"})
    repo.commit({"src/deep/app.py": "new\n"})
    repo.index()
    repo.story("""::: note Explanation
A plain note.
:::

| Name | Meaning |
| --- | --- |
| Token | Caller |

@diff src/deep/app.py#h1""")
    repo.build()
    text = repo.read("story.txt")
    assert "[note]" in text and "[ note]" not in text
    assert "\nName | Meaning\nToken | Caller\n" in text
    assert "src/deep/app.py" in text and "new" in text
