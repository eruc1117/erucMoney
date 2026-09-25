"""
模型登記表：每個模型是一個函式 fn(data, tr, te, label) → 測試樣本的 P(上漲)。
tr / te 是 samples 的列索引（numpy int array）。所有模型只看 tr 的資料擬合（TF-IDF、PCA、標準化都在 fold 內重做）。

論文對應（詳見 AI/Doc/NewsModels.md）
    tfidf_*         Schumaker & Chen 2009 AZFinText：文字袋 + 線性分類器
    dict_xgb        Tetlock 2007 字典情緒 + 樹模型（現有 M2 的做法）
    emb_*           Sentence-BERT（Reimers 2019）日級平均向量 + 線性／樹
    sentzh_xgb      FinBERT 路線（Araci 2019；FinBERT-LSTM 2024）的中文版：預訓練財經情緒分數當特徵
    fused_lgbm      特徵融合（情緒統計 + 注意力 + 向量 PCA + 價格）
    mlp_fused       多模態 MLP
    gru_price       純價格 GRU（對照）
    stocknet_lite   Xu & Cohen 2018 StockNet：文字 + 價格 的時序編碼 + 時間注意力（去掉 VAE）
    han             Hu et al. 2018 Hybrid Attention Networks：新聞層注意力 + 日層注意力 + GRU
    ding_cnn        Ding et al. 2015：事件向量的短／中／長期 CNN
    transformer     Transformer encoder 時序融合（Sawhney 2020 / TFT 精神）
"""
import math
import os
import random
from datetime import date

import numpy as np
import pandas as pd

import nm_config as C

PRICE_COLS = ['r1', 'ex1', 'ex2', 'ex5', 'ex10', 'ex20', 'mkt1', 'mkt5', 'vol20', 'rng1', 'rng5', 'vr', 'ex60']
DICT_COLS = ['n_log', 'sent_mean', 'sent_min', 'sent_max', 'sent_w', 'n_tier1', 'n_mops', 'n_solo', 'attn', 'has_news']
SEQ_MAX = 30


