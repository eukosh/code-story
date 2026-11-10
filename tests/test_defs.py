import html
import json
import re

import pytest

from test_unfold import sources


def manifest(repo):
    return json.loads(re.search(r'id="_def">(.*?)</script>', repo.read("story.html")).group(1))


def links(repo):
    """The linked names in the story's frames, in page order: (name, [(path, line) of each place it opens])."""
    page = repo.read("story.html")
    main = page[page.index("<main") : page.index("</main>")]
    defs = manifest(repo)
    return [
        (html.unescape(m[2]), [tuple(defs[int(i)][3:]) for i in m[1].split()])
        for m in re.finditer(r'<span[^>]*data-d="([\d ]+)"[^>]*>([^<]*)</span>', main)
    ]


def opened(repo, path, line):
    """The rows a click on a name defined at path:line puts in the panel."""
    src, at, n = next(d[:3] for d in manifest(repo) if d[3:] == [path, line])
    return [text for _, text in sources(repo)[src]["rows"][at : at + n]]


def story(repo, files, body=None, front=""):
    repo.commit({"README.md": "start\n"})
    repo.commit(files)
    repo.index()
    repo.story(body or "\n\n".join(f"@also {p}" for p in files if not p.startswith("tests/")), front)
    return repo.build()


CACHE = """\
import os


# how rows are read
@cached
def load_rows(path):
    rows = [path]
    return rows


def other():
    return 1
"""


def test_a_call_opens_the_function_it_names(repo):
    story(repo, {"src/cache.py": CACHE, "app.py": "from src.cache import load_rows\n\nrows = load_rows(1)\n"})
    assert links(repo) == [("load_rows", [("src/cache.py", 6)])] * 2
    assert opened(repo, "src/cache.py", 6) == [
        "# how rows are read", "@cached", "def load_rows(path):", "    rows = [path]", "    return rows",
    ]


def test_a_definition_opens_from_its_diff_with_the_removed_lines_in_place(repo):
    repo.commit({"src/cache.py": CACHE, "app.py": "x = 1\n"})
    repo.commit({"src/cache.py": CACHE.replace("    rows = [path]\n", "    rows = [path, 2]\n"), "app.py": "x = load_rows(1)\n"})
    repo.index()
    repo.story("@also src/cache.py\n\n@also app.py")
    repo.build()
    assert opened(repo, "src/cache.py", 6) == [
        "# how rows are read", "@cached", "def load_rows(path):", "    rows = [path]", "    rows = [path, 2]", "    return rows",
    ]


def test_a_removed_line_links_nothing(repo):
    repo.commit({"src/cache.py": CACHE, "app.py": "x = load_rows(1)\ny = 2\n"})
    repo.commit({"src/cache.py": CACHE + "\nZ = 1\n", "app.py": "y = 2\n"})
    repo.index()
    repo.story("@also src/cache.py\n\n@also app.py")
    repo.build()
    assert links(repo) == []


def test_a_name_alone_has_to_settle_where_it_leads(repo):
    story(repo, {
        "src/cache.py": "class Cache:\n    def get(self, key):\n        return key\n\n    def drop_all(self):\n        return 0\n\n\ndef load(path):\n    return path\n",
        "app.py": (
            "d = {}\n"
            "a = d.get(1)\n"  # some other get
            "b = cache.get(1)\n"  # the receiver names the file
            "c = store.drop_all()\n"  # a compound name says enough
            "e = load\n"  # one word, not called
            "f = load(1)\n"
            "g = run(load=2)\n"  # a keyword, not the function
        ),
    })
    assert links(repo) == [
        ("get", [("src/cache.py", 2)]),
        ("drop_all", [("src/cache.py", 5)]),
        ("load", [("src/cache.py", 9)]),
    ]


def test_a_function_inside_a_function_is_not_a_method(repo):
    story(repo, {
        "server.py": "def build_server():\n    def list_tables(ctx):\n        return ctx\n\n    return list_tables(1)\n",
        "tools.py": "x = client.list_tables(2)\ny = list_tables(3)\n",
    })
    assert links(repo) == [("list_tables", [("server.py", 2)])]


def test_an_import_names_the_file_a_name_comes_from(repo):
    story(repo, {
        "src/models.py": "class Thing:\n    pass\n",
        "a.py": "from src.models import Thing\n\nx = Thing()\n",
        "b.py": "from lib.models import Thing\n\ny = Thing()\n",
        "c.py": "from lib.models import Thing as Base\n\nz = Base()\n",
    })
    assert links(repo) == [("Thing", [("src/models.py", 1)])] * 2


def test_a_method_does_not_lead_to_itself(repo):
    story(repo, {
        "auth.py": "class Verifier(Base):\n    def load_token(self, token):\n        return super().load_token(token)\n\n    def check(self):\n        return self.load_token(1)\n",
    })
    assert links(repo) == [("load_token", [("auth.py", 2)])]


