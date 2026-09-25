"""
HTML / Markdown 報告產生器
讀取 results/ 下的 metrics.json，產出完整分析報告
"""
import json
import os
from datetime import datetime
from pathlib import Path

import pandas as pd

from config import RESULTS_DIR, REPORT_DIR, MODEL_NAMES


def _load_all_metrics() -> list[dict]:
    records = []
    for model_key in MODEL_NAMES:
        model_dir = RESULTS_DIR / model_key
        if not model_dir.exists():
            continue
        for stock_dir in sorted(model_dir.iterdir()):
            metrics_file = stock_dir / "metrics.json"
            if not metrics_file.exists():
                continue
            with open(metrics_file) as f:
                m = json.load(f)
            records.append({
                "stock_id":   stock_dir.name,
                "model_key":  model_key,
                "model_name": MODEL_NAMES[model_key],
                **m,
            })
    return records


def generate_report(summary: list[dict] | None = None) -> str:
    """
    summary: 訓練時直接傳入，或為 None 時從磁碟讀取
    回傳 HTML 報告路徑
    """
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    if summary is None:
        summary = _load_all_metrics()

    if not summary:
        print("無可用的評估結果，跳過報告產生")
        return ""

    df = pd.DataFrame(summary)
    generated_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # ── 各指標最佳模型（跨股票平均）──────────────────────────────────────
    avg_by_model = (
        df.groupby("model_name")[["MAE", "RMSE", "MAPE", "DA"]]
        .mean().round(3).reset_index()
        .sort_values("RMSE")
    )

    # ── 各股票最佳模型 ────────────────────────────────────────────────────
    best_per_stock = (
        df.loc[df.groupby("stock_id")["RMSE"].idxmin()]
        [["stock_id", "model_name", "MAE", "RMSE", "MAPE", "DA"]]
        .sort_values("stock_id").reset_index(drop=True)
    )

    # ── 產生 HTML ──────────────────────────────────────────────────────────
    def df_to_html(d: pd.DataFrame, highlight_col: str = None) -> str:
        rows = ""
        for _, row in d.iterrows():
            cells = ""
            for col in d.columns:
                val = row[col]
                style = ""
                if col == highlight_col and isinstance(val, float):
                    # 最低值標綠
                    min_val = d[col].min()
                    if abs(val - min_val) < 1e-9:
                        style = ' style="background:#C8E6C9;font-weight:bold"'
                cells += f"<td{style}>{val:.3f}" \
                         if isinstance(val, float) else f"<td>{val}"
                cells += "</td>"
            rows += f"<tr>{cells}</tr>"

        headers = "".join(f"<th>{c}</th>" for c in d.columns)
        return (f'<table border="1" cellpadding="6" cellspacing="0" '
                f'style="border-collapse:collapse;font-size:13px">'
                f"<thead><tr>{headers}</tr></thead><tbody>{rows}</tbody></table>")

    # ── 圖片嵌入 ──────────────────────────────────────────────────────────
    img_blocks = ""
    for stock_id in sorted(df["stock_id"].unique()):
        img_blocks += f'<h3>📈 {stock_id}</h3><div style="display:flex;flex-wrap:wrap;gap:10px">'
        for model_key in MODEL_NAMES:
            img_path = RESULTS_DIR / model_key / stock_id / "prediction.png"
            if img_path.exists():
                rel = os.path.relpath(str(img_path), str(REPORT_DIR))
                rel = rel.replace("\\", "/")
                label = MODEL_NAMES[model_key]
                img_blocks += (
                    f'<div style="text-align:center">'
                    f'<p style="margin:4px;font-size:12px">{label}</p>'
                    f'<img src="{rel}" width="480">'
                    f'</div>'
                )
        img_blocks += "</div><hr>"

    html = f"""<!DOCTYPE html>
<html lang="zh-Hant">
<head>
  <meta charset="UTF-8">
  <title>LSTM 模型訓練報告</title>
  <style>
    body {{ font-family: "Segoe UI", sans-serif; margin: 30px; color: #333; }}
    h1   {{ color: #1565C0; }}
    h2   {{ color: #1976D2; border-bottom: 2px solid #90CAF9; padding-bottom: 4px; }}
    h3   {{ color: #424242; }}
    table {{ margin-bottom: 20px; }}
    th   {{ background: #1976D2; color: white; padding: 8px; }}
    td   {{ padding: 6px 10px; }}
    tr:nth-child(even) td {{ background: #F5F5F5; }}
    .badge {{ display:inline-block; padding:2px 8px; border-radius:4px;
              background:#1976D2; color:white; font-size:12px; }}
  </style>
</head>
<body>
  <h1>📊 LSTM 股票預測模型訓練報告</h1>
  <p>產生時間：{generated_at}　｜
     股票數：{df['stock_id'].nunique()}　｜
     模型數：{df['model_name'].nunique()}</p>

  <h2>1. 模型整體表現（跨股票平均）</h2>
  <p>指標說明：
     <b>MAE</b>（平均絕對誤差，TWD）｜
     <b>RMSE</b>（均方根誤差，TWD）｜
     <b>MAPE</b>（平均絕對百分比誤差，%）｜
     <b>DA</b>（方向準確率，%，越高越好）</p>
  {df_to_html(avg_by_model, highlight_col="RMSE")}

  <h2>2. 各股票最佳模型</h2>
  {df_to_html(best_per_stock, highlight_col="RMSE")}

  <h2>3. 完整指標明細</h2>
  {df_to_html(df[['stock_id','model_name','MAE','RMSE','MAPE','DA']].round(3))}

  <h2>4. 預測圖表</h2>
  {img_blocks}

  <hr>
  <p style="font-size:12px;color:#999">
    本報告由 LSTM/report_generator.py 自動產生 · 訓練腳本：train_all.py
  </p>
</body>
</html>"""

    out_path = REPORT_DIR / "report.html"
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(html)

    # ── 產生 Markdown 摘要 ────────────────────────────────────────────────
    md_lines = [
        "# LSTM 模型訓練報告",
        f"\n產生時間：{generated_at}",
        f"\n## 模型整體表現（跨股票平均）\n",
        avg_by_model.to_markdown(index=False),
        "\n## 各股票最佳模型\n",
        best_per_stock.to_markdown(index=False),
    ]
    with open(REPORT_DIR / "report.md", "w", encoding="utf-8") as f:
        f.write("\n".join(md_lines))

    return str(out_path)


if __name__ == "__main__":
    path = generate_report()
    print(f"報告已產生：{path}")