# ═══════════════════════════════ 資料容器 ═══════════════════════════════
class Data:
    def __init__(self):
        D = C.DATA_DIR
        self.samples = pd.read_pickle(os.path.join(D, 'samples.pkl'))
        self.panel = pd.read_pickle(os.path.join(D, 'panel.pkl')).reset_index(drop=True)
        self.news = pd.read_pickle(os.path.join(D, 'news.pkl')).reset_index(drop=True)
        self.open_days = pd.read_pickle(os.path.join(D, 'open_days.pkl'))
        self.emb = np.load(os.path.join(D, 'emb_minilm.npy')) if os.path.exists(os.path.join(D, 'emb_minilm.npy')) else None
        sz = os.path.join(D, 'sent_zh.npy')
        self.sent_zh = np.load(sz) if os.path.exists(sz) else None
        if self.sent_zh is not None and not np.isfinite(self.sent_zh).any():
            self.sent_zh = None
        self.news_row = {int(i): r for r, i in enumerate(self.news.id.values)}

        # panel 派生欄位
        p = self.panel
        p['n_log'] = np.log1p(p.n)
        p['has_news'] = (p.n > 0).astype(float)
        self.panel_pos = {(s, d): i for i, (s, d) in enumerate(zip(p.stock_id.values, p.date.values))}
        self.samples['prow'] = [self.panel_pos[(s, d)] for s, d in zip(self.samples.stock_id, self.samples.date)]
        self.samples['n_log'] = np.log1p(self.samples.n)
        self.samples['has_news'] = 1.0
        # 波動標籤 v1：隔日 |超額報酬| 是否超過該股近 20 日日波動的 0.8 倍（事件研究說新聞先預測波動、再預測方向）
        self.samples['fwd_v1'] = self.samples.fwd_y1.abs() - 0.8 * self.samples.vol20
        self.samples['v1'] = (self.samples.fwd_v1 > 0).astype(int)

        # 每個 panel 列的「當日新聞向量均值」與「新聞列清單」（HAN 用）
        self._day_emb = None
        self._day_news = None
        self._seq_idx = None
        self._docs = None
        self._day_sentzh = None

    # ── 日級向量 ──
    def day_emb(self) -> np.ndarray:
        if self._day_emb is None:
            E = np.zeros((len(self.panel), self.emb.shape[1]), dtype=np.float32)
            for i, ids in enumerate(self.panel.news_ids.values):
                rows = [self.news_row[j] for j in ids if j in self.news_row]
                if rows:
                    E[i] = self.emb[rows].mean(axis=0)
            self._day_emb = E
        return self._day_emb

    def day_sentzh(self) -> np.ndarray:
        """每個 panel 列：sent_zh 的 mean/min/max（無模型時全 0）。"""
        if self._day_sentzh is None:
            S = np.zeros((len(self.panel), 3), dtype=np.float32)
            if self.sent_zh is not None:
                for i, ids in enumerate(self.panel.news_ids.values):
                    v = [self.sent_zh[self.news_row[j]] for j in ids if j in self.news_row]
                    v = [x for x in v if np.isfinite(x)]
                    if v:
                        S[i] = (np.mean(v), np.min(v), np.max(v))
            self._day_sentzh = S
        return self._day_sentzh

    def day_news(self) -> list:
        """每個 panel 列：最多 MAX_NEWS_PER_DAY 個新聞列索引（tier 高、內文長者優先）。"""
        if self._day_news is None:
            out = []
            tier = self.news.tier.values
            ln = self.news.content.str.len().fillna(0).values
            for ids in self.panel.news_ids.values:
                rows = [self.news_row[j] for j in ids if j in self.news_row]
                rows.sort(key=lambda r: (tier[r], -ln[r]))
                out.append(rows[:C.MAX_NEWS_PER_DAY])
            self._day_news = out
        return self._day_news

    def seq_idx(self) -> np.ndarray:
        """samples × SEQ_MAX：往前 SEQ_MAX 個交易日的 panel 列索引（含當日在最後一格；缺 → -1）。"""
        if self._seq_idx is None:
            p = self.panel
            by_stock = {}
            for s, g in p.groupby('stock_id'):
                by_stock[s] = (g.date.values, g.index.values)
            idx = np.full((len(self.samples), SEQ_MAX), -1, dtype=np.int64)
            for i, (s, d) in enumerate(zip(self.samples.stock_id.values, self.samples.date.values)):
                dates, rows = by_stock[s]
                k = np.searchsorted(dates, d, side='right')          # 位置 k-1 是當日
                lo = max(0, k - SEQ_MAX)
                seg = rows[lo:k]
                idx[i, SEQ_MAX - len(seg):] = seg
            self._seq_idx = idx
        return self._seq_idx

    def docs(self) -> list:
        """每個樣本的文字袋（jieba 斷詞後以空白連接）：當日新聞標題 + 內文前 150 字。"""
        if self._docs is None:
            import jieba
            jieba.setLogLevel(60)
            title = self.news.title.fillna('').values
            content = self.news.content.fillna('').values
            cache = {}
            out = []
            for ids in self.samples.news_ids.values:
                parts = []
                for j in ids:
                    r = self.news_row.get(j)
                    if r is None:
                        continue
                    if r not in cache:
                        cache[r] = ' '.join(w for w in jieba.lcut(title[r] + '。' + content[r][:150]) if w.strip())
                    parts.append(cache[r])
                out.append(' '.join(parts))
            self._docs = out
        return self._docs

    # ── 常用特徵矩陣 ──
    def X_price(self, idx) -> np.ndarray:
        return self.samples.loc[idx, PRICE_COLS].values.astype(np.float32)

    def X_dict(self, idx) -> np.ndarray:
        return self.samples.loc[idx, DICT_COLS].values.astype(np.float32)

    def X_emb(self, idx, how='meanmax') -> np.ndarray:
        rows_list = [[self.news_row[j] for j in ids if j in self.news_row] for ids in self.samples.news_ids.values[idx]]
        M = np.zeros((len(idx), self.emb.shape[1] * (2 if how == 'meanmax' else 1)), dtype=np.float32)
        for k, rows in enumerate(rows_list):
            if rows:
                e = self.emb[rows]
                M[k, :self.emb.shape[1]] = e.mean(axis=0)
                if how == 'meanmax':
                    M[k, self.emb.shape[1]:] = e.max(axis=0)
        return M

    def X_sentzh(self, idx) -> np.ndarray:
        return self.day_sentzh()[self.samples.prow.values[idx]]

    def y(self, idx, label) -> np.ndarray:
        return self.samples[label].values[idx].astype(np.float32)


