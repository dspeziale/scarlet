#!/usr/bin/env python3
"""One-off helper used while introducing i18n: translate page titles, macro labels and
server-side error titles. Kept in the repository so the transformation is reproducible."""

from __future__ import annotations

import glob
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

TITLES = [
    "Dashboard",
    "Hosts",
    "Host Groups",
    "Environments",
    "Applications",
    "Releases",
    "Packages",
    "Upload package",
    "Deployments",
    "New deployment",
    "Lifecycle Operations",
    "Jobs",
    "Health",
    "Logs",
    "Users",
    "Roles",
    "Credentials",
    "API tokens",
    "Audit Log",
    "Security Events",
    "Settings",
    "Notifications",
    "About",
    "Change password",
]

REPLACEMENTS = [
    (
        "{{ 'Edit host' if host else 'New host' }}",
        "{{ _('Edit host') if host else _('New host') }}",
    ),
    (
        "{{ 'Save changes' if host else 'Create host' }}",
        "{{ _('Save changes') if host else _('Create host') }}",
    ),
    (
        "{{ 'Edit ' ~ app.code if app else 'New application' }}",
        "{{ (_('Edit') ~ ' ' ~ app.code) if app else _('New application') }}",
    ),
    (
        "{{ 'Save changes' if app else 'Create application' }}",
        "{{ _('Save changes') if app else _('Create application') }}",
    ),
    ("{{ host.name if host else 'New' }}", "{{ host.name if host else _('New') }}"),
    ("{{ app.code if app else 'New' }}", "{{ app.code if app else _('New') }}"),
    (
        '<li class="breadcrumb-item active">Error {{ status }}</li>',
        "<li class=\"breadcrumb-item active\">{{ _('Error') }} {{ status }}</li>",
    ),
    ("<title>Sign in · SCARLET</title>", "<title>{{ _('Sign in') }} · SCARLET</title>"),
    (">{{ col.label }}{% if col.sort %}", ">{{ _(col.label) }}{% if col.sort %}"),
    ('data-role="empty" hidden>{{ empty }}<', 'data-role="empty" hidden>{{ _(empty) }}<'),
]


def main() -> None:
    pairs = list(REPLACEMENTS)
    for title in TITLES:
        pairs.append(
            (
                f"{{% block title %}}{title}{{% endblock %}}",
                f"{{% block title %}}{{{{ _('{title}') }}}}{{% endblock %}}",
            )
        )

    changed = 0
    for f in glob.glob(str(ROOT / "app" / "templates" / "**" / "*.html"), recursive=True):
        if "/help/" in f.replace("\\", "/"):
            continue
        path = Path(f)
        s = original = path.read_text(encoding="utf-8")
        for old, new in pairs:
            s = s.replace(old, new)
        if s != original:
            path.write_text(s, encoding="utf-8", newline="\n")
            changed += 1
    print(f"templates patched: {changed}")

    # server-side error titles / messages
    p = ROOT / "app" / "api" / "errors.py"
    s = p.read_text(encoding="utf-8")
    if "from app.i18n import gettext as _" not in s:
        s = s.replace(
            "from app.errors import AuthenticationError, RateLimitError, ScarletError",
            "from app.errors import AuthenticationError, RateLimitError, ScarletError\nfrom app.i18n import gettext as _",
        )
        s = s.replace(
            "def _title_for(status: int) -> str:\n    return {",
            "def _title_for(status: int) -> str:\n    return _({",
        )
        s = s.replace('.get(status, "Error")\n', '.get(status, "Error"))\n')
        s = s.replace("message=exc.message,", "message=_(exc.message),")
        s = s.replace(
            'message=exc.description if status < 500 else "An internal error occurred.",',
            'message=_(exc.description) if status < 500 else _("An internal error occurred."),',
        )
        p.write_text(s, encoding="utf-8", newline="\n")
        print("errors.py patched")
    else:
        print("errors.py already patched")


if __name__ == "__main__":
    main()
