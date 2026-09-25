"""
模型目錄（Iteration 31）
────────────────────────
在此之前，「有哪些模型」這件事散落在四個地方各說各話：

    Prediction.jsx 的 MODELS 常數      10 個 LSTM
    roles.py 的 ROLES                  7 個角色（其中只有 1 個 LSTM）
    cash_allocator.py 的 import        gap / range / risk / m3
    model_registry.MODEL_TYPES         版本管理用的清單

結果是「預測比對」頁密集監控 10 個已證實沒有 edge 的 LSTM，而真正在做買賣決策的
四個模型完全不在那一頁上；閒置資金一個 LSTM 都沒用到，投票也只用了 m02_stacked。

本模組是**唯一的事實來源**：每個模型宣告自己預測什麼、用哪些資料、
可以出現在哪些頁面、在投票裡算方向還是閘門、以及它的實測可信度。
前端的模型選擇器、投票引擎、資金配置、模型版本頁全部讀這一份。

## 欄位語意

kind        direction  進投票方向計分（有權重）
            gate       不投方向，只調整部位／停損／進場價
            magnitude  量級預測，供閘門或資訊呈現
            reference  純參考，不參與任何決策

pages       這個模型可以出現在哪些頁面。`selectable` 的頁面會顯示勾選器。

credibility proven       有走查實證且優於天真基準
            weak         有實證但邊際或有期間依賴
            none         實測等同或劣於天真基準
            unvalidated  尚未經回測

**credibility 直接顯示給使用者。** 使用者有權知道哪些意見有實測支撐。
"""

MODEL_KIND_LABEL = {
    'direction': '方向訊號', 'gate': '閘門／調節',
    'magnitude': '量級預測', 'reference': '參考',
}

CREDIBILITY_LABEL = {
    'proven': '已驗證', 'weak': '邊際', 'none': '無 edge', 'unvalidated': '未驗證',
}

# 頁面代號與 Screen/src/App.jsx 的 tab key 一致
PAGE_KEYS = ['overview', 'analysis', 'predict', 'compare',
             'voting', 'idlecash', 'holdings', 'models', 'us',
             'predict_us', 'compare_us']     # 趨勢預測／預測比對切到美股時的頁面代號

