from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from ingrid_patel.settings import TIMEZONE

MT = ZoneInfo(TIMEZONE)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def parse_iso(dt_iso: str) -> datetime:
    # Supports "YYYY-MM-DDTHH:MM:SS+00:00""
    return datetime.fromisoformat(dt_iso)


def format_release_mt(dt_utc_iso: str) -> str:
    dt_utc = parse_iso(dt_utc_iso)
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    dt_mt = dt_utc.astimezone(MT)
    return dt_mt.strftime("%B %d, %Y %I:%M %p MT")