"""The page in a browser, beyond what the engine's tests can see."""
from conftest import LINES


def test_a_story_opens_without_errors(changed, story_page):
    changed.story("@diff app.py#h1 id=one\n@diff app.py#h2 id=two")
    changed.build()
    page = story_page(changed)
    assert page.locator(".progress .p-txt").inner_text() == "0/2 reviewed"
    assert page.locator("figure.frame").count() == 2
