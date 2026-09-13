"""Lightweight internationalisation for the web UI.

Templates call ``_('English text')``; JavaScript calls ``Scarlet.t('English text')`` with the
same catalogue injected in the page. English is the source language, Italian the default
locale (``SCARLET_DEFAULT_LOCALE``). Unknown strings fall back to the English text, so partial
catalogues never break the UI. Translations are trusted static strings and may contain markup.
"""

from __future__ import annotations

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


def gettext(text: str, **kwargs: Any) -> Markup:
    catalogue = CATALOGUES.get(get_locale(), {})
    translated = catalogue.get(text, text)
    if kwargs:
        try:
            translated = translated.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return Markup(translated)


def js_catalogue() -> dict[str, str]:
    return CATALOGUES.get(get_locale(), {})


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
        }

    @app.after_request
    def _content_language(response):
        try:
            response.headers.setdefault("Content-Language", get_locale())
        except RuntimeError:
            pass
        return response