# ═══════════════════════════════ 傳統模型 ═══════════════════════════════
def _scale(Xtr, Xte):
    from sklearn.preprocessing import StandardScaler
    sc = StandardScaler().fit(Xtr)
    return sc.transform(Xtr), sc.transform(Xte)


def m_majority(d: Data, tr, te, label):
    return np.full(len(te), d.y(tr, label).mean(), dtype=np.float32)


def m_persist(d: Data, tr, te, label):
    ex1 = d.samples.ex1.values[te]
    return (0.5 + 0.4 * np.sign(ex1)).astype(np.float32)


def m_price_logreg(d, tr, te, label):
    from sklearn.linear_model import LogisticRegression
    a, b = _scale(d.X_price(tr), d.X_price(te))
    return LogisticRegression(C=0.5, max_iter=500).fit(a, d.y(tr, label)).predict_proba(b)[:, 1]


def _xgb(Xtr, ytr, Xte, n=400, depth=4, lr=0.03):
    import xgboost as xgb
    m = xgb.XGBClassifier(n_estimators=n, max_depth=depth, learning_rate=lr, subsample=0.8, colsample_bytree=0.8,
                          reg_lambda=1.0, min_child_weight=5, tree_method='hist', random_state=C.SEED, n_jobs=8, verbosity=0)
    return m.fit(Xtr, ytr).predict_proba(Xte)[:, 1]


def m_dict_xgb(d, tr, te, label):
    Xtr = np.hstack([d.X_price(tr), d.X_dict(tr)])
    Xte = np.hstack([d.X_price(te), d.X_dict(te)])
    return _xgb(Xtr, d.y(tr, label), Xte)


def _tfidf(d, tr, te):
    from sklearn.feature_extraction.text import TfidfVectorizer
    docs = d.docs()
    v = TfidfVectorizer(ngram_range=(1, 2), min_df=3, max_features=60000, sublinear_tf=True, token_pattern=r'(?u)\b\w+\b')
    A = v.fit_transform([docs[i] for i in tr])
    B = v.transform([docs[i] for i in te])
    return A, B


def m_tfidf_logreg(d, tr, te, label):
    from sklearn.linear_model import LogisticRegression
    A, B = _tfidf(d, tr, te)
    return LogisticRegression(C=0.3, max_iter=1000).fit(A, d.y(tr, label)).predict_proba(B)[:, 1]


def m_tfidf_nb(d, tr, te, label):
    from sklearn.naive_bayes import MultinomialNB
    A, B = _tfidf(d, tr, te)
    return MultinomialNB(alpha=0.3).fit(A, d.y(tr, label)).predict_proba(B)[:, 1]


def m_tfidf_svm(d, tr, te, label):
    from sklearn.svm import LinearSVC
    A, B = _tfidf(d, tr, te)
    s = LinearSVC(C=0.1).fit(A, d.y(tr, label)).decision_function(B)
    return 1 / (1 + np.exp(-2 * s))


def m_emb_logreg(d, tr, te, label):
    from sklearn.linear_model import LogisticRegression
    a, b = _scale(np.hstack([d.X_emb(tr), d.X_price(tr)]), np.hstack([d.X_emb(te), d.X_price(te)]))
    return LogisticRegression(C=0.05, max_iter=1000).fit(a, d.y(tr, label)).predict_proba(b)[:, 1]