CATALOG = {
    # ── 決策主力：量級與閘門 ───────────────────────────────────────────────
    'gap': {
        'label': '開盤跳空預測', 'icon': '🌙', 'kind': 'gate',
        'registry_type': 'gap', 'role_key': 'gap',
        'target': '次一交易日開盤跳空幅度', 'horizon_days': 1,
        'blocks': ['price', 'chip', 'cs', 'market', 'us', 'night'],
        'credibility': 'proven',
        'metric': '走查相關 0.6935、方向 72.24%（Iteration 28/30）',
        'note': '不投方向——跳空在開盤瞬間發生、事後無法交易。'
                '用途是「明天大概開在哪」，據以調整掛單價位',
        'pages': ['voting', 'idlecash', 'analysis', 'overview', 'models'],
        'selectable': ['voting', 'idlecash'],
        'default': True,
    },
    'range': {
        'label': '週振幅預測', 'icon': '📐', 'kind': 'gate',
        'registry_type': 'range', 'role_key': 'swing',
        'target': '未來 5 日 (最高−最低) ÷ 今日收盤', 'horizon_days': 5,
        'blocks': ['price', 'chip', 'cs', 'market', 'night', 'intl'],
        'credibility': 'proven',
        'metric': '走查排序相關 0.6537、lift 1.99（Iteration 19/30）',
        'note': '振幅大不代表會漲，只回答「有沒有價差可做」',
        'pages': ['voting', 'idlecash', 'analysis', 'models'],
        'selectable': ['voting', 'idlecash'],
        'default': True,
    },
    'volatility': {
        'label': '波動率（風險模組）', 'icon': '🛡️', 'kind': 'gate',
        'registry_type': 'volatility', 'role_key': 'risk',
        'target': '未來 20 日已實現波動率', 'horizon_days': 20,
        'blocks': ['price', 'chip', 'cs', 'market', 'night'],
        'credibility': 'proven',
        'metric': '走查相關 0.606、R²(log) 0.483，全面優於 EWMA（Iteration 13/30）',
        'note': '不投方向，只決定押多少與停損放哪',
        'pages': ['voting', 'idlecash', 'analysis', 'holdings', 'models'],
        'selectable': ['voting', 'idlecash'],
        'default': True,
    },
    'volume': {
        'label': '成交量預測（流動性）', 'icon': '💧', 'kind': 'gate',
        'registry_type': 'volume', 'role_key': 'liquidity',
        'target': '未來 5 日均量 ÷ 目前 20 日均量', 'horizon_days': 5,
        'blocks': ['price', 'chip', 'cs', 'market'],
        'credibility': 'proven',
        'metric': '走查排序相關 0.4823、持續性基準 0.3588（Iteration 31）',
        'note': '新增於 Iteration 31。回答「這檔吃不吃得下這筆錢」，'
                '量能萎縮時縮小部位。與漲跌無關，不進方向計分',
        'pages': ['voting', 'idlecash', 'analysis', 'models'],
        'selectable': ['voting', 'idlecash'],
        'default': True,
    },

    'us_gap': {
        'label': '美股開盤跳空預測', 'icon': '🇺🇸', 'kind': 'gate',
        'registry_type': 'us_gap', 'role_key': None,
        'target': '美股次一場開盤 ÷ 前收 − 1', 'horizon_days': 1,
        'blocks': ['us_own', 'us_market', 'tw_day', 'asia'],
        'credibility': 'proven',
        'metric': '走查相關 0.2763、方向 61.32%（多數類別 55.33%）（Iteration 32）',
        'note': '新增於 Iteration 32，方向與台股跳空模型相反：拿台股與韓日的'
                '當日盤預測美股當晚開盤。只用美股自身歷史時相關僅 0.0085——'
                '訊號全部來自亞洲時區。跳空事後無法交易，不投方向、不進投票',
        'pages': ['us', 'models'],
        'selectable': [],
        'default': True,
    },

    # ── 方向訊號 ──────────────────────────────────────────────────────────
    'm3_chip': {
        'label': 'M3 籌碼 Random Forest', 'icon': '🏦', 'kind': 'direction',
        'registry_type': 'm3_chip', 'role_key': 'chip', 'weight': 0.55,
        'target': '未來 3 日 alpha 方向（剝離大盤 beta）', 'horizon_days': 3,
        'blocks': ['price', 'chip', 'cs', 'market'],
        'credibility': 'weak',
        'metric': '走查買進 56.87%（2012 起）；**2018 之後只有 51.53%**（Iteration 30）',
        'note': '賣出側無 edge 已被模型抑制，只會投 Buy 或 Hold。'
                '期間依賴明顯，0.55 的權重待重新檢討',
        'pages': ['voting', 'idlecash', 'analysis', 'models'],
        'selectable': ['voting', 'idlecash'],
        'default': True,
    },
    'm2_news': {
        'label': 'M2 新聞情緒規則引擎', 'icon': '📰', 'kind': 'direction',
        'registry_type': None, 'role_key': 'news', 'weight': 0.30,
        'target': '個股新聞情緒 → 買／賣／觀望', 'horizon_days': 3,
        'blocks': ['news'],
        'credibility': 'unvalidated',
        'metric': '無走查（新聞歷史僅數日）',
        'note': 'Iteration 10 修正「22 檔恆同訊號」的結構問題，'
                '但權重數值仍未經回測驗證',
        'pages': ['voting', 'analysis', 'models'],
        'selectable': ['voting'],
        'default': True,
    },
}

