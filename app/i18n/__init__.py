"""Lightweight internationalisation for the web UI.

Templates call ``_('English text')``; JavaScript calls ``Scarlet.t('English text')`` with the
same catalogue injected in the page. English is the source language, Italian the default
locale (``SCARLET_DEFAULT_LOCALE``). Unknown strings fall back to the English text, so partial
catalogues never break the UI. Translations are trusted static strings and may contain markup.
"""

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any

from flask import Flask, has_request_context, request, session
from markupsafe import Markup

from app.i18n.it import IT

SUPPORTED_LOCALES: dict[str, dict[str, str]] = {
    "it": {"name": "Italiano", "flag": "🇮🇹"},
    "en": {"name": "English", "flag": "🇬🇧"},
}
CATALOGUES: dict[str, dict[str, str]] = {"it": IT, "en": {}}
COOKIE = "scarlet_lang"


def get_locale() -> str:
    """Resolve the active locale: explicit choice, then browser preference, then default.

    Deliberately not cached on ``g``: an application context can outlive a single request
    (tests, CLI, Celery), and a stale cache there would freeze the whole process on one
    language. Resolution is a handful of dict lookups.
    """
    from flask import current_app

    if not has_request_context():
        return "it"
    lang = session.get("lang") or request.cookies.get(COOKIE)
    if lang not in SUPPORTED_LOCALES and request.accept_languages:
        lang = request.accept_languages.best_match(list(SUPPORTED_LOCALES))
    if lang not in SUPPORTED_LOCALES:
        lang = current_app.config.get("SCARLET_DEFAULT_LOCALE")
    if lang not in SUPPORTED_LOCALES:
        lang = "it"
    return lang


def _return_to() -> str:
    """Where the language switcher sends the user back to.

    ``request.full_path`` appends a bare ``?`` when there is no query string, which would
    show up in the link and in the address bar after the redirect.
    """
    if not has_request_context():
        return "/"
    return request.full_path.rstrip("?") if request.query_string else request.path


def gettext(text: str, **kwargs: Any) -> Markup:
    catalogue = CATALOGUES.get(get_locale(), {})
    translated = catalogue.get(text, text)
    if kwargs:
        try:
            translated = translated.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return Markup(translated)


#: ``Scarlet.t("…")`` / ``t("…")`` in the bundled scripts, either quoting style.
_JS_CALL = re.compile(r"""(?<![\w.$])(?:S\.)?t\(\s*(?:'([^']*)'|"([^"]*)")""")


@lru_cache(maxsize=1)
def _js_keys() -> frozenset[str]:
    """Strings the browser can ask for, so a page embeds a few KB instead of the whole catalogue.

    Two sources: literal ``t('…')`` calls found in the bundled scripts, and every SHOUTY key
    (``RUNNING``, ``ROLLED BACK``, …), because badge labels are built at runtime from API
    values rather than from a literal. Anything missed still renders, in English, since
    ``Scarlet.t`` falls back to the key itself.
    """
    keys = {key for key in CATALOGUES["it"] if key == key.upper()}
    for path in (Path(__file__).resolve().parents[1] / "static" / "js").rglob("*.js"):
        for match in _JS_CALL.finditer(path.read_text(encoding="utf-8")):
            keys.add(match.group(1) if match.group(1) is not None else match.group(2))
    return frozenset(keys)


def js_catalogue() -> dict[str, str]:
    catalogue = CATALOGUES.get(get_locale(), {})
    return {key: value for key, value in catalogue.items() if key in _js_keys()}


def register_i18n(app: Flask) -> None:
    app.config.setdefault("SCARLET_DEFAULT_LOCALE", "it")
    app.jinja_env.globals["_"] = gettext
    app.jinja_env.filters["tr"] = lambda text: gettext(str(text))

    @app.context_processor
    def _inject() -> dict[str, Any]:
        return {
            "current_locale": get_locale(),
            "supported_locales": SUPPORTED_LOCALES,
            "js_translations": js_catalogue(),
            "nav_return_to": _return_to(),
        }

    @app.after_request
    def _content_language(response):
        try:
            response.headers.setdefault("Content-Language", get_locale())
        except RuntimeError:
            pass
        return response