def test_test_helpers_serve_only_tests(repo):
    story(repo, {
        "tests/conftest.py": "def make_client():\n    return 1\n",
        "tests/test_app.py": "c = make_client()\n",
        "src/app.py": "c = make_client()\n",
    }, body="@also src/app.py")
    assert links(repo) == []  # the frame of src/app.py
    assert [d[3:] for d in manifest(repo)] == [["tests/conftest.py", 1]]  # the test file's own use, in the full diff


def test_a_few_candidates_are_all_offered_and_many_are_none(repo):
    story(repo, {
        "a.py": "def save_all():\n    return 1\n",
        "b.py": "def save_all():\n    return 2\n",
        "c.py": "x = save_all()\n",
        "d1.py": "def read_all():\n    return 1\n",
        "d2.py": "def read_all():\n    return 1\n",
        "d3.py": "def read_all():\n    return 1\n",
        "d4.py": "def read_all():\n    return 1\n",
        "e.py": "y = read_all()\n",
    })
    assert links(repo) == [("save_all", [("a.py", 1), ("b.py", 1)])]


def test_a_traced_name_keeps_its_trace_and_its_link(repo):
    story(repo, {"src/cache.py": CACHE, "app.py": "rows = load_rows(1)\n"}, front="traces:\n  rows: [load_rows]")
    page = repo.read("story.html")
    assert re.search(r'<span class="tr" data-tr="rows"><span class="n" data-d="0">load_rows</span></span>', page)


def test_a_word_mark_inside_a_name_keeps_the_link_on_both_pieces(repo):
    lib = "def load_rows_fast():\n    return 1\n\n\ndef load_rows_slow():\n    return 2\n"
    repo.commit({"lib.py": lib, "app.py": "x = load_rows_fast()\n"})
    repo.commit({"lib.py": lib + "\nZ = 1\n", "app.py": "x = load_rows_slow()\n"})
    repo.index()
    repo.story("@also lib.py\n\n@diff app.py#h1")
    repo.build()
    assert "".join(name for name, _ in links(repo)) == "load_rows_slow"
    assert {tuple(to) for _, to in links(repo)} == {(("lib.py", 5),)}
    assert "x = load_rows_slow()" in repo.read("story.txt")


def test_a_tour_links_into_the_files_it_shows(repo):
    repo.commit({"src/cache.py": CACHE, "app.py": "rows = load_rows(1)\nlast = other_thing(2)\n", "lib.py": "def other_thing(x):\n    return x\n"})
    repo.run("index", "--repo", repo.path, "--tour", "--out", repo.out)
    repo.story("@ctx app.py@head 1-2\n\n@ctx src/cache.py@head 1-3")
    repo.build()
    assert links(repo) == [("load_rows", [("src/cache.py", 6)])]
    assert opened(repo, "src/cache.py", 6)[2] == "def load_rows(path):"


def test_a_relative_import_names_the_file_beside_the_importer(repo):
    story(repo, {
        "pkg/cache.py": "def load_rows():\n    return 1\n",
        "other/cache.py": "def load_rows():\n    return 2\n",
        "other/conf.py": "def settings():\n    return 3\n",
        "pkg/app.py": "from .cache import load_rows\nfrom . import settings\n\nx = load_rows()\ny = settings()\n",
        "pkg/deep/app.py": "from ..cache import load_rows\n\nz = load_rows()\n",
    }, "@also pkg/app.py\n\n@also pkg/deep/app.py\n\n@also pkg/cache.py\n\n@also other/cache.py\n\n@also other/conf.py")
    assert links(repo) == [("load_rows", [("pkg/cache.py", 1)])] * 4


def test_an_alias_opens_what_it_was_imported_as(repo):
    story(repo, {
        "lib/models.py": "class Thing:\n    pass\n\n\nclass Base:\n    pass\n",
        "app.py": "from lib.models import Thing as Base\n\nz = Base()\n",
    }, "@also app.py\n\n@also lib/models.py")
    assert links(repo) == [("Thing", [("lib/models.py", 1)]), ("Base", [("lib/models.py", 1)])]


def test_a_keyword_argument_at_the_margin_is_not_a_constant(repo):
    story(repo, {"a.py": "rows = load(\nmax_rows=3,\n)\n", "b.py": "limit = max_rows\n"})
    assert links(repo) == []


def test_a_brace_on_its_own_line_opens_the_body(repo):
    story(repo, {
        "lib.php": "<?php\nfunction load_rows($a)\n{\n    return $a;\n}\n\nfunction other()\n{\n    return 1;\n}\n",
        "main.php": "<?php\n$x = load_rows(1);\n",
    })
    assert opened(repo, "lib.php", 2) == ["function load_rows($a)", "{", "    return $a;", "}"]


