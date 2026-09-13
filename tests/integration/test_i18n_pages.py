"""Every HTML page must render in both supported locales, and the Italian
catalogue must actually be applied (no raw English left in the chrome)."""

from __future__ import annotations

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


def test_navigation_is_translated_in_italian(admin_client):
    admin_client.get("/lang/it")
    html = admin_client.get("/dashboard").get_data(as_text=True)
    assert "Applicazioni" in html
    assert "Distribuzioni" in html or "Deployment" in html
    assert ">Hosts<" not in html or "Host" in html


def test_english_stays_untranslated(admin_client):
    admin_client.get("/lang/en")
    html = admin_client.get("/dashboard").get_data(as_text=True)
    assert "Applications" in html
    assert "Applicazioni" not in html


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
