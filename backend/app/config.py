"""Runtime configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass
class Settings:
    port: int
    max_upload_mb: int
    log_level: str
    static_dir: str
    trusted_proxy_hops: int
    max_concurrent_conversions: int
    max_pending_conversions: int
    convert_rate_limit: str
    cors_allow_origins: tuple[str, ...]
    max_positions: int
    zip_threshold_mb: int
    usage_db_url: str
    usage_db_password: str
    usage_hash_secret: str
    usage_instance: str
    usage_drain_seconds: float
    geoip_db_path: str
    maxmind_license_key: str
    site_origin: str
    indexnow_key: str

    @property
    def max_upload_bytes(self) -> int:
        return self.max_upload_mb * 1024 * 1024


def load_settings() -> Settings:
    return Settings(
        port=int(os.getenv("PORT", "8080")),
        max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "25")),
        log_level=os.getenv("LOG_LEVEL", "INFO").upper(),
        static_dir=os.getenv("STATIC_DIR", "/app/static"),
        # Proxies in front of the app that append to X-Forwarded-For (Cloud Run: 1;
        # 0 = use the TCP peer, e.g. when uvicorn is reachable directly).
        trusted_proxy_hops=int(os.getenv("TRUSTED_PROXY_HOPS", "1")),
        # Conversions are CPU and memory bound; more in parallel only queue on one vCPU.
        max_concurrent_conversions=int(os.getenv("MAX_CONCURRENT_CONVERSIONS", "1")),
        # Conversions uploading, queued or running at once; more get 503 (each holds its upload).
        max_pending_conversions=int(os.getenv("MAX_PENDING_CONVERSIONS", "4")),
        convert_rate_limit=os.getenv("CONVERT_RATE_LIMIT", "20/minute;200/hour"),
        # Memory grows with the number of positions (≈ 50 KB each while converting).
        max_positions=int(os.getenv("MAX_POSITIONS", "10000")),
        # Larger outputs are delivered zipped (Cloud Run caps responses at 32 MiB).
        zip_threshold_mb=int(os.getenv("ZIP_THRESHOLD_MB", "8")),
        # Usage statistics (docs/USAGE_STATS.md); off unless USAGE_DB_URL is set.
        # The URL carries no password; it comes from USAGE_DB_PASSWORD (a secret).
        usage_db_url=os.getenv("USAGE_DB_URL", ""),
        usage_db_password=os.getenv("USAGE_DB_PASSWORD", ""),
        usage_hash_secret=os.getenv("USAGE_HASH_SECRET", ""),
        # Which deployment writes the rows: cloudrun | vps (both share one database).
        usage_instance=os.getenv("USAGE_INSTANCE", ""),
        usage_drain_seconds=float(os.getenv("USAGE_DRAIN_SECONDS", "2")),
        geoip_db_path=os.getenv("GEOIP_DB_PATH", "/app/geoip/GeoLite2-Country.mmdb"),
        maxmind_license_key=os.getenv("MAXMIND_LICENSE_KEY", ""),
        # The public address search engines should index (canonical, sitemap, og:url). Requests
        # for any other host (*.run.app, staging) get X-Robots-Tag: noindex.
        site_origin=os.getenv("SITE_ORIGIN", "https://www.fund-data-converter.eu").rstrip("/"),
        # IndexNow key (tools/indexnow_ping.py); served as /<key>.txt when set.
        indexnow_key=os.getenv("INDEXNOW_KEY", ""),
        cors_allow_origins=tuple(
            o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
        ),
    )


settings = load_settings()
