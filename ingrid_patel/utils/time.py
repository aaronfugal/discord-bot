# ingrid_patel/utils/time.py

from __future__ import annotations

import re
import unicodedata
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from typing import Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(microsecond=0)

def _coerce_z(s: str) -> str:
    """
    Convert trailing 'Z' to '+00:00' so datetime.fromisoformat can parse it.
    """
    s = (s or "").strip()
    if s.endswith("Z"):
        return s[:-1] + "+00:00"
    return s


def canonical_utc_iso(dt_iso: Optional[str]) -> Optional[str]:
    s = (dt_iso or "").strip()
    if not s:
        return None

    dt = datetime.fromisoformat(_coerce_z(s))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc).replace(microsecond=0)
    return dt.isoformat()



def parse_iso(dt_iso: str) -> datetime:
    dt = datetime.fromisoformat(_coerce_z(dt_iso))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def format_release(dt_utc_iso: str, tz_name: str) -> str:
    """
    Format a UTC ISO timestamp into a given timezone.
    """
    dt_utc = parse_iso(dt_utc_iso)
    tz = ZoneInfo(tz_name)
    dt_local = dt_utc.astimezone(tz)
    return dt_local.strftime("%B %d, %Y %I:%M %p")


def format_release_mt(dt_utc_iso: str) -> str:
    """
    Backwards-compatible wrapper.
    If you still call this anywhere, it will format in America/Denver.
    (Safe, but avoid using it for new code.)
    """
    try:
        return format_release(dt_utc_iso, "America/Denver") + " MT"
    except Exception:
        return dt_utc_iso


_PRECISION_UNKNOWN = "unknown"
_PRECISION_DAY = "day"
_PRECISION_MONTH = "month"
_PRECISION_QUARTER = "quarter"
_PRECISION_SEASON = "season"
_PRECISION_YEAR = "year"

_MONTH_ALIASES: dict[str, int] = {
    # English
    "jan": 1,
    "january": 1,
    "feb": 2,
    "february": 2,
    "mar": 3,
    "march": 3,
    "apr": 4,
    "april": 4,
    "may": 5,
    "jun": 6,
    "june": 6,
    "jul": 7,
    "july": 7,
    "aug": 8,
    "august": 8,
    "sep": 9,
    "sept": 9,
    "september": 9,
    "oct": 10,
    "october": 10,
    "nov": 11,
    "november": 11,
    "dec": 12,
    "december": 12,
    # Portuguese
    "fev": 2,
    "fevereiro": 2,
    "abr": 4,
    "abril": 4,
    "mai": 5,
    "maio": 5,
    "ago": 8,
    "set": 9,
    "setembro": 9,
    "out": 10,
    "outubro": 10,
    "dez": 12,
    "dezembro": 12,
    # French
    "janv": 1,
    "janvier": 1,
    "fevr": 2,
    "fevrier": 2,
    "mars": 3,
    "avr": 4,
    "avril": 4,
    "mai": 5,
    "juin": 6,
    "juil": 7,
    "juillet": 7,
    "aout": 8,
    "septembre": 9,
    "octobre": 10,
    "novembre": 11,
    "decembre": 12,
    # Spanish
    "ene": 1,
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
    # German
    "januar": 1,
    "februar": 2,
    "maerz": 3,
    "marz": 3,
    "mai": 5,
    "juni": 6,
    "juli": 7,
    "okt": 10,
    "oktober": 10,
    "dezember": 12,
}


def _normalize_month_token(token: str) -> str:
    # Remove accents/punctuation so "fev.", "fév.", "févr." normalize predictably.
    t = unicodedata.normalize("NFKD", token or "")
    t = "".join(ch for ch in t if not unicodedata.combining(ch))
    t = t.lower().strip().strip(".")
    t = re.sub(r"[^a-z0-9]", "", t)
    return t


def _parse_localized_dmy(date_text: str) -> str | None:
    """
    Parse localized day/month/year variants such as:
      - 26/fev./2026
      - 26/feb/2026
      - 26/02/2026
    """
    m = re.fullmatch(r"(\d{1,2})\s*/\s*([^/\s]+)\s*/\s*(\d{4})", (date_text or "").strip(), re.IGNORECASE)
    if not m:
        return None

    day = int(m.group(1))
    month_part = (m.group(2) or "").strip()
    year = int(m.group(3))

    month_num: int | None
    if month_part.isdigit():
        month_num = int(month_part)
    else:
        month_num = _MONTH_ALIASES.get(_normalize_month_token(month_part))

    if not month_num or not (1 <= month_num <= 12):
        return None

    try:
        dt = datetime(year, month_num, day, tzinfo=timezone.utc)
    except ValueError:
        return None
    return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()


