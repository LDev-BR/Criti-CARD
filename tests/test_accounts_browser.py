"""Real browser recovery and explicit verification, including no-JS forms."""
import os
from pathlib import Path

import pytest

from conftest import rows
from test_accounts import links
from test_browser_forms import origin
from test_browser_reading import reading_page as accounts_page

pytestmark = pytest.mark.skipif(os.getenv("CRITICARD_BROWSER_TESTS") != "1", reason="Optional browser regressions")


def configure_local_mail(app, tmp_path, base):
    app.config.update(ACCOUNT_MAIL_BACKEND="file", ACCOUNT_BASE_URL=base,
                      ACCOUNT_OUTBOX_PATH=str(tmp_path / "outbox"), ACCOUNT_MAIL_FROM="no-reply@criticard.test")


def screenshot(page, name):
    destination = os.getenv("CRITICARD_ACCOUNTS_SCREENSHOTS")
    if destination:
        page.screenshot(path=str(Path(destination) / (name + ".png")), full_page=False)


def test_recovery_password_reveal_verification_and_mobile(accounts_page, app, tmp_path):
    page = accounts_page
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    configure_local_mail(app, tmp_path, origin(page))
    page.goto(origin(page) + "/recuperar-senha")
    assert "Recuperar senha" in page.title()
    screenshot(page, "forgot-desktop")
    page.locator("#email").fill("alice@example.com")
    page.locator(".form-submit").click()
    page.locator(".accounts-notice").wait_for()
    path = links(app)[0]
    page.goto(origin(page) + path)
    assert rows(app, "SELECT used_at FROM account_tokens WHERE purpose='reset'")[0][0] is None
    page.locator("#senha").fill("Different2!")
    page.locator("[data-password-toggle]").click()
    assert page.locator("#senha").get_attribute("type") == "text"
    page.locator("[data-password-toggle]").click()
    page.locator("#senha_confirmacao").fill("Different2!")
    screenshot(page, "reset-desktop")
    page.locator(".form-submit").click()
    page.wait_for_url(origin(page) + "/")
    page.locator("#username").fill("alice@example.com")
    page.locator("#senha").fill("Different2!")
    page.locator(".form-submit").click()
    page.wait_for_url("**/dashboard")
    page.locator('form[action$="/reenviar-verificacao"] button').click()
    page.locator(".accounts-notice").wait_for()
    verify_path = links(app, "verificar-email")[0]
    page.goto(origin(page) + verify_path)
    assert rows(app, "SELECT email_verified FROM usuarios WHERE id=1")[0][0] == 0
    page.locator(".form-submit").click()
    page.locator(".accounts-notice").wait_for()
    assert rows(app, "SELECT email_verified FROM usuarios WHERE id=1")[0][0] == 1
    page.set_viewport_size({"width": 390, "height": 844})
    page.goto(origin(page) + "/recuperar-senha")
    assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
    screenshot(page, "forgot-mobile")
    assert not errors


def test_recovery_and_confirmation_without_javascript(accounts_page, app, tmp_path):
    page = accounts_page.context.browser.new_page(java_script_enabled=False, viewport={"width": 375, "height": 812})
    try:
        configure_local_mail(app, tmp_path, origin(accounts_page))
        page.goto(origin(accounts_page) + "/recuperar-senha")
        page.locator("#email").fill("alice@example.com")
        page.locator(".form-submit").click()
        page.locator(".accounts-notice").wait_for()
        path = links(app)[0]
        page.goto(origin(accounts_page) + path)
        assert not page.locator("[data-password-toggle]").is_visible()
        page.locator("#senha").fill("Different2!")
        page.locator("#senha_confirmacao").fill("Different3!")
        page.locator(".form-submit").click()
        page.locator("#senha_confirmacao-error").wait_for()
        assert rows(app, "SELECT used_at FROM account_tokens WHERE purpose='reset'")[0][0] is None
        page.locator("#senha").fill("Different2!")
        page.locator("#senha_confirmacao").fill("Different2!")
        page.locator(".form-submit").click()
        page.wait_for_url(origin(accounts_page) + "/")
        assert rows(app, "SELECT session_version FROM usuarios WHERE id=1")[0][0] == 1
    finally:
        page.close()
