#!/bin/zsh
# 初回だけ：Google Cloud の準備（API 有効化・バケット・サービスアカウント）
set -euo pipefail
cd "$(dirname "$0")"
source ./config.sh
SA="gfs-nps-app@${PROJECT_ID}.iam.gserviceaccount.com"

gcloud config set project "$PROJECT_ID"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com \
  iap.googleapis.com storage.googleapis.com

# データ保存用バケット（非公開・世代管理あり＝過去の状態に戻せる）
gcloud storage buckets create "gs://${BUCKET}" --location="$REGION" \
  --uniform-bucket-level-access --public-access-prevention || true
gcloud storage buckets update "gs://${BUCKET}" --versioning

# アプリ用のサービスアカウント（このバケットだけ読み書きできる）
gcloud iam service-accounts create gfs-nps-app --display-name="GFS NPS analysis app" || true
gcloud storage buckets add-iam-policy-binding "gs://${BUCKET}" \
  --member="serviceAccount:${SA}" --role="roles/storage.objectAdmin"
echo "準備完了。次は ./upload_db.sh（今のデータを載せる場合）→ ./deploy.sh"
