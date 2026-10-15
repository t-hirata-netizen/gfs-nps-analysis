# Google Cloud Run 用。データは Cloud Storage に保存（gfs_analysis/cloud.py）
FROM python:3.9-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    GFS_CLOUD=1 \
    GFS_STORAGE=gcs \
    GFS_DB_PATH=/tmp/gfs/gfs_analysis.db

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

# Cloud Run が渡す PORT で待ち受ける。利用統計は送らない
CMD streamlit run app.py \
    --server.port=${PORT:-8080} \
    --server.address=0.0.0.0 \
    --server.headless=true \
    --server.maxUploadSize=30 \
    --browser.gatherUsageStats=false
