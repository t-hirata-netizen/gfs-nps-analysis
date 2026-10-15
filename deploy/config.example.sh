# deploy/config.sh にコピーして値を入れてください（config.sh は Git 管理外）
PROJECT_ID="your-gcp-project-id"     # Google Cloud のプロジェクトID
REGION="asia-northeast1"             # 東京
SERVICE="gfs-nps"                    # Cloud Run のサービス名
BUCKET="${PROJECT_ID}-gfs-nps-data"  # データ保存用のバケット名（世界で一意）
DOMAIN="example.co.jp"               # ログインを許可する会社のドメイン