# ── LSTM：10 個各自成為一個目錄項 ──────────────────────────────────────────
# 它們的實測結論是共通的（Iteration 11：MAE 5.17~5.25 對天真基準 5.20、
# 方向 46.9~50.6%），所以 credibility 一律 none。保留在目錄裡有兩個理由：
# 一是趨勢預測／預測比對頁本來就以它們為主體，二是線上台帳要繼續累積——
# 拿掉就永遠證不出它到底行不行。
_LSTM = {
    'm01_vanilla': ('M01 Vanilla', '單特徵基準'),
    'm02_stacked': ('M02 Stacked', '3 層堆疊'),
    'm03_bidirectional': ('M03 BiLSTM', '雙向時序'),
    'm04_attention': ('M04 Attention', '關鍵步聚焦'),
    'm05_cnn_lstm': ('M05 CNN-LSTM', '局部+長程特徵'),
    'm06_multifeature': ('M06 Multi', 'OHLCV+籌碼'),
    'm07_seq2seq': ('M07 Seq2Seq', '多步直接輸出'),
    'm08_mc_dropout': ('M08 MC Dropout', '不確定性量化'),
    'm09_technical': ('M09 Technical', '20 項技術指標'),
    'm10_ensemble': ('M10 Ensemble', 'M01+M02+M03 加權'),
}
for _k, (_label, _desc) in _LSTM.items():
    CATALOG[f'lstm:{_k}'] = {
        'label': _label, 'icon': '🧠', 'kind': 'direction',
        'registry_type': f'lstm:{_k}', 'role_key': 'trend', 'weight': 0.15,
        'target': '未來 7 日逐日收盤價', 'horizon_days': 7,
        'blocks': ['price'] + (['chip'] if _k in ('m06_multifeature',) else []),
        'credibility': 'none',
        'metric': 'Iteration 11：MAE 5.17~5.25 對天真基準 5.20、方向 46.9~50.6%',
        'note': f'{_desc}。價格序列本身沒有訊號——要讓它有用得換輸入而非換架構。'
                '權重已降至 0.15，保留以累積線上紀錄',
        'pages': ['predict', 'compare', 'voting', 'analysis', 'models'],
        'selectable': ['voting'],
        'default': _k == 'm02_stacked',       # 投票預設只用 m02（歷史沿用）
    }
    # 美股：同一個模型檔、另一條台帳（見 model_registry 的 lstm_us:*）。
    # 不進投票——投票是台股的事；也不標 proven：Iteration 32 實測只用美股
    # 自身歷史的走查相關 0.0085 ≈ 0，與台股 Iteration 11 的結論一致。
    CATALOG[f'lstm_us:{_k}'] = {
        'label': f'{_label}（美股）', 'icon': '🧠', 'kind': 'reference',
        'registry_type': f'lstm_us:{_k}', 'role_key': None,
        'target': '美股未來 7 個場次逐日收盤價', 'horizon_days': 7,
        'blocks': ['us'],
        'credibility': 'none',
        'metric': 'Iteration 32：只用美股自身歷史，走查相關 0.0085、方向 50.29%（多數類別 55.48%）',
        'note': f'{_desc}。與台股同一批跨股票模型，輸入是 z-score 後的收盤價視窗，'
                '與價格尺度無關；線上成績另立台帳累積',
        'pages': ['predict_us', 'compare_us', 'models'],
        'selectable': [],
        'default': False,
    }


# ── 查詢 ────────────────────────────────────────────────────────────────────
def all_models(page: str = None, selectable_only: bool = False) -> list:
    """目錄清單，可依頁面過濾。回傳順序穩定：先閘門、再方向、最後 LSTM。"""
    order = {'gate': 0, 'magnitude': 1, 'direction': 2, 'reference': 3}
    out = []
    for key, m in CATALOG.items():
        if page and page not in m.get('pages', []):
            continue
        if selectable_only and page and page not in m.get('selectable', []):
            continue
        out.append(describe(key))
    out.sort(key=lambda x: (order.get(x['kind'], 9),
                            0 if not x['key'].startswith('lstm:') else 1,
                            x['key']))
    return out


def describe(key: str) -> dict:
    m = CATALOG.get(key)
    if not m:
        return {}
    d = dict(m)
    d['key'] = key
    d['kind_label'] = MODEL_KIND_LABEL.get(m['kind'], m['kind'])
    d['credibility_label'] = CREDIBILITY_LABEL.get(m['credibility'], m['credibility'])
    return d


def defaults(page: str) -> list:
    """某頁面的預設啟用清單。"""
    return [k for k, m in CATALOG.items()
            if page in m.get('selectable', []) and m.get('default')]


def resolve(selected, page: str) -> list:
    """
    把使用者送來的清單正規化：過濾掉不屬於本頁的、去重、保持目錄順序。
    傳 None 或空清單時回預設值——**不是回空**。
    使用者取消勾選所有模型時應該由呼叫端明確處理，而不是靜默變成「全不用」，
    否則畫面會顯示一份沒有任何依據的決策。
    """
    if not selected:
        return defaults(page)
    want = {str(s).strip() for s in selected}
    allowed = [k for k, m in CATALOG.items() if page in m.get('selectable', [])]
    keep = [k for k in allowed if k in want]
    return keep or defaults(page)


def blocks_in_use(keys) -> list:
    """這批模型合起來用到哪些資料區塊（供頁面說明「資料來源」）。"""
    out = []
    for k in keys:
        for b in CATALOG.get(k, {}).get('blocks', []):
            if b not in out:
                out.append(b)
    return out
