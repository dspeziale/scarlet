"""Every HTML page must render in both supported locales, and the Italian
catalogue must actually be applied (no raw English left in the chrome)."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.i18n import CATALOGUES, SUPPORTED_LOCALES


def _page_rules(app) -> list[str]:
    """All parameterless GET routes served by the HTML blueprints."""
    rules = []
    for rule in app.url_map.iter_rules():
        if rule.arguments or "GET" not in rule.methods:
            continue
        if not rule.endpoint.startswith("web."):
            continue
        if rule.endpoint.startswith("web_auth."):
            continue  # login/logout redirect for an authenticated client
        rules.append(str(rule))
    return sorted(rules)


def test_all_pages_render_in_every_locale(app, admin_client):
    pages = _page_rules(app)
    assert len(pages) > 15, pages
    for locale in SUPPORTED_LOCALES:
        assert admin_client.get(f"/lang/{locale}").status_code in (301, 302)
        for path in pages:
            response = admin_client.get(path)
            assert response.status_code == 200, f"{path} in {locale}: {response.status_code}"
            if not response.mimetype.startswith("text/html"):
                continue  # /healthz and friends answer JSON
            if path == "/guida":
                continue  # the user guide is an Italian-only document
            assert f'lang="{locale}"' in response.get_data(
                as_text=True
            ), f"{path} missing lang {locale}"


def test_unknown_locale_is_rejected(admin_client):
    assert admin_client.get("/lang/de").status_code == 404


def test_language_selector_is_available_before_login(client):
    html = client.get("/login").get_data(as_text=True)
    for code in SUPPORTED_LOCALES:
        assert f"/lang/{code}" in html


def _sidebar_labels(html: str) -> list[str]:
    """Menu entries as rendered, so the assertion cannot be satisfied by the embedded catalogue."""
    import re

    aside = html[html.index("<aside") : html.index("</aside>")]
    return [
        re.sub(r"<[^>]+>", "", label).strip() for label in re.findall(r"<p>(.*?)</p>", aside, re.S)
    ]


def test_navigation_is_translated_in_italian(admin_client):
    admin_client.get("/lang/it")
    labels = _sidebar_labels(admin_client.get("/dashboard").get_data(as_text=True))
    assert "Applicazioni" in labels
    assert "Cruscotto" in labels
    assert "Applications" not in labels


def test_english_stays_untranslated(admin_client):
    admin_client.get("/lang/en")
    labels = _sidebar_labels(admin_client.get("/dashboard").get_data(as_text=True))
    assert "Applications" in labels
    assert "Applicazioni" not in labels


@pytest.mark.parametrize("key", ["Hosts", "Applications", "Deployments", "Settings", "Sign in"])
def test_core_terms_are_in_the_catalogue(key):
    assert key in CATALOGUES["it"] and CATALOGUES["it"][key]


def _ui_strings() -> set[str]:
    """Every string the UI asks the catalogue for: ``_('…')`` in Jinja, ``S.t('…')`` in JS."""
    import glob
    import re
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    keys: set[str] = set()
    jinja = re.compile(r"_\(\s*(['\"])((?:(?!\1).)*?)\1\s*\)", re.S)
    for path in glob.glob(str(root / "app" / "templates" / "**" / "*.html"), recursive=True):
        if "help/guida" in path.replace("\\", "/"):
            continue  # standalone Italian document, nothing to translate
        for match in jinja.finditer(Path(path).read_text(encoding="utf-8")):
            keys.add(match.group(2))
    js = re.compile(r"S\.t\(\s*(['\"])((?:(?!\1).)*?)\1")
    for path in glob.glob(str(root / "app" / "static" / "js" / "**" / "*.js"), recursive=True):
        for match in js.finditer(Path(path).read_text(encoding="utf-8")):
            keys.add(match.group(2))
    return {key for key in keys if key.strip()}


def test_italian_catalogue_covers_every_ui_string():
    missing = sorted(key for key in _ui_strings() if key not in CATALOGUES["it"])
    assert not missing, f"{len(missing)} strings have no Italian translation: {missing[:10]}"


def test_catalogue_has_no_empty_translations():
    empty = sorted(key for key, value in CATALOGUES["it"].items() if not value.strip())
    assert not empty, empty


def test_injected_catalogue_covers_every_javascript_call(app):
    """The page only embeds the browser's subset, so that subset must be complete."""
    from app.i18n import _JS_CALL, CATALOGUES, js_catalogue

    with app.test_request_context("/", headers={"Cookie": "scarlet_lang=it"}):
        injected = js_catalogue()
    assert injected, "no catalogue injected for Italian"

    root = Path(__file__).resolve().parents[2] / "app" / "static" / "js"
    for path in root.rglob("*.js"):
        for match in _JS_CALL.finditer(path.read_text(encoding="utf-8")):
            key = match.group(1) if match.group(1) is not None else match.group(2)
            if key in CATALOGUES["it"]:
                assert key in injected, f"{path.name} asks for {key!r}, not injected"


def test_injected_catalogue_is_smaller_than_the_full_one(app):
    from app.i18n import CATALOGUES, js_catalogue

    with app.test_request_context("/"):
        assert len(js_catalogue()) < len(CATALOGUES["it"])


def test_catalogue_defines_each_key_once():
    """A repeated key silently shadows the earlier translation, so ban duplicates."""
    import re
    from collections import Counter

    source = (Path(__file__).resolve().parents[2] / "app" / "i18n" / "it.py").read_text(
        encoding="utf-8"
    )
    entry = re.compile(r"^\s{4}((['\"])(?:(?!\2).)*?\2):", re.M)
    counts = Counter(match.group(1) for match in entry.finditer(source))
    assert not [key for key, n in counts.items() if n > 1]


def test_switching_language_returns_to_the_current_page(admin_client):
    response = admin_client.get("/lang/en?next=%2Fhosts%3Fenvironment%3DDEV")
    assert response.status_code in (301, 302)
    assert response.headers["Location"] == "/hosts?environment=DEV"


def test_switching_language_refuses_an_external_return_url(admin_client):
    response = admin_client.get("/lang/en?next=https%3A%2F%2Fevil.example%2Fx")
    assert response.headers["Location"] == "/"
    assert admin_client.get("/lang/en?next=%2F%2Fevil.example").headers["Location"] == "/"


def test_language_link_has_no_trailing_question_mark(admin_client):
    html = admin_client.get("/dashboard").get_data(as_text=True)
    assert "/lang/en?next=/dashboard?" not in html, "bare '?' leaks from request.full_path"
    assert "/lang/en?next=/dashboard" in html


def test_copyright_is_shown_on_every_page(admin_client, client):
    """The notice must reach the console, the login page and the standalone guide."""
    from app import __copyright__

    assert __copyright__ == "© 2024-26 DS Consulting"
    assert __copyright__ in client.get("/login").get_data(as_text=True)
    for path in ("/dashboard", "/system/about", "/guida"):
        assert __copyright__ in admin_client.get(path).get_data(as_text=True), path


def test_pdf_manuals_carry_the_same_copyright():
    """The manuals are built by a separate script: keep the two constants from drifting."""
    import sys

    from app import __copyright__

    scripts = Path(__file__).resolve().parents[2] / "scripts"
    sys.path.insert(0, str(scripts))
    try:
        import pdflib
    except ImportError:  # reportlab è una dipendenza di sviluppo
        pytest.skip("reportlab non installato")
    finally:
        sys.path.remove(str(scripts))
    assert __copyright__ == pdflib.COPYRIGHT