def m_emb_xgb(d, tr, te, label):
    Xtr = np.hstack([d.X_emb(tr, 'mean'), d.X_price(tr), d.X_dict(tr)])
    Xte = np.hstack([d.X_emb(te, 'mean'), d.X_price(te), d.X_dict(te)])
    return _xgb(Xtr, d.y(tr, label), Xte, n=500, depth=4, lr=0.03)


def m_sentzh_xgb(d, tr, te, label):
    if d.sent_zh is None:
        raise RuntimeError('沒有中文財經情緒分數（sent_zh.npy 全 NaN）')
    Xtr = np.hstack([d.X_sentzh(tr), d.X_price(tr), d.X_dict(tr)])
    Xte = np.hstack([d.X_sentzh(te), d.X_price(te), d.X_dict(te)])
    return _xgb(Xtr, d.y(tr, label), Xte)


def m_fused_lgbm(d, tr, te, label):
    import lightgbm as lgb
    from sklearn.decomposition import PCA
    pca = PCA(32, random_state=C.SEED).fit(d.X_emb(tr, 'mean'))
    Xtr = np.hstack([pca.transform(d.X_emb(tr, 'mean')), d.X_price(tr), d.X_dict(tr), d.X_sentzh(tr)])
    Xte = np.hstack([pca.transform(d.X_emb(te, 'mean')), d.X_price(te), d.X_dict(te), d.X_sentzh(te)])
    m = lgb.LGBMClassifier(n_estimators=600, learning_rate=0.02, num_leaves=15, min_child_samples=40, subsample=0.8,
                           subsample_freq=1, colsample_bytree=0.7, reg_lambda=2.0, random_state=C.SEED, verbose=-1, n_jobs=8)
    return m.fit(Xtr, d.y(tr, label)).predict_proba(Xte)[:, 1]


# ═══════════════════════════════ 深度模型 ═══════════════════════════════
def _torch():
    import torch
    torch.manual_seed(C.SEED)
    random.seed(C.SEED)
    np.random.seed(C.SEED)
    return torch, ('cuda' if torch.cuda.is_available() else 'cpu')


class _SeqBatch:
    """把樣本索引變成序列張量：price+dict 特徵 (B,L,F)、日向量 (B,L,E)、遮罩 (B,L)、HAN 用的新聞袋 (B,L,K,E)。"""

    def __init__(self, d: Data, L: int, need_bag: bool = False, need_emb: bool = True):
        self.d, self.L, self.need_bag, self.need_emb = d, L, need_bag, need_emb
        p = d.panel
        self.pf = p[PRICE_COLS + DICT_COLS].fillna(0).values.astype(np.float32)
        self.pf_mu = None
        self.pf_sd = None
        self.E = d.day_emb() if need_emb else None
        self.bags = d.day_news() if need_bag else None
        self.seq = d.seq_idx()[:, SEQ_MAX - L:]

    def fit_scaler(self, tr):
        rows = self.seq[tr].ravel()
        rows = rows[rows >= 0]
        x = self.pf[rows]
        self.pf_mu, self.pf_sd = x.mean(axis=0), x.std(axis=0) + 1e-6

    def __call__(self, idx):
        import torch
        S = self.seq[idx]
        mask = S >= 0
        Sc = np.where(mask, S, 0)
        X = (self.pf[Sc] - self.pf_mu) / self.pf_sd
        X[~mask] = 0
        out = {'x': torch.tensor(X), 'mask': torch.tensor(mask)}
        if self.need_emb:
            out['e'] = torch.tensor(self.E[Sc] * mask[..., None])
        if self.need_bag:
            K = C.MAX_NEWS_PER_DAY
            B, L = S.shape
            bag = np.zeros((B, L, K, self.d.emb.shape[1]), dtype=np.float32)
            bmask = np.zeros((B, L, K), dtype=bool)
            for i in range(B):
                for j in range(L):
                    if mask[i, j]:
                        rows = self.bags[S[i, j]]
                        if rows:
                            bag[i, j, :len(rows)] = self.d.emb[rows]
                            bmask[i, j, :len(rows)] = True
            out['bag'] = torch.tensor(bag)
            out['bmask'] = torch.tensor(bmask)
        return out


