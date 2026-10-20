#!/usr/bin/env bash
# Deploy to Cloud Run with `gcloud run deploy --source .` (Cloud Build builds the Dockerfile).
#
# Usage: GCP_PROJECT=my-project scripts/deploy.sh
#        GCP_PROJECT=my-project scripts/deploy.sh --memory 1Gi   (extra flags go to gcloud)
#
# The project is always passed explicitly – never rely on the gcloud default project.
#
# Sizing: a 10,000-position TPT needs ~800 MB and ~11 s while converting, so one
# conversion runs per 1 GiB instance; parallel uploads spread over up to 4 instances.
# min-instances 0: nothing runs (or costs) while nobody converts.
set -euo pipefail

PROJECT="${GCP_PROJECT:?set GCP_PROJECT to the Google Cloud project id}"
REGION="${GCP_REGION:-europe-west1}"
SERVICE="${SERVICE:-tpt-fundsxml}"

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo ">> deploying $SERVICE to $PROJECT/$REGION"
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
  --set-env-vars "MAX_UPLOAD_MB=25,MAX_POSITIONS=10000,MAX_CONCURRENT_CONVERSIONS=1,TRUSTED_PROXY_HOPS=1" \
  "$@"

URL="$(gcloud run services describe "$SERVICE" --project "$PROJECT" --region "$REGION" --format 'value(status.url)')"
echo ">> smoke test $URL"
curl -fsS "$URL/api/health" && echo
curl -fsS -o /dev/null -w "sample conversion: HTTP %{http_code}\n" \
  -F "file=@backend/app/samples/tpt_v7_sample.xlsx" "$URL/api/convert"
