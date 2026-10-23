#!/usr/bin/env bash
# Deploy to Cloud Run with `gcloud run deploy --source .` (Cloud Build builds the Dockerfile).
#
# Usage: GCP_PROJECT=my-project scripts/deploy.sh
#        GCP_PROJECT=my-project scripts/deploy.sh --memory 1Gi   (extra flags go to gcloud)
#        SKIP_GEOIP=1 GCP_PROJECT=my-project scripts/deploy.sh   (keep the GeoLite2 file as is)
#
# The project is always passed explicitly – never rely on the gcloud default project.
#
# Sizing: a 10,000-position TPT needs ~800 MB and ~11 s while converting, so one
# conversion runs per 1 GiB instance; parallel uploads spread over up to 4 instances.
# min-instances 0: nothing runs (or costs) while nobody converts.
#
# Usage statistics (docs/USAGE_STATS.md) are switched on when the secret
# tptconverter-db-password exists in the project; see there for the one-time setup.
set -euo pipefail

PROJECT="${GCP_PROJECT:?set GCP_PROJECT to the Google Cloud project id}"
REGION="${GCP_REGION:-europe-west1}"
SERVICE="${SERVICE:-tpt-fundsxml}"
EDITION=GeoLite2-Country
USAGE_DB_URL='postgresql://tptconverter@62.238.116.11:5432/tptconverter_stats?sslmode=require'

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

ENV_VARS="MAX_UPLOAD_MB=25,MAX_POSITIONS=10000,MAX_CONCURRENT_CONVERSIONS=1,TRUSTED_PROXY_HOPS=1"
# The address search engines index (canonical, sitemap). Every other host – including the
# *.run.app URL – answers with X-Robots-Tag: noindex.
ENV_VARS+=",SITE_ORIGIN=${SITE_ORIGIN:-https://www.fund-data-converter.eu}"
if [[ -n "${INDEXNOW_KEY:-}" ]]; then ENV_VARS+=",INDEXNOW_KEY=${INDEXNOW_KEY}"; fi
USAGE_FLAGS=()
if gcloud secrets describe tptconverter-db-password --project "$PROJECT" >/dev/null 2>&1; then
  if [[ "${SKIP_GEOIP:-}" != "1" ]]; then
    echo ">> downloading ${EDITION} (key from Secret Manager)"
    KEY="$(gcloud secrets versions access latest --secret=tptconverter-maxmind-license-key --project "$PROJECT" | tr -d '\n')"
    TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
    # -s: never echo the URL (it carries the key); query auth is what MaxMind offers for GeoLite.
    curl -fsSL --retry 3 --retry-delay 5 -o "$TMP/db.tar.gz" \
      "https://download.maxmind.com/app/geoip_download?edition_id=${EDITION}&license_key=${KEY}&suffix=tar.gz"
    tar -xzf "$TMP/db.tar.gz" -C "$TMP" --wildcards "*/${EDITION}.mmdb"
    mv "$TMP"/*/"${EDITION}.mmdb" "backend/geoip/${EDITION}.mmdb"
  fi
  [[ -s "backend/geoip/${EDITION}.mmdb" ]] || echo "!! GeoLite2 file missing – instances download it at startup" >&2
  ENV_VARS+=",USAGE_INSTANCE=cloudrun,USAGE_DB_URL=${USAGE_DB_URL}"
  USAGE_FLAGS=(--update-secrets "USAGE_DB_PASSWORD=tptconverter-db-password:latest,USAGE_HASH_SECRET=tptconverter-usage-hash-secret:latest,MAXMIND_LICENSE_KEY=tptconverter-maxmind-license-key:latest")
else
  echo "!! secret tptconverter-db-password not found – deploying without usage statistics" >&2
fi

echo ">> deploying $SERVICE to $PROJECT/$REGION"
# --set-env-vars replaces all plain env vars, so every one the service needs is listed above.
gcloud run deploy "$SERVICE" \
  --source . \
  --project "$PROJECT" \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 1Gi \
  --cpu 1 \
  --cpu-boost \
  --concurrency 4 \
  --min-instances 0 \
  --max-instances 4 \
  --timeout 60 \
  --set-env-vars "$ENV_VARS" \
  "${USAGE_FLAGS[@]}" \
  "$@"

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
echo ">> smoke test $URL"
curl -fsS "$URL/api/health" && echo
curl -fsS -o /dev/null -w "sample conversion: HTTP %{http_code}\n" \
  -F "file=@backend/app/samples/tpt_v7_sample.xlsx" "$URL/api/convert"