def _train_torch(model, make_batch, d: Data, tr, te, label, epochs=20, bs=256, lr=1e-3, patience=3):
    """時間序切最後 10% 的訓練樣本當驗證集做早停。"""
    torch, dev = _torch()
    model = model.to(dev)
    dates = d.samples.date.values[tr]
    cut = np.quantile(pd.to_datetime(dates).astype('int64'), 0.9)
    va = tr[pd.to_datetime(dates).astype('int64') > cut]
    tr2 = tr[pd.to_datetime(dates).astype('int64') <= cut]
    y = d.y(np.arange(len(d.samples)), label)
    opt = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    lossf = torch.nn.BCEWithLogitsLoss()

    def run(idx, train):
        model.train(train)
        tot, n = 0.0, 0
        order = np.random.permutation(idx) if train else idx
        for s in range(0, len(order), bs):
            b = order[s:s + bs]
            batch = {k: v.to(dev) for k, v in make_batch(b).items()}
            yy = torch.tensor(y[b]).to(dev)
            with torch.set_grad_enabled(train):
                logit = model(batch)
                loss = lossf(logit, yy)
                if train:
                    opt.zero_grad()
                    loss.backward()
                    torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
                    opt.step()
            tot += float(loss) * len(b)
            n += len(b)
        return tot / max(n, 1)

    best, best_state, bad = 1e9, None, 0
    for ep in range(epochs):
        run(tr2, True)
        vl = run(va, False)
        if vl < best - 1e-4:
            best, bad = vl, 0
            best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
        else:
            bad += 1
            if bad >= patience:
                break
    if best_state:
        model.load_state_dict(best_state)
    model.eval()
    out = []
    with torch.no_grad():
        for s in range(0, len(te), 1024):
            b = te[s:s + 1024]
            batch = {k: v.to(dev) for k, v in make_batch(b).items()}
            out.append(torch.sigmoid(model(batch)).cpu().numpy())
    return np.concatenate(out)


def _nn():
    import torch.nn as nn
    return nn


class MLPFused:
    """多模態 MLP：日向量 mean/max + 價格 + 字典特徵。"""
    def __call__(self, d, tr, te, label):
        torch, dev = _torch()
        nn = _nn()
        a, b = _scale(np.hstack([d.X_emb(tr), d.X_price(tr), d.X_dict(tr)]), np.hstack([d.X_emb(te), d.X_price(te), d.X_dict(te)]))
        allX = np.zeros((len(d.samples), a.shape[1]), dtype=np.float32)
        allX[tr], allX[te] = a, b
        net = nn.Sequential(nn.Linear(a.shape[1], 256), nn.GELU(), nn.Dropout(0.3), nn.Linear(256, 64), nn.GELU(),
                            nn.Dropout(0.2), nn.Linear(64, 1))

        class M(nn.Module):
            def __init__(self):
                super().__init__()
                self.net = net

            def forward(self, batch):
                return self.net(batch['x']).squeeze(-1)

        mk = lambda idx: {'x': torch.tensor(allX[idx])}
        return _train_torch(M(), mk, d, tr, te, label)


class GRUPrice:
    def __init__(self, L=C.SEQ_LEN):
        self.L = L

    def __call__(self, d, tr, te, label):
        torch, dev = _torch()
        nn = _nn()
        sb = _SeqBatch(d, self.L, need_emb=False)
        sb.fit_scaler(tr)
        F = len(PRICE_COLS)

        class M(nn.Module):
            def __init__(self):
                super().__init__()
                self.gru = nn.GRU(F, 64, batch_first=True)
                self.head = nn.Sequential(nn.Dropout(0.2), nn.Linear(64, 1))

            def forward(self, b):
                h, _ = self.gru(b['x'][..., :F])
                return self.head(h[:, -1]).squeeze(-1)

        return _train_torch(M(), sb, d, tr, te, label)


