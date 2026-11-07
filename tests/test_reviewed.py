from conftest import LINES


def test_frame_hash_survives_earlier_hunk_and_changes_with_content(repo):
    repo.commit({"app.py": LINES})
    repo.commit({"app.py": LINES.replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    repo.story("@diff app.py#h1 id=target")
    repo.build()
    original = repo.frame("target")["data-hash"]
    repo.commit({"app.py": (repo.path / "app.py").read_text().replace("value_2 = 2", "value_2 = 200")})
    repo.index()
    repo.story("@diff app.py#h1\n@diff app.py#h2 id=target")
    repo.build("--accept")
    assert repo.frame("target")["data-hash"] == original
    repo.commit({"app.py": (repo.path / "app.py").read_text().replace("value_25 = 250", "value_25 = 251")})
    repo.index()
    repo.build("--accept")
    assert repo.frame("target")["data-hash"] != original


def test_ripple_hash_survives_folded_hunk_renumbering_but_tracks_content(repo):
    repo.commit({"a.py": "old\n", "b.py": LINES})
    repo.commit({"a.py": "new\n", "b.py": LINES.replace("value_25 = 25", "value_25 = 250")})
    repo.index()
    repo.story("@ripple a.py#h1 b.py#h1 id=target")
    repo.build()
    original = repo.frame("target")["data-hash"]
    repo.commit({"b.py": (repo.path / "b.py").read_text().replace("value_2 = 2", "value_2 = 200")})
    repo.index()
    repo.story("@diff b.py#h1\n@ripple a.py#h1 b.py#h2 id=target")
    repo.build("--accept")
    assert repo.frame("target")["data-hash"] == original
    repo.commit({"b.py": (repo.path / "b.py").read_text().replace("value_25 = 250", "value_25 = 251")})
    repo.index()
    repo.build("--accept")
    assert repo.frame("target")["data-hash"] != original


def test_ripple_hash_includes_folded_site_path(repo):
    repo.commit({"a.py": "old\n", "b.py": "old\n", "c.py": "old\n"})
    repo.commit({"a.py": "new\n", "b.py": "new\n", "c.py": "new\n"})
    repo.index()
    repo.story("@ripple a.py#h1 b.py#h1 id=target\n@also c.py")
    repo.build()
    original = repo.frame("target")["data-hash"]
    repo.story("@ripple a.py#h1 c.py#h1 id=target\n@also b.py")
    repo.build()
    assert repo.frame("target")["data-hash"] != original


def test_full_diff_file_and_hunk_ids_are_unique(repo):
    paths = ["a", "a-h1", "a-b.py", "a_b.py", "日本.py", "中文.py"]
    repo.commit({path: "old\n" for path in paths})
    repo.commit({path: "new\n" for path in paths})
    repo.index()
    repo.story("\n".join(f"@also {path}" for path in paths))
    repo.build()
    ids = [a["id"] for a in repo.tags() if a.get("id", "").startswith("fd-")]
    assert len(ids) == len(set(ids)) == 2 * len(paths)
    assert all(a["data-fd"] in ids for a in repo.tags() if a.get("data-fd"))
