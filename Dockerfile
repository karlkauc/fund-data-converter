# syntax=docker/dockerfile:1.7

# ---------- Stage 1: build the frontend ----------
FROM node:20-alpine@sha256:fb4cd12c85ee03686f6af5362a0b0d56d50c58a04632e6c0fb8363f609372293 AS frontend
WORKDIR /src/frontend

COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------- Stage 2: python runtime ----------
FROM python:3.12-slim@sha256:46cb7cc2877e60fbd5e21a9ae6115c30ace7a077b9f8772da879e4590c18c2e3 AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    STATIC_DIR=/app/static \
    GEOIP_DB_PATH=/app/geoip/GeoLite2-Country.mmdb \
    PORT=8080

RUN addgroup --system --gid 1001 app \
 && adduser --system --uid 1001 --ingroup app --home /app app

WORKDIR /app

# lxml and openpyxl ship manylinux wheels with their own libxml2; no apt packages needed.
COPY backend/pyproject.toml ./pyproject.toml
COPY backend/app ./app
RUN pip install --no-cache-dir . && rm -rf /root/.cache

COPY --from=frontend /src/frontend/dist ./static

# GeoLite2-Country for the usage statistics (optional). scripts/deploy.sh downloads it into
# backend/geoip/ before the build, so no instance downloads it at runtime (MaxMind's daily
# limit). Without the file the app downloads it at startup when MAXMIND_LICENSE_KEY is set;
# the directory is app-owned so that fallback can write.
COPY --chown=app:app backend/geoip ./geoip

USER app

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request,sys; \
    r=urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/health',timeout=3); \
    sys.exit(0 if r.status==200 else 1)" || exit 1

# One worker: Cloud Run scales by instances; a second process would only double the memory.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --no-access-log"]