class StockNetLite:
    """Xu & Cohen 2018 的骨架：每日 [文字向量, 價格] → GRU → 時間注意力 → 預測。去掉 VAE 與 tweet 層。"""
    def __init__(self, L=C.SEQ_LEN):
        self.L = L

    def __call__(self, d, tr, te, label):
        torch, dev = _torch()
        nn = _nn()
        sb = _SeqBatch(d, self.L)
        sb.fit_scaler(tr)
        F, E = len(PRICE_COLS) + len(DICT_COLS), d.emb.shape[1]

        class M(nn.Module):
            def __init__(self):
                super().__init__()
                self.tproj = nn.Sequential(nn.Linear(E, 64), nn.Tanh(), nn.Dropout(0.3))
                self.gru = nn.GRU(64 + F, 96, batch_first=True, bidirectional=True)
                self.att = nn.Linear(192, 1)
                self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(192 + F, 1))

            def forward(self, b):
                z = torch.cat([self.tproj(b['e']), b['x']], dim=-1)
                h, _ = self.gru(z)
                a = self.att(h).squeeze(-1).masked_fill(~b['mask'], -1e9)
                w = torch.softmax(a, dim=1).unsqueeze(-1)
                ctx = (h * w).sum(1)
                return self.head(torch.cat([ctx, b['x'][:, -1]], dim=-1)).squeeze(-1)

        return _train_torch(M(), sb, d, tr, te, label, lr=5e-4)


class HAN:
    """Hu et al. 2018：新聞層注意力（同一天多則新聞加權）→ 日層 bi-GRU + 時間注意力 → 預測。"""
    def __init__(self, L=C.SEQ_LEN):
        self.L = L

    def __call__(self, d, tr, te, label):
        torch, dev = _torch()
        nn = _nn()
        sb = _SeqBatch(d, self.L, need_bag=True, need_emb=False)
        sb.fit_scaler(tr)
        F, E = len(PRICE_COLS) + len(DICT_COLS), d.emb.shape[1]

        class M(nn.Module):
            def __init__(self):
                super().__init__()
                self.nproj = nn.Sequential(nn.Linear(E, 96), nn.Tanh(), nn.Dropout(0.3))
                self.natt = nn.Linear(96, 1)
                self.gru = nn.GRU(96 + F, 96, batch_first=True, bidirectional=True)
                self.datt = nn.Linear(192, 1)
                self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(192, 1))

            def forward(self, b):
                u = self.nproj(b['bag'])                                     # B,L,K,96
                a = self.natt(u).squeeze(-1).masked_fill(~b['bmask'], -1e9)  # B,L,K
                w = torch.softmax(a, dim=-1).unsqueeze(-1)
                dayv = (u * w).sum(2) * b['bmask'].any(-1, keepdim=True)     # 無新聞的日子 → 0
                h, _ = self.gru(torch.cat([dayv, b['x']], dim=-1))
                a2 = self.datt(h).squeeze(-1).masked_fill(~b['mask'], -1e9)
                w2 = torch.softmax(a2, dim=1).unsqueeze(-1)
                return self.head((h * w2).sum(1)).squeeze(-1)

        return _train_torch(M(), sb, d, tr, te, label, bs=128, lr=5e-4)


class DingCNN:
    """Ding et al. 2015：事件向量的短期（當日）、中期（7 日）、長期（30 日）三路，中長期用卷積 + 最大池化。"""
    def __call__(self, d, tr, te, label):
        torch, dev = _torch()
        nn = _nn()
        sb = _SeqBatch(d, 30)
        sb.fit_scaler(tr)
        F, E = len(PRICE_COLS) + len(DICT_COLS), d.emb.shape[1]

        class M(nn.Module):
            def __init__(self):
                super().__init__()
                self.proj = nn.Sequential(nn.Linear(E, 64), nn.Tanh())
                self.mid = nn.Conv1d(64, 64, 3, padding=1)
                self.long = nn.Conv1d(64, 64, 3, padding=1)
                self.head = nn.Sequential(nn.Dropout(0.3), nn.Linear(64 * 3 + F, 64), nn.GELU(), nn.Linear(64, 1))

            def forward(self, b):
                z = self.proj(b['e'])                    # B,30,64
                short = z[:, -1]
                mid = torch.relu(self.mid(z[:, -7:].transpose(1, 2))).max(-1).values
                long = torch.relu(self.long(z.transpose(1, 2))).max(-1).values
                return self.head(torch.cat([short, mid, long, b['x'][:, -1]], dim=-1)).squeeze(-1)

        return _train_torch(M(), sb, d, tr, te, label)


