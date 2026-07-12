"""Shared LinkedIn session/login handling.

`recruiter_finder.py`, `outreach.py`, and `linkedin_source.py` all hit the same
LinkedIn auth wall: load saved cookies into the browser context, navigate to a
target URL, and if LinkedIn redirects to a login/authwall/signup page, either
auto-fill LINKEDIN_EMAIL/LINKEDIN_PASSWORD (from .env) or pause for the human
to log in manually (handles 2FA/CAPTCHA), then persist cookies for next time.

This module owns that one flow so it isn't duplicated across callers.
"""
import json
import os
import pathlib
import sys

COOKIES_PATH = pathlib.Path(__file__).parent / ".linkedin_cookies.json"

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0 Safari/537.36"
)

_AUTHWALL_MARKERS = ["login", "authwall", "signup"]
_CHECKPOINT_MARKERS = ["checkpoint", "challenge", "login", "authwall"]


async def _perform_login(page, context, interactive=True):
    """Log in on `page` (auto-fill or manual pause), then persist cookies.

    `interactive=False` (used by unattended/automated callers such as
    `linkedin_source.fetch_linkedin`) skips every `input()` pause: it still
    tries auto-fill when credentials are present, but if that doesn't clear
    the checkpoint/authwall it returns immediately instead of blocking on
    stdin forever with no human present. Cookies are only persisted when a
    login attempt actually completed (auto-fill ran, or a human pressed
    Enter) — not on a bare non-interactive bail-out.
    """
    email = os.getenv("LINKEDIN_EMAIL")
    password = os.getenv("LINKEDIN_PASSWORD")

    if email and password:
        print("Auto-filling LinkedIn login...", file=sys.stderr)
        await page.goto("https://www.linkedin.com/login", wait_until="load", timeout=30000)
        email_sel = 'input#username, input[name="session_key"], input[autocomplete="username"]'
        pass_sel  = 'input#password, input[name="session_password"], input[autocomplete="current-password"]'
        await page.wait_for_selector(email_sel, state="attached", timeout=15000)
        await page.fill(email_sel, email, force=True)
        await page.fill(pass_sel, password, force=True)
        await page.click('button[type="submit"]')
        await page.wait_for_timeout(4000)

        if any(x in page.url for x in _CHECKPOINT_MARKERS):
            if not interactive:
                print(
                    "LinkedIn triggered a verification step (2FA/CAPTCHA) and "
                    "no human is attached (interactive=False) — bailing out, no retry.",
                    file=sys.stderr,
                )
                return
            print(
                "LinkedIn triggered a verification step (2FA/CAPTCHA).\n"
                "Complete it in the browser window, then press Enter...",
                file=sys.stderr,
            )
            input()
    else:
        if not interactive:
            print(
                "LinkedIn requires login and no credentials/cookies are available "
                "(interactive=False) — bailing out, no retry.",
                file=sys.stderr,
            )
            return
        print(
            "LinkedIn requires login. A browser window is open.\n"
            "Log in, then press Enter here to continue...\n"
            "Tip: add LINKEDIN_EMAIL and LINKEDIN_PASSWORD to .env for auto-login.",
            file=sys.stderr,
        )
        input()

    COOKIES_PATH.write_text(json.dumps(await context.cookies()))
    print("Cookies saved.", file=sys.stderr)


async def get_authenticated_page(context, target_url, interactive=True):
    """Return a Page navigated to `target_url`, handling LinkedIn's login flow.

    Loads saved cookies (if any) into `context`, opens a new page, and
    navigates to `target_url`. If LinkedIn redirects to a login/authwall/
    signup page, logs in (auto-fill or manual pause via `_perform_login`) and
    re-navigates to `target_url` before returning.

    `interactive=False` disables every manual/`input()` fallback (see
    `_perform_login`) — the returned page may still be sitting on a
    checkpoint/authwall URL if login didn't fully succeed; callers that pass
    `interactive=False` are expected to check `is_checkpoint_url(page.url)`
    themselves and abort rather than proceed.
    """
    if COOKIES_PATH.exists():
        await context.add_cookies(json.loads(COOKIES_PATH.read_text()))

    page = await context.new_page()
    await page.goto(target_url, wait_until="networkidle", timeout=45000)

    if any(x in page.url for x in _AUTHWALL_MARKERS):
        await _perform_login(page, context, interactive=interactive)
        await page.goto(target_url, wait_until="networkidle", timeout=45000)

    return page


def is_checkpoint_url(url):
    """True if `url` looks like a LinkedIn checkpoint/CAPTCHA/login-wall redirect."""
    return any(x in url for x in _CHECKPOINT_MARKERS)
