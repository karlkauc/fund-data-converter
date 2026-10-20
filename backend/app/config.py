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
    convert_rate_limit: str
    cors_allow_origins: tuple[str, ...]
    max_positions: int
    zip_threshold_mb: int

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
        convert_rate_limit=os.getenv("CONVERT_RATE_LIMIT", "20/minute"),
        # Memory grows with the number of positions (≈ 50 KB each while converting).
        max_positions=int(os.getenv("MAX_POSITIONS", "10000")),
        # Larger outputs are delivered zipped (Cloud Run caps responses at 32 MiB).
        zip_threshold_mb=int(os.getenv("ZIP_THRESHOLD_MB", "8")),
        cors_allow_origins=tuple(
            o.strip() for o in os.getenv("CORS_ALLOW_ORIGINS", "").split(",") if o.strip()
        ),
    )


settings = load_settings()
