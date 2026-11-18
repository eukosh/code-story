"""A click on a name opens a panel; only the panel's chip, alt-click or the Trace menu start a trace (D45)."""
import pytest

from conftest import Repo

LIB = "MAX_ROWS = 10\n\n\ndef load_rows(n):\n    return n\n"
APP = "from src.lib import load_rows\n\nrows = load_rows(MAX_ROWS)\nlimit = max_rows_seen + 1\n"


@pytest.fixture(scope="module")
def built(tmp_path_factory, git_template):
    """The one story every test here opens: none of them changes it."""
    repo = Repo(tmp_path_factory.mktemp("click"), git_template)
    repo.commit({"README.md": "start\n"})
    repo.commit({"src/lib.py": LIB, "app.py": APP})
    repo.index()
    repo.story("@also src/lib.py\n\n@diff app.py#h1 id=use", front="traces:\n  rows: [load_rows, max_rows_seen]")
    repo.build()
    return repo


@pytest.fixture
def page(built, story_page):
    return story_page(built)


def tracing(page):
    return "tracing" in (page.locator("body").get_attribute("class") or "").split()


def open_def(page, name):
    """Clicks a linked name in the frame and waits for its definition: the panel loads it from the page's sources."""
    page.locator(f'#use .row [data-d]:text-is("{name}")').last.click()
    page.wait_for_selector("#def:not([hidden]):not(.compact)")


def chip(page):
    c = page.locator("#def .def-tr")
    return {"shown": c.is_visible(), "text": c.inner_text() if c.is_visible() else "", "pressed": c.get_attribute("aria-pressed")}


def test_a_click_opens_the_definition_and_starts_no_trace(page):
    open_def(page, "load_rows")
    assert "def load_rows(n):" in page.locator("#def .def-body").inner_text()
    assert not tracing(page)
    assert chip(page) == {"shown": True, "text": "Trace rows · 2 snippets", "pressed": "false"}


def test_a_name_with_no_trace_has_no_chip(page):
    open_def(page, "MAX_ROWS")
    assert not chip(page)["shown"]


def test_the_chip_starts_and_stops_the_trace_and_the_definition_stays(page):
    open_def(page, "load_rows")
    page.locator("#def .def-tr").click()
    assert tracing(page) and chip(page) == {"shown": True, "text": "Stop tracing rows", "pressed": "true"}
    assert page.locator("#def").is_visible()
    assert page.locator(".tracepill .tp-count").inner_text() == "2 / 2"
    page.locator("#def .def-tr").click()
    assert not tracing(page) and chip(page)["pressed"] == "false"
    assert page.locator("#def").is_visible()


def test_a_traced_name_without_a_definition_opens_a_compact_panel(page):
    page.locator('#use .tr:has-text("max_rows_seen")').click()
    assert page.locator("#def.compact").is_visible()
    assert page.locator("#def .def-follows").inner_text() == "Part of the trace “rows”. Tracing lights up every snippet these names appear in: load_rows max_rows_seen"
    assert chip(page) == {"shown": True, "text": "Trace rows · 2 snippets", "pressed": "false"}
    assert not tracing(page)
    page.locator("#def .def-tr").click()
    assert tracing(page)
    assert page.locator("#def").is_hidden()


def test_alt_click_traces_at_once(page):
    page.locator('#use .row [data-d]:text-is("load_rows")').last.click(modifiers=["Alt"])
    assert tracing(page)
    assert page.locator("#def").is_hidden()


def test_while_tracing_a_click_on_a_traced_name_still_opens_the_panel(page):
    page.locator('#use .tr:has-text("max_rows_seen")').click(modifiers=["Alt"])
    assert tracing(page)
    page.locator('#use .tr:has-text("max_rows_seen")').click()
    assert tracing(page)
    assert page.locator("#def.compact").is_visible()
    assert chip(page)["pressed"] == "true"


def test_the_trace_menu_still_starts_a_trace(page):
    page.locator('[data-act="trace-menu"]').click()
    assert "alt" in page.locator("#trace-pop .pop-hint").inner_text()
    page.locator('#trace-pop button[data-tr="rows"]').click()
    assert tracing(page)
    assert page.locator('#trace-pop button[data-tr="rows"] .meta').inner_text() == "2 snippets"


def line_and_panel(page, name):
    return page.evaluate(f"""(() => {{
        const el = [...document.querySelectorAll('#use .tr')].find(x => x.textContent === {name!r});
        const r = el.closest('.row').getBoundingClientRect();
        const d = document.querySelector('#def').getBoundingClientRect();
        return {{top: r.top, bottom: r.bottom, x: el.getBoundingClientRect().left, dtop: d.top, dbottom: d.bottom, dleft: d.left}};
    }})()""")


def test_the_compact_panel_opens_at_the_clicked_name(page):
    page.locator('#use .tr:has-text("max_rows_seen")').click()
    at = line_and_panel(page, "max_rows_seen")
    assert 0 <= at["dtop"] - at["bottom"] <= 8
    assert abs(at["dleft"] - at["x"]) <= 16
    page.keyboard.press("Escape")
    # with no room below the line it opens above it
    page.set_viewport_size({"width": 1400, "height": int(at["bottom"]) + 40})
    page.locator('#use .tr:has-text("max_rows_seen")').click()
    at = line_and_panel(page, "max_rows_seen")
    assert 0 <= at["top"] - at["dbottom"] <= 8


def test_while_tracing_a_click_on_its_name_moves_the_stepper_there(page):
    page.locator('#use .tr:has-text("max_rows_seen")').click(modifiers=["Alt"])
    assert page.locator(".tracepill .tp-count").inner_text() == "2 / 2"
    page.locator(".tracepill [data-act=trace-prev]").click()
    assert page.locator(".tracepill .tp-count").inner_text() == "1 / 2"
    page.locator('#use .tr:has-text("max_rows_seen")').click()
    assert page.locator(".tracepill .tp-count").inner_text() == "2 / 2"
    assert page.locator("#use.current").count() == 1
    assert tracing(page)