class TransformerFused:
    def __init__(self, L=C.SEQ_LEN):
        self.L = L

    def __call__(self, d, tr, te, label):
        torch, dev = _torch()
        nn = _nn()
        sb = _SeqBatch(d, self.L)
        sb.fit_scaler(tr)
        F, E, L = len(PRICE_COLS) + len(DICT_COLS), d.emb.shape[1], self.L

        class M(nn.Module):
            def __init__(self):
                super().__init__()
                self.inp = nn.Linear(E + F, 128)
                self.pos = nn.Parameter(torch.zeros(1, L, 128))
                layer = nn.TransformerEncoderLayer(128, 4, 256, dropout=0.2, batch_first=True)
                self.enc = nn.TransformerEncoder(layer, 2)
                self.head = nn.Sequential(nn.LayerNorm(128), nn.Dropout(0.2), nn.Linear(128, 1))

            def forward(self, b):
                z = self.inp(torch.cat([b['e'], b['x']], dim=-1)) + self.pos
                h = self.enc(z, src_key_padding_mask=~b['mask'])
                return self.head(h[:, -1]).squeeze(-1)

        return _train_torch(M(), sb, d, tr, te, label, lr=3e-4)


def _fused(d, idx):
    return np.hstack([d.X_emb(idx, 'mean'), d.X_price(idx), d.X_dict(idx), d.X_sentzh(idx)])


def m_rf_fused(d, tr, te, label):
    from sklearn.ensemble import RandomForestClassifier
    m = RandomForestClassifier(n_estimators=400, max_depth=8, min_samples_leaf=30, max_features=0.3, n_jobs=8, random_state=C.SEED)
    return m.fit(_fused(d, tr), d.y(tr, label)).predict_proba(_fused(d, te))[:, 1]


def m_et_fused(d, tr, te, label):
    from sklearn.ensemble import ExtraTreesClassifier
    m = ExtraTreesClassifier(n_estimators=500, max_depth=10, min_samples_leaf=30, max_features=0.3, n_jobs=8, random_state=C.SEED)
    return m.fit(_fused(d, tr), d.y(tr, label)).predict_proba(_fused(d, te))[:, 1]


def m_lr_fused(d, tr, te, label):
    from sklearn.linear_model import LogisticRegression
    a, b = _scale(_fused(d, tr), _fused(d, te))
    return LogisticRegression(C=0.02, max_iter=1000).fit(a, d.y(tr, label)).predict_proba(b)[:, 1]


def m_emb_only_xgb(d, tr, te, label):
    """只有新聞向量、沒有價格——量新聞本身的訊號。"""
    return _xgb(d.X_emb(tr, 'mean'), d.y(tr, label), d.X_emb(te, 'mean'), n=400, depth=4, lr=0.03)


def m_news_only_xgb(d, tr, te, label):
    """只有新聞統計（字典情緒、則數、注意力、中文財經情緒），沒有價格與向量。"""
    Xtr = np.hstack([d.X_dict(tr), d.X_sentzh(tr)])
    Xte = np.hstack([d.X_dict(te), d.X_sentzh(te)])
    return _xgb(Xtr, d.y(tr, label), Xte)


def m_attn_logreg(d, tr, te, label):
    """Da, Engelberg & Gao 2011 異常注意力 + 則數 + 價格 → Logistic。"""
    from sklearn.linear_model import LogisticRegression
    cols = ['n_log', 'attn', 'n_tier1', 'n_mops']
    a, b = _scale(np.hstack([d.samples.loc[tr, cols].values, d.X_price(tr)]), np.hstack([d.samples.loc[te, cols].values, d.X_price(te)]))
    return LogisticRegression(C=0.5, max_iter=500).fit(a, d.y(tr, label)).predict_proba(b)[:, 1]