@pytest.mark.parametrize(
    "files, expected",
    [
        (
            {
                "lib/table.js": "export function parseRow(x) {\n  return x;\n}\nexport const MAX_ROWS = 5;\nexport class Table {\n  renderAll(a) {\n    return a;\n  }\n}\n",
                "main.js": 'import { parseRow, MAX_ROWS } from "./lib/table";\nimport { Table } from "left-pad";\nparseRow(MAX_ROWS);\nnew Table().renderAll(2);\n',
            },
            [("parseRow", "lib/table.js", 1), ("MAX_ROWS", "lib/table.js", 4), ("parseRow", "lib/table.js", 1),
             ("MAX_ROWS", "lib/table.js", 4), ("renderAll", "lib/table.js", 6)],
        ),
        (
            {
                "types.ts": "export interface RowOpts {\n  a: number;\n}\nexport type RowId = string;\n",
                "use.ts": "function f(o: RowOpts): RowId {\n  return '';\n}\n",
            },
            [("RowOpts", "types.ts", 1), ("RowId", "types.ts", 4)],
        ),
        (
            {
                "server.go": "package main\n\ntype Server struct {\n\ta int\n}\n\nfunc (s *Server) HandleCall(w int) int {\n\treturn parseAll(w)\n}\n\nfunc parseAll(w int) int {\n\treturn w\n}\n",
                "main.go": "package main\n\nfunc main() {\n\ts := Server{}\n\ts.HandleCall(1)\n}\n",
            },
            [("Server", "server.go", 3), ("parseAll", "server.go", 11), ("Server", "server.go", 3), ("HandleCall", "server.go", 7)],
        ),
        (
            {
                "lib/store.rb": "class Store\n  def self.make_all\n    1\n  end\nend\n",
                "main.rb": "Store.make_all\n",
            },
            [("Store", "lib/store.rb", 1), ("make_all", "lib/store.rb", 2)],
        ),
        (
            {
                "src/lib.rs": "pub struct Parser {\n    a: u8,\n}\n\npub fn parse_all(a: u8) -> u8 {\n    a\n}\n",
                "src/main.rs": "fn main() {\n    let p = Parser { a: parse_all(1) };\n}\n",
            },
            [("Parser", "src/lib.rs", 1), ("parse_all", "src/lib.rs", 5)],
        ),
    ],
    ids=["js", "ts", "go", "ruby", "rust"],
)
def test_definitions_are_found_in_other_languages(repo, files, expected):
    story(repo, files)
    assert [(name, *to[0]) for name, to in links(repo)] == expected


# ---- dbt ----

PROJECT = "name: shop\nmodel-paths: [models]\nmacro-paths: [macros]\n"
MONEY = "{# money #}\n{% macro cents_to_dollars(col) %}\n  ({{ col }} / 100)\n{% endmacro %}\n\n{% macro coalesce(a) %}\n  {{ a }}\n{% endmacro %}\n"
ORDERS = """\
SELECT
    {{ cents_to_dollars('amount') }} AS amount,
    {{ dbt_utils.star(ref('stg_orders')) }},
    coalesce(a, b) AS c
FROM {{ ref('stg_orders') }}
LEFT JOIN {{ ref('shop', 'stg_users') }} USING (id)
LEFT JOIN {{ ref(other) }} USING (id)
LEFT JOIN {{ source('raw', 'stg_orders') }} USING (id)
"""


def dbt(repo, extra=None, orders=ORDERS, body="@also models/orders.sql"):
    repo.commit({
        "dbt_project.yml": PROJECT, "macros/money.sql": MONEY, "models/orders.sql": "SELECT 1\n",
        "models/staging/stg_orders.sql": "SELECT *\nFROM raw.orders\n", "models/staging/stg_users.sql": "SELECT 1\n",
        **(extra or {}),
    })
    repo.commit({"models/orders.sql": orders})
    repo.index()
    repo.story(body)
    return repo.build()


def test_a_ref_opens_the_model_and_a_macro_call_its_macro(repo):
    dbt(repo)
    assert links(repo) == [
        ("cents_to_dollars", [("macros/money.sql", 2)]),
        ("'stg_orders'", [("models/staging/stg_orders.sql", 1)]),
        ("'stg_orders'", [("models/staging/stg_orders.sql", 1)]),
    ]
    assert opened(repo, "models/staging/stg_orders.sql", 1) == ["SELECT *", "FROM raw.orders"]
    assert opened(repo, "macros/money.sql", 2) == ["{% macro cents_to_dollars(col) %}", "  ({{ col }} / 100)", "{% endmacro %}"]
    # the change's own file first, then what it leads to
    assert [len(s["rows"]) for s in sources(repo)] == [9, 8, 2]


