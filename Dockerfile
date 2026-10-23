# syntax=docker/dockerfile:1.7

# ---------- Stage 1: build the frontend ----------
FROM node:22-alpine@sha256:fe4f6d74e20370acb04ad889077d14d0f64a9c8ea6a42bc60cddf1e844699914 AS frontend
WORKDIR /src/frontend

COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# ---------- Stage 2: python runtime ----------
FROM python:3.12-slim@sha256:cb33f7f771ecec2ef1225cf39b159591a040391bd73e4c01f00fdfc4c47611d2 AS runtime

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
# The commit built, named in converted files and usage rows (app.release_version); passed by
# docker compose from GIT_COMMIT on the host, empty for the version alone. Set last, so a new
# commit does not rebuild the layers above.
ARG GIT_COMMIT=""
ENV GIT_COMMIT=${GIT_COMMIT}

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD python -c "import os,urllib.request,sys; \
    r=urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8080')+'/api/health',timeout=3); \
    sys.exit(0 if r.status==200 else 1)" || exit 1

# One worker: Cloud Run scales by instances; a second process would only double the memory.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT} --workers 1 --no-access-log"]
