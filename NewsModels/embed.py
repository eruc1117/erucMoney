"""
新聞向量化（一次算完、快取）
    data/emb_minilm.npy   每則新聞 384 維（paraphrase-multilingual-MiniLM-L12-v2；標題 + 內文前 400 字）
    data/sent_zh.npy      中文財經情緒模型 P(正) − P(負)（bardsai/finance-sentiment-zh-base；下載失敗則全 NaN）

前視偏誤說明（方案文件第 05 節）：MiniLM 2021 年訓練、finance-sentiment-zh 2023 年前，測試期 2024-07 起，
模型權重不含測試期的後見之明；LLM 直接打分（news_pilot）才有那個問題。
"""
import os
import sys

import numpy as np
import pandas as pd
import torch

import nm_config as C


def main():
    news = pd.read_pickle(os.path.join(C.DATA_DIR, 'news.pkl'))
    texts = [(t or '') + '。' + (c or '')[:400] for t, c in zip(news.title, news.content)]
    dev = 'cuda' if torch.cuda.is_available() else 'cpu'
    print(f'{len(texts):,} 則，裝置 {dev}', flush=True)

    out = os.path.join(C.DATA_DIR, 'emb_minilm.npy')
    if not os.path.exists(out) or '--force' in sys.argv:
        from sentence_transformers import SentenceTransformer
        m = SentenceTransformer(C.EMB_MODEL, device=dev)
        emb = m.encode(texts, batch_size=128, show_progress_bar=True, convert_to_numpy=True, normalize_embeddings=True)
        np.save(out, emb.astype(np.float32))
        print('emb', emb.shape, flush=True)

    out2 = os.path.join(C.DATA_DIR, 'sent_zh.npy')
    if not os.path.exists(out2) or '--force' in sys.argv:
        try:
            from transformers import pipeline
            clf = pipeline('text-classification', model=C.SENT_MODEL, device=0 if dev == 'cuda' else -1,
                           truncation=True, max_length=256, top_k=None)
            scores = np.full(len(texts), np.nan, dtype=np.float32)
            short = [(t or '')[:200] for t in news.title]           # 情緒模型看標題就夠，省時間
            B = 64
            for i in range(0, len(short), B):
                res = clf(short[i:i + B], batch_size=B)
                for j, r in enumerate(res):
                    d = {x['label'].lower(): x['score'] for x in r}
                    scores[i + j] = d.get('positive', 0) - d.get('negative', 0)
                if i % (B * 50) == 0:
                    print(f'  sent {i:,}/{len(short):,}', flush=True)
            np.save(out2, scores)
            print('sent_zh 完成，非 NaN', int(np.isfinite(scores).sum()), flush=True)
        except Exception as e:      # noqa: BLE001
            print(f'中文財經情緒模型不可用，跳過：{e}', flush=True)
            np.save(out2, np.full(len(texts), np.nan, dtype=np.float32))


if __name__ == '__main__':
    main()