def test_sql_outside_a_dbt_project_links_nothing(repo):
    repo.commit({"models/orders.sql": "SELECT 1\n", "models/stg_orders.sql": "SELECT 2\n"})
    repo.commit({"models/orders.sql": ORDERS})
    repo.index()
    repo.story("@also models/orders.sql")
    repo.build()
    assert links(repo) == [] and len(sources(repo)) == 1


def test_two_models_of_one_name_link_neither(repo):
    dbt(repo, {"models/other/stg_orders.sql": "SELECT 3\n"})
    assert [name for name, _ in links(repo)] == ["cents_to_dollars"]


def test_a_model_the_story_already_shows_is_packed_once(repo):
    dbt(repo, body="@also models/orders.sql\n\n@ctx models/staging/stg_orders.sql@head 1-2")
    assert ("'stg_orders'", [("models/staging/stg_orders.sql", 1)]) in links(repo)
    assert [len(s["rows"]) for s in sources(repo)] == [9, 2, 8]


def test_a_packed_model_links_no_further_than_the_page(repo):
    dbt(repo, {"models/staging/stg_orders.sql": "SELECT * FROM {{ ref('stg_users') }}\nJOIN {{ ref('orders') }}\n"})
    assert len(sources(repo)) == 3  # stg_users stays out: only the packed model names it
    assert [d[3] for d in manifest(repo)] == ["macros/money.sql", "models/staging/stg_orders.sql", "models/orders.sql"]


def test_models_past_the_budget_stay_out_and_the_build_says_so(repo):
    big = {f"models/big_{n}.sql": "SELECT 1\n" * 590 for n in range(1, 7)}
    huge = {"models/huge.sql": "SELECT 1\n" * 601}
    refs = "".join(f"SELECT * FROM {{{{ ref('big_{n}') }}}}\n" for n in range(2, 7))
    # big_1 is named only in a line the diff doesn't show: it gives way first
    old = "SELECT * FROM {{ ref('big_1') }}\n" + "-- pad\n" * 12 + "SELECT 0\n"
    new = old.replace("SELECT 0\n", refs + "SELECT * FROM {{ ref('huge') }}\n")
    repo.commit({"dbt_project.yml": PROJECT, "models/orders.sql": old, **big, **huge})
    repo.commit({"models/orders.sql": new})
    repo.index()
    repo.story("@also models/orders.sql")
    out = repo.build().stdout
    assert [name for name, _ in links(repo)] == [f"'big_{n}'" for n in range(2, 7)]
    assert len(sources(repo)) == 6
    assert "note: definitions: packed 5 dbt files from outside the change (2950 rows); 2 more" in out
    assert out.rstrip().split("open nothing: ")[1].split("\n")[0] == "huge, big_1"


def test_a_macro_call_can_span_lines(repo):
    dbt(repo, orders="SELECT\n    {{\n        cents_to_dollars(\n            'amount'\n        )\n    }} AS amount,\n    coalesce(a, b) AS c\nFROM {{ ref('stg_orders') }}\n")
    assert [name for name, _ in links(repo)] == ["cents_to_dollars", "'stg_orders'"]


def test_models_can_sit_at_the_project_root(repo):
    repo.commit({"dbt_project.yml": "name: shop\nmodel-paths: ['.']\n", "orders.sql": "SELECT 1\n", "stg_orders.sql": "SELECT 2\n"})
    repo.commit({"orders.sql": "SELECT * FROM {{ ref('stg_orders') }}\n"})
    repo.index()
    repo.story("@also orders.sql")
    repo.build()
    assert links(repo) == [("'stg_orders'", [("stg_orders.sql", 1)])]


def test_what_the_story_shows_is_packed_before_what_only_the_full_diff_does(repo):
    big = {f"models/big_{n}.sql": "SELECT 1\n" * 590 for n in range(1, 7)}
    refs = "".join(f"SELECT * FROM {{{{ ref('big_{n}') }}}}\n" * 2 for n in range(2, 7))
    repo.commit({"dbt_project.yml": PROJECT, "models/orders.sql": "SELECT 0\n", "models/aside.sql": "SELECT 0\n", **big})
    repo.commit({"models/orders.sql": "SELECT * FROM {{ ref('big_1') }}\n", "models/aside.sql": refs})
    repo.index()
    repo.story("@also models/orders.sql", front="exclude:\n  - path: models/aside.sql\n    reason: shown elsewhere")
    out = repo.build().stdout
    assert links(repo) == [("'big_1'", [("models/big_1.sql", 1)])]
    assert out.rstrip().split("open nothing: ")[1].split("\n")[0] == "big_6"
