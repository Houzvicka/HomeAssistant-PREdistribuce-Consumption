r"""PortalClient: talks to the PREdistribuce customer portal.

Endpoint captured from a real browser session (HAR analysis, 2026-09-08):

    POST https://www.predistribuce.cz/cs/muj-ucet/profily-spotreby/
    Content-Type: application/x-www-form-urlencoded

    eans_to_export[]=<EAN>
    cinna[]=<EAN>
    induktivni[]=<EAN>
    kapacitni[]=<EAN>
    cumulative2=on
    export_CSV=Exportovat CSV
    _form_=exportCSVForm
    date_from=DD.MM.YYYY
    date_to=DD.MM.YYYY
    id_formation=

Response: Content-Disposition attachment, filename "Profily_spotreby_DD.MM.YYYY.csv",
Content-Type application/vnd.ms-excel (mislabeled — body is actually the
semicolon-delimited, ISO-8859-2, Czech-date CSV format documented in parser.py).

Login endpoint (HAR analysis, 2026-09-08, second capture):

    POST https://www.predistribuce.cz/cs/muj-ucet/prihlaseni-uzivatele/
    Content-Type: application/x-www-form-urlencoded

    alias=<username/email>
    password=<password>
    login=Přihlásit
    recaptcha_response=
    _form_=PREdi\ClientPortal\LogIn\LogIn::createLogInForm
    redirect=

No CSRF field in the form. Success is a 302 redirect to /cs/muj-ucet/ (an
http:// Location that the server then bounces to https:// — two redirect
hops, both followed transparently by `requests`).

Auth is the `PHPSESSID` cookie (confirmed via DevTools -> Application ->
Cookies, since both HAR exports strip cookies entirely). Two F5 BIG-IP WAF
persistence cookies, `TS0117fb81` and `TSe...`, ride along too and are
probably also required. All three show Expires/Max-Age = "Session" — no
explicit lifetime, just however long PHP's server-side idle timeout is
(unmeasured). That's a browser concept anyway; `requests.Session()` just
holds them in memory for the life of the process, which is what matters
here — login() gets called fresh at the start of every run rather than
persisting a session across runs, so none of this needs to be tracked.

Caveat: there's a `recaptcha_response` field. It was empty in the captured
login and still succeeded, suggesting either an invisible/score-based
reCAPTCHA v3 that isn't always enforced, or it simply wasn't triggered for
that session/browser. A plain `requests` client can't solve a real
challenge if one shows up — if login() starts failing where it used to
work, this is the first thing to suspect, and the fix is a headless-browser
client (Playwright) instead of raw HTTP.
"""
from __future__ import annotations

import datetime
import requests

BASE_URL = "https://www.predistribuce.cz"
LOGIN_PATH = "/cs/muj-ucet/prihlaseni-uzivatele/"
EXPORT_PATH = "/cs/muj-ucet/profily-spotreby/"

# Common browser headers the portal's WAF/bot-detection may expect.
# Trimmed from the captured request; User-Agent matters most in practice.
DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,image/apng,*/*;q=0.8"
    ),
    "Origin": BASE_URL,
}


NO_DATA_MARKER = "nejsou dostupná žádná data"  # "no data available for this report"


class PortalError(RuntimeError):
    pass


class NoDataError(PortalError):
    """The portal has no data for the requested range.

    Confirmed 2026-09-15 by probing the live account: a range entirely
    before the account's data history (e.g. before the meter's activation
    date) returns the normal HTML page with a
    `<div class="flash error">...nejsou dostupná žádná data.</div>` banner,
    not an attachment — a different failure shape than an auth problem, and
    an expected/benign one the coordinator should just skip past rather than
    treat as an error worth alerting on.
    """


class PortalClient:
    def __init__(self, session: requests.Session | None = None):
        self.session = session or requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)

    def login(self, username: str, password: str) -> None:
        """Authenticate against the portal; the session then holds the cookie.

        Raises PortalError if the portal bounces back to the login page
        instead of redirecting to the account dashboard (bad credentials, or
        a reCAPTCHA challenge — see module docstring caveat).
        """
        login_url = BASE_URL + LOGIN_PATH
        # Prime whatever cookie the server sets on the plain page load, same
        # as a real browser would before ever submitting the form.
        self.session.get(login_url, timeout=30)

        payload = {
            "alias": username,
            "password": password,
            "login": "Přihlásit",
            "recaptcha_response": "",
            "_form_": "PREdi\\ClientPortal\\LogIn\\LogIn::createLogInForm",
            "redirect": "",
        }
        resp = self.session.post(
            login_url,
            data=payload,
            headers={"Referer": login_url},
            timeout=30,
        )
        resp.raise_for_status()

        if LOGIN_PATH in resp.url:
            raise PortalError(
                "login failed — still on the login page after submitting "
                "credentials (bad alias/password, or a reCAPTCHA challenge "
                "blocked it)"
            )

    def seed_session_cookie(self, name: str, value: str) -> None:
        """Manually inject a session cookie captured from a live browser login.

        Fallback for testing download_export() when login() itself is blocked
        (e.g. by a reCAPTCHA challenge — see module docstring caveat). Get the
        value from DevTools -> Application -> Cookies (not the Network tab /
        HAR export, which strips it), while logged in at predistribuce.cz.
        """
        self.session.cookies.set(name, value, domain="www.predistribuce.cz")

    def download_export(
        self,
        ean: str,
        date_from: datetime.date,
        date_to: datetime.date,
    ) -> bytes:
        """Download the CSV export for one EAN and date range (inclusive).

        Returns the raw response bytes (ISO-8859-2 encoded) — hand these to
        parser.parse().

        Note: a range including *today* returns a real attachment, but every
        row for today is zero-filled placeholder (kwh=0.0, kw=0.0) — the
        portal has a full-day lag, confirmed 2026-09-15 by comparing today's
        export against actual consumption. Callers should never request
        today; cap date_to at yesterday.
        """
        payload = {
            "eans_to_export[]": ean,
            "cinna[]": ean,
            "induktivni[]": ean,
            "kapacitni[]": ean,
            "cumulative2": "on",
            "export_CSV": "Exportovat CSV",
            "_form_": "exportCSVForm",
            "date_from": date_from.strftime("%d.%m.%Y"),
            "date_to": date_to.strftime("%d.%m.%Y"),
            "id_formation": "",
        }
        resp = self.session.post(
            BASE_URL + EXPORT_PATH,
            data=payload,
            headers={"Referer": BASE_URL + EXPORT_PATH},
            timeout=30,
        )
        resp.raise_for_status()

        content_type = resp.headers.get("Content-Type", "")
        disposition = resp.headers.get("Content-Disposition", "")
        if "attachment" not in disposition:
            if NO_DATA_MARKER in resp.text:
                raise NoDataError(
                    f"no data available for {date_from} to {date_to} — "
                    "likely before this account's history begins"
                )
            # Anything else with no attachment is unexpected — most likely
            # the session cookie is missing/expired and the portal returned
            # the login page instead of a file.
            raise PortalError(
                "export did not return a file attachment — session likely "
                f"not authenticated (content-type={content_type!r}, "
                f"disposition={disposition!r})"
            )
        return resp.content
