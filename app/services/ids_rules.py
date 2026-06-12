"""Shared Suricata ruleset logic: categorisation, active-subset filtering and
predefined detection templates. Used by both the admin UI and the probe-facing
rules endpoint so the two never drift."""

import re
import hashlib

ACTIONS = ('alert ', 'drop ', 'reject ', 'pass ', 'sdrop ')
_ET_CAT_RE = re.compile(r'msg:\s*"ET\s+([A-Z0-9_]+)')
_CLASSTYPE_RE = re.compile(r'classtype:\s*([a-z0-9\-]+)')


def is_rule_line(ln):
    s = ln.lstrip()
    return bool(s) and not s.startswith('#') and s.startswith(ACTIONS)


def rule_category(line):
    """Human-friendly category for a rule (ET category, else classtype, else Other)."""
    m = _ET_CAT_RE.search(line)
    if m:
        return m.group(1).capitalize()
    m = _CLASSTYPE_RE.search(line)
    if m:
        return m.group(1).replace('-', ' ').title()
    return "Other"


def count_rules(text):
    return sum(1 for ln in text.splitlines() if is_rule_line(ln))


def categorize(text, prev_enabled=None):
    """Returns [{name, count, enabled}] grouped by category, preserving previous
    enable choices when re-downloading (new categories default to enabled)."""
    counts = {}
    for ln in text.splitlines():
        if is_rule_line(ln):
            c = rule_category(ln)
            counts[c] = counts.get(c, 0) + 1
    cats = []
    for name in sorted(counts):
        enabled = True if prev_enabled is None else (name in prev_enabled)
        cats.append({"name": name, "count": counts[name], "enabled": enabled})
    return cats


def active_rules(ruleset):
    """Returns (active_text, version, active_count) for the currently-enabled
    categories. The version incorporates the selection so probes re-sync on change."""
    cats = ruleset.categories or []
    base = ruleset.version or ''
    if not cats:
        return ruleset.rules_text or '', base, ruleset.rule_count or 0

    enabled = {c['name'] for c in cats if c.get('enabled')}
    lines = []
    for ln in (ruleset.rules_text or '').splitlines():
        if not is_rule_line(ln) or rule_category(ln) in enabled:
            lines.append(ln)
    text = "\n".join(lines)
    version = hashlib.sha256((base + "|" + ",".join(sorted(enabled))).encode()).hexdigest()[:12]
    return text, version, count_rules(text)


# Predefined detection profiles: each maps to a set of category keywords.
DETECTION_TEMPLATES = [
    {"name": "Full Coverage", "icon": "fa-shield-halved",
     "desc": "Every available rule category — maximum detection.", "keywords": None},
    {"name": "Malware & C2", "icon": "fa-virus",
     "desc": "Malware, trojans, botnets, coinminers, phishing.",
     "keywords": ["malware", "trojan", "worm", "botcc", "adware", "coinminer", "mobile",
                  "compromised", "ciarmy", "dshield", "phishing", "drop"]},
    {"name": "Network Recon", "icon": "fa-magnifying-glass",
     "desc": "Port scans, DoS, DNS abuse and reconnaissance.",
     "keywords": ["scan", "dos", "dns", "icmp", "info", "hunting"]},
    {"name": "Web Attacks", "icon": "fa-globe",
     "desc": "Web servers/apps, SQL injection, client-side.",
     "keywords": ["web", "sql", "activex"]},
    {"name": "Exploits & Intrusion", "icon": "fa-bomb",
     "desc": "Exploits, shellcode, attack responses.",
     "keywords": ["exploit", "attack_response", "shellcode", "current_events", "rpc", "netbios", "smtp"]},
    {"name": "Policy & Compliance", "icon": "fa-user-shield",
     "desc": "Acceptable-use: policy, P2P, chat, Tor, games.",
     "keywords": ["policy", "inappropriate", "games", "p2p", "chat", "tor", "voip"]},
]


def template_by_name(name):
    return next((t for t in DETECTION_TEMPLATES if t['name'] == name), None)


def apply_template(categories, template_name):
    """Returns a new categories list with enabled flags set per the named template."""
    tmpl = template_by_name(template_name)
    if not tmpl:
        return None
    out = []
    for c in (categories or []):
        if tmpl['keywords'] is None:
            on = True
        else:
            nl = c['name'].lower()
            on = any(k in nl for k in tmpl['keywords'])
        out.append({"name": c['name'], "count": c['count'], "enabled": on})
    return out
