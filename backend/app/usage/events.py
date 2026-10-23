"""Pure helpers for building usage events – no I/O, fully unit-testable.

Ported from the XSD/XML/OData viewers so the usage dashboard can read the
table with the shared viewer queries; the converter adds its own columns.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from collections.abc import Mapping
from dataclasses import dataclass, field, fields
from datetime import date
from urllib.parse import urlsplit, urlunsplit

MAX_TEXT = 255

_BOT_RE = re.compile(
    r"bot|crawl|spider|slurp|curl/|wget/|python-|httpx|aiohttp|go-http-client|"
    r"headless|lighthouse|preview|facebookexternalhit|scrapy|java/|libwww|okhttp|monitor|uptime|"
    r"scan|check|validat|radar|probe|googleother|lead-research|censys|palo alto|zgrab|nuclei",
    re.IGNORECASE,
)
# Scanners like to pose as long-gone browsers (Chrome 33, Firefox 21); real visitors are far newer.
_ENGINE_VERSION_RE = re.compile(r"\b(?:Chrome|Firefox)/(\d+)")
_MIN_ENGINE_VERSION = 100
# Same trick with Safari (a crawler as iOS 13 Safari, one visitor per hit). Only real Safari
# sends "Version/N … Safari/"; Chrome/Firefox on iOS (CriOS/FxiOS) and Android WebViews do not.
_SAFARI_VERSION_RE = re.compile(r"\bVersion/(\d+)[\d.]* (?:Mobile/\S+ )?Safari/")
_MIN_SAFARI_VERSION = 15
_MOBILE_RE = re.compile(r"Mobile|Android|iPhone|iPad|iPod|Windows Phone|Opera Mini", re.IGNORECASE)


@dataclass(slots=True)
class UsageEvent:
    """One row of the ``usage_event`` table (column order = field order)."""

    event_type: str
    visitor_hash: str | None = None
    country_code: str | None = None
    user_agent: str | None = None
    device: str | None = None
    status_code: int | None = None
    app_version: str | None = None
    path: str | None = None
    referrer: str | None = None
    source: str | None = None
    schema_name: str | None = None
    target_namespace: str | None = None
    input_bytes: int | None = None
    file_count: int | None = None
    element_count: int | None = None
    type_count: int | None = None
    diagnostic_count: int | None = None
    error_count: int | None = None
    duration_ms: int | None = None
    status: str | None = None
    error_detail: str | None = None
    utm_source: str | None = None
    utm_medium: str | None = None
    utm_campaign: str | None = None
    # converter-specific columns
    direction: str | None = None
    tpt_version: str | None = None
    version_source: str | None = None
    output_format: str | None = None
    include_block: bool | None = None
    include_core: bool | None = None
    issue_codes: list[str] = field(default_factory=list)
    valid: bool | None = None
    zipped: bool | None = None
    instance: str | None = None
    # added 2026-10 (T3): ALTER TABLE in backend/sql/usage_stats.sql before deploying
    delimiter: str | None = None
    all_columns: bool | None = None
    output_bytes: int | None = None
    # added 2026-10 (public API): ALTER TABLE in backend/sql/usage_stats.sql before deploying
    channel: str | None = None  # web (the SPA sends X-Client: web) | api
    response_mode: str | None = None  # convert: json | file | zip
    # added 2026-10 (format statistics): ALTER TABLE in backend/sql/usage_stats.sql before deploying
    source_format: str | None = None  # tpt | fundsxml | openfunds
    target_format: str | None = None
    of_layout: str | None = None  # openfunds input: flat | narrow
    of_templates: list[str] = field(default_factory=list)  # EMT, EPT, EET, EFT with filled fields
    shareclass_count: int | None = None
    holding_count: int | None = None
    asset_count: int | None = None
    has_tpt_block: bool | None = None  # FundsXML input
    cic_categories: list[str] = field(default_factory=list)  # CIC categories present (1–9, 0, A–F)
    warning_count: int | None = None
    info_count: int | None = None
    values_lost: int | None = None  # report.dataLoss
    values_kept_custom: int | None = None
    coverage_pct: float | None = None  # → FundsXML: source fields placed in the block or core
    options: list[str] = field(default_factory=list)  # non-default options, fixed names
    target: str | None = None  # download: xml | xlsx | csv | zip; handoff: validator | xml-viewer

    def as_row(self) -> tuple:
        return tuple(getattr(self, f.name) for f in fields(self))


COLUMNS: tuple[str, ...] = tuple(f.name for f in fields(UsageEvent))

INSERT_SQL = f"INSERT INTO usage_event ({', '.join(COLUMNS)}) VALUES ({', '.join('%s' for _ in COLUMNS)})"


def truncate(value: str | None, limit: int = MAX_TEXT) -> str | None:
    if value is None:
        return None
    value = value.strip()
    if not value:
        return None
    return value[:limit]


def visitor_hash(ip: str | None, user_agent: str | None, day: date, secret: str) -> str | None:
    """Daily-salted, non-reversible visitor id.

    The salt is HMAC(secret, day) – or just the day when no secret is set – so
    the same visitor hashes identically within one day and differently the
    next. Without ``secret`` a brute-force over the IPv4 space is feasible;
    ``USAGE_HASH_SECRET`` should therefore be set in production.
    """
    if not ip:
        return None
    day_key = day.isoformat()
    salt = hmac.new(secret.encode(), day_key.encode(), hashlib.sha256).hexdigest() if secret else day_key
    digest = hashlib.sha256(f"{salt}|{ip}|{user_agent or ''}".encode()).hexdigest()
    return digest[:32]


def classify_device(user_agent: str | None) -> str:
    if not user_agent or not user_agent.strip():
        return "unknown"
    # Every real browser sends "Mozilla/5.0 (…"; bare tool names are scripts and probes.
    if not user_agent.startswith("Mozilla/") or _BOT_RE.search(user_agent):
        return "bot"
    engine = _ENGINE_VERSION_RE.search(user_agent)
    if engine and int(engine.group(1)) < _MIN_ENGINE_VERSION:
        return "bot"
    safari = _SAFARI_VERSION_RE.search(user_agent)
    if safari and int(safari.group(1)) < _MIN_SAFARI_VERSION:
        return "bot"
    if _MOBILE_RE.search(user_agent):
        return "mobile"
    return "desktop"


def clean_referrer(header: str | None) -> str | None:
    """Keep scheme, host and path of a Referer; drop query, fragment, credentials."""
    if not header:
        return None
    try:
        parts = urlsplit(header.strip())
    except ValueError:
        return None
    if parts.scheme not in ("http", "https") or not parts.hostname:
        return None
    netloc = parts.hostname + (f":{parts.port}" if parts.port else "")
    return truncate(urlunsplit((parts.scheme, netloc, parts.path or "/", "", "")))


_UTM_RE = re.compile(r"[a-z0-9._-]{1,64}")
UTM_KEYS = ("utm_source", "utm_medium", "utm_campaign")


def utm_fields(query: Mapping[str, str]) -> dict[str, str]:
    """Campaign tags of a page view. The site sends ``Referrer-Policy: no-referrer``,
    so links from the sister sites and posts carry ``utm_source`` instead; anything
    that is not a short slug is dropped rather than stored."""
    tags: dict[str, str] = {}
    for key in UTM_KEYS:
        value = (query.get(key) or "").strip().lower()
        if _UTM_RE.fullmatch(value):
            tags[key] = value
    return tags
