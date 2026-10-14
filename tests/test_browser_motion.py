"""Motion must preserve reading, keyboard focus and accessibility preferences."""
import os

import pytest
from test_browser_reading import reading_page
from test_browser_forms import origin, sign_in

pytestmark = pytest.mark.skipif(
    os.getenv("CRITICARD_BROWSER_TESTS") != "1", reason="Optional browser regressions"
)


@pytest.mark.parametrize("motion", ["no-preference", "reduce"])
def test_page_transition_preserves_reading_and_respects_motion_preference(reading_page, motion):
    from playwright.sync_api import expect
    page = reading_page
    page.emulate_media(reduced_motion=motion)
    card = page.locator("#card-1")
    card.locator(".read-review").click()
    card.locator("[data-expand-review]").click()
    dialog = page.locator("#review-dialog")
    text = dialog.locator("[data-reader-page]")
    original_page = text.text_content()
    dialog.locator("[data-page-next]").click()
    assert text.text_content() != original_page
    active = text.evaluate("node => node.getAnimations().filter(a => a.playState === 'running').length")
    assert active == (0 if motion == "reduce" else 1)
    assert text.evaluate("node => node.scrollHeight <= node.clientHeight + 1")
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(card.locator("[data-expand-review]")).to_be_focused()


def test_changing_motion_preference_cancels_transition(reading_page):
    page = reading_page
    page.emulate_media(reduced_motion="no-preference")
    card = page.locator("#card-1")
    card.locator(".read-review").click()
    text = card.locator("[data-reader-page]")
    card.locator("[data-page-next]").click()
    expected_text = text.text_content()
    assert text.evaluate("node => node.getAnimations().length") > 0
    page.emulate_media(reduced_motion="reduce")
    page.wait_for_function("() => document.querySelector('#card-1 [data-reader-page]').getAnimations().length === 0")
    assert text.text_content() == expected_text
    assert text.evaluate("node => node.scrollHeight <= node.clientHeight + 1")


def test_mobile_draft_preview_stays_centered_with_reduced_motion(reading_page):
    from playwright.sync_api import expect

    page = reading_page
    page.set_viewport_size({"width": 390, "height": 844})
    page.emulate_media(reduced_motion="reduce")
    sign_in(page)
    page.goto(origin(page) + "/cadastro_cards")
    trigger = page.locator("[data-open-draft]")
    expect(trigger).to_be_visible()
    bounds = trigger.bounding_box()
    assert 0 <= bounds["x"] and bounds["x"] + bounds["width"] <= 390
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    trigger.click()
    expect(page.locator(".draft-preview-dialog")).to_be_visible()
    page.keyboard.press("Escape")
    expect(page.locator(".draft-preview-dialog")).not_to_be_visible()
    expect(trigger).to_be_focused()
