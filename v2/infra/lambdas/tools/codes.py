"""Pure validation helpers shared by tools (unit tested without AWS)."""

from __future__ import annotations

import datetime as dt
import re

ICD10 = re.compile(r"^[A-TV-Z][0-9][0-9A-Z](\.[0-9A-Z]{1,4})?$")
CPT = re.compile(r"^[0-9]{4}[0-9A-Z]$")
HCPCS = re.compile(r"^[A-V][0-9]{4}$")
POS = re.compile(r"^[0-9]{2}$")
MODIFIER = re.compile(r"^[0-9A-Z]{2}$")


def normalize_code(code: str | None) -> str:
    return re.sub(r"\s+", "", (code or "")).upper().split("/")[0].split("-")[0]


def normalize_icd10(code: str | None) -> str:
    c = normalize_code(code).replace(".", "")
    return f"{c[:3]}.{c[3:]}" if len(c) > 3 else c


def npi_is_valid(npi: str | None) -> bool:
    """CMS NPI check digit: Luhn over the 80840 prefix + first 9 digits."""
    digits = re.sub(r"\D", "", npi or "")
    if len(digits) != 10:
        return False
    total = 0
    for i, ch in enumerate(reversed("80840" + digits[:9])):
        d = int(ch)
        if i % 2 == 0:
            d *= 2
            d = d - 9 if d > 9 else d
        total += d
    return (10 - total % 10) % 10 == int(digits[9])


_DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%m %d %Y", "%m %d %y", "%Y%m%d")


def parse_date(value: str | None) -> dt.date | None:
    if not value:
        return None
    text = str(value).strip()
    for fmt in _DATE_FORMATS:
        try:
            return dt.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def name_tokens(name: str | None) -> set[str]:
    return {t for t in re.split(r"[\s,.]+", (name or "").lower()) if len(t) > 1}
