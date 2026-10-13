"""匿名サンプルデータを sample_data/ に作成する

    .venv/bin/python scripts/make_sample_data.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from gfs_analysis.sample import (action_csv_bytes, link_csv_bytes, make_action_frame,  # noqa: E402
                                 make_sample_frame, write_survey_excel)

if __name__ == "__main__":
    out_dir = Path(__file__).resolve().parent.parent / "sample_data"
    survey = make_sample_frame()
    write_survey_excel(out_dir / "sample_60日アンケート.xlsx", survey)
    (out_dir / "sample_アクションリスト.csv").write_bytes(action_csv_bytes(make_action_frame(survey)))
    (out_dir / "sample_ID対応表.csv").write_bytes(link_csv_bytes(survey["会員ID"].unique()))
    print(f"作成しました: {out_dir}")
