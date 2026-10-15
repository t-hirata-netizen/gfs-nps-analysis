#!/bin/zsh
# アプリをビルドして Cloud Run に出す（初回・更新のたび）。ログインは会社の Google アカウントだけ許可
set -euo pipefail
cd "$(dirname "$0")/.."
source deploy/config.sh
SA="gfs-nps-app@${PROJECT_ID}.iam.gserviceaccount.com"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"

# 最大インスタンス数 1：データベースに同時に書き込むプロセスを1つにするため
gcloud beta run deploy "$SERVICE" --source . --region "$REGION" \
  --service-account "$SA" --no-allow-unauthenticated --iap \
  --max-instances 1 --min-instances 0 --memory 1Gi --cpu 1 \
  --timeout 3600 --session-affinity \
  --set-env-vars "GFS_DB_BUCKET=${BUCKET}"

# Google のログイン（IAP）からアプリを呼べるようにする
gcloud run services add-iam-policy-binding "$SERVICE" --region "$REGION" \
  --member="serviceAccount:service-${PROJECT_NUMBER}@gcp-sa-iap.iam.gserviceaccount.com" \
  --role="roles/run.invoker"

# 会社のドメインのアカウントだけ利用を許可
gcloud beta iap web add-iam-policy-binding --resource-type=cloud-run \
  --service="$SERVICE" --region="$REGION" \
  --member="domain:${DOMAIN}" --role="roles/iap.httpsResourceAccessor"

gcloud run services describe "$SERVICE" --region "$REGION" --format='value(status.url)'