# ═══════════════════════════════ 登記表 ═══════════════════════════════
REGISTRY = [
    # name, 說明, 論文／出處, fn, 需要 emb?
    ('majority', '多數類', '基準', m_majority, False),
    ('persist', '昨日超額報酬延續', '基準', m_persist, False),
    ('price_logreg', '純價格 Logistic', '基準（動能／波動／量比）', m_price_logreg, False),
    ('gru_price', '純價格 GRU（10 日）', '基準', GRUPrice(), False),
    ('dict_xgb', '字典情緒 + 價格 → XGBoost', 'Tetlock 2007 字典情緒；現有 M2', m_dict_xgb, False),
    ('tfidf_logreg', 'TF-IDF(jieba 1-2gram) + Logistic', 'Schumaker & Chen 2009 AZFinText', m_tfidf_logreg, False),
    ('tfidf_nb', 'TF-IDF + Naive Bayes', '文字分類基線', m_tfidf_nb, False),
    ('tfidf_svm', 'TF-IDF + LinearSVC', 'Schumaker & Chen 2009（SVR→SVC）', m_tfidf_svm, False),
    ('emb_logreg', 'MiniLM 日向量 mean/max + 價格 → Logistic', 'Sentence-BERT 2019', m_emb_logreg, True),
    ('emb_xgb', 'MiniLM 日向量 + 價格 + 字典 → XGBoost', 'BERT 向量 + 樹（arXiv 2107.08721 精神）', m_emb_xgb, True),
    ('sentzh_xgb', '中文財經情緒模型分數 + 價格 → XGBoost', 'FinBERT 路線（Araci 2019；FinBERT-LSTM 2024）', m_sentzh_xgb, False),
    ('fused_lgbm', '向量 PCA32 + 情緒 + 注意力 + 價格 → LightGBM', '特徵融合', m_fused_lgbm, True),
    ('mlp_fused', '多模態 MLP', '多模態融合', MLPFused(), True),
    ('stocknet_lite', 'StockNet-lite：文字+價格 bi-GRU + 時間注意力', 'Xu & Cohen 2018（去 VAE）', StockNetLite(), True),
    ('han', 'HAN：新聞層注意力 + 日層 bi-GRU 注意力', 'Hu et al. 2018 WSDM', HAN(), True),
    ('ding_cnn', '事件向量 短／中／長期 CNN', 'Ding et al. 2015 IJCAI', DingCNN(), True),
    ('transformer', 'Transformer encoder 時序融合（10 日）', 'Sawhney 2020 / 時序 Transformer', TransformerFused(), True),
    # 第二批：消融與變體
    ('news_only_xgb', '只用新聞統計（無價格、無向量）→ XGBoost', '消融：新聞本身', m_news_only_xgb, False),
    ('emb_only_xgb', '只用 MiniLM 日向量（無價格）→ XGBoost', '消融：文字向量本身', m_emb_only_xgb, True),
    ('attn_logreg', '異常注意力 + 則數 + 價格 → Logistic', 'Da, Engelberg & Gao 2011', m_attn_logreg, False),
    ('lr_fused', '全部特徵（向量+價格+字典+情緒）→ Logistic', '線性融合', m_lr_fused, True),
    ('rf_fused', '全部特徵 → Random Forest', '樹融合（M3 風格）', m_rf_fused, True),
    ('et_fused', '全部特徵 → ExtraTrees', '樹融合', m_et_fused, True),
    ('han_L5', 'HAN，回看 5 日', 'Hu et al. 2018 變體', HAN(L=5), True),
    ('stocknet_L20', 'StockNet-lite，回看 20 日', 'Xu & Cohen 2018 變體', StockNetLite(L=20), True),
    ('transformer_L20', 'Transformer，回看 20 日', '變體', TransformerFused(L=20), True),
    ('gru_price_L20', '純價格 GRU，回看 20 日', '基準變體', GRUPrice(L=20), False),
]
