"""Parsing of Kubernetes resource quantities ("250m", "1Gi", "1.5", "128974848")."""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

_SUFFIX = {
    "n": Decimal("1e-9"), "u": Decimal("1e-6"), "m": Decimal("1e-3"), "": Decimal(1),
    "k": Decimal(10**3), "M": Decimal(10**6), "G": Decimal(10**9), "T": Decimal(10**12),
    "P": Decimal(10**15), "E": Decimal(10**18),
    "Ki": Decimal(2**10), "Mi": Decimal(2**20), "Gi": Decimal(2**30), "Ti": Decimal(2**40),
    "Pi": Decimal(2**50), "Ei": Decimal(2**60),
}  # fmt: skip
_RE = re.compile(r"^([+-]?[0-9.]+(?:[eE][+-]?[0-9]+)?)(n|u|m|k|M|G|T|P|E|Ki|Mi|Gi|Ti|Pi|Ei)?$")

CPU_RE = re.compile(r"^([0-9]+m|[0-9]+(\.[0-9]{1,3})?)$")
MEMORY_RE = re.compile(r"^[0-9]+(Ki|Mi|Gi|Ti|k|M|G|T)?$")


def parse_quantity(value: str | int | float | None) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return Decimal(str(value))
    m = _RE.match(str(value).strip())
    if not m:
        return None
    try:
        return Decimal(m.group(1)) * _SUFFIX[m.group(2) or ""]
    except InvalidOperation:
        return None


def cpu_cores(value: str | None) -> float | None:
    q = parse_quantity(value)
    return float(q) if q is not None else None


def bytes_(value: str | None) -> int | None:
    q = parse_quantity(value)
    return int(q) if q is not None else None


def is_valid_cpu(value: str) -> bool:
    return bool(CPU_RE.match(value)) and (cpu_cores(value) or 0) > 0


def is_valid_memory(value: str) -> bool:
    return bool(MEMORY_RE.match(value)) and (bytes_(value) or 0) > 0