def parse_steam_release_date(date_text: str) -> tuple[str | None, str]:
    """
    Returns (release_at_utc_iso_or_none, precision).

    Precision values:
      - day, month, quarter, season, year, unknown

    Notes:
      - For non-day formats, we store an "anchor" date (earliest plausible date)
        so ordering works and we can refresh later when Steam becomes precise.
      - For truly unknown ("TBA", "Coming Soon"), return (None, "unknown").
    """
    s = (date_text or "").strip()
    if not s:
        return None, _PRECISION_UNKNOWN

    s_norm = re.sub(r"\s+", " ", s).strip()

    # Common unknowns
    if re.search(r"\b(tba|tbd|to be announced|coming soon)\b", s_norm, re.IGNORECASE):
        return None, _PRECISION_UNKNOWN

    # 1) Exact day formats (try multiple common Steam strings)
    day_formats = (
        "%b %d, %Y",      # Jan 20, 2026
        "%B %d, %Y",      # January 20, 2026
        "%d %b, %Y",      # 20 Jan, 2026 (rare)
        "%d %B, %Y",      # 20 January, 2026 (rare)
    )
    for fmt in day_formats:
        try:
            # Anchor at UTC midnight for the date (no local timezone assumptions).
            dt = datetime.strptime(s_norm, fmt).replace(tzinfo=timezone.utc)
            dt = dt.replace(hour=0, minute=0, second=0, microsecond=0)
            return dt.isoformat(), _PRECISION_DAY
        except ValueError:
            pass

    localized_iso = _parse_localized_dmy(s_norm)
    if localized_iso:
        return localized_iso, _PRECISION_DAY

    # 2) Month + year (e.g. "May 2026", "Sep 2026") -> anchor at first day UTC
    m = re.fullmatch(r"([A-Za-z]+)\s+(\d{4})", s_norm)
    if m:
        mon_str, year_str = m.group(1), m.group(2)
        for fmt in ("%b %Y", "%B %Y"):
            try:
                dt = datetime.strptime(f"{mon_str} {year_str}", fmt).replace(tzinfo=timezone.utc)
                dt = dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                return dt.isoformat(), _PRECISION_MONTH
            except ValueError:
                pass

    # 3) Quarter (Q1..Q4)
    m = re.fullmatch(r"Q([1-4])\s+(\d{4})", s_norm, flags=re.IGNORECASE)
    if m:
        q = int(m.group(1))
        year = int(m.group(2))
        month = {1: 1, 2: 4, 3: 7, 4: 10}[q]
        dt = datetime(year, month, 1, tzinfo=timezone.utc)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(), _PRECISION_QUARTER

    # 4) Seasons (Spring/Summer/Fall/Autumn/Winter)
    m = re.fullmatch(r"(Spring|Summer|Fall|Autumn|Winter)\s+(\d{4})", s_norm, flags=re.IGNORECASE)
    if m:
        season = m.group(1).lower()
        year = int(m.group(2))

        # Earliest plausible month starts (Northern hemisphere convention)
        season_start_month = {
            "spring": 3,
            "summer": 6,
            "fall": 9,
            "autumn": 9,
            "winter": 12,  # winter spans year boundary; anchor to Dec 1 of stated year
        }[season]

        dt = datetime(year, season_start_month, 1, tzinfo=timezone.utc)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(), _PRECISION_SEASON

    # 5) Year only (e.g. "2026")
    if s_norm.isdigit() and len(s_norm) == 4:
        year = int(s_norm)
        try:
            dt = datetime(year, 1, 1, tzinfo=timezone.utc)
            return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(), _PRECISION_YEAR
        except ValueError:
            return None, _PRECISION_UNKNOWN

    # "Early 2026" / "Late 2026" -> year anchor
    m = re.fullmatch(r"(Early|Mid|Late)\s+(\d{4})", s_norm, flags=re.IGNORECASE)
    if m:
        year = int(m.group(2))
        dt = datetime(year, 1, 1, tzinfo=timezone.utc)
        return dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(), _PRECISION_YEAR

    return None, _PRECISION_UNKNOWN


def parse_steam_release_date_to_utc_iso(date_text: str) -> str | None:
    iso, _precision = parse_steam_release_date(date_text)
    return iso
