"""
凱基證券（KGI）介面——接口先放好，實際下單還沒接。

凱基有官方 Python 套件 `kgiapp`（PyPI；底層是 .NET Framework 4.5，Windows），要先向凱基申請 API 權限才能用。
接上去要做的事（接的時候再填）：
    1. pip install kgiapp；環境變數 KGI_ID、KGI_PASSWORD、KGI_BRANCH、KGI_ACCOUNT（.env，不進版控）
    2. execute()：登入 → 對每張委託送零股限價單（盤後零股或盤中零股，依 order 的 session）→ 拿委託書號存 broker_ref
    3. 成交回報：當天收盤後查回報，把 filled_shares／filled_price 填回 trading_orders，並照紙上的格式寫一筆進 portfolio_paper_trades（或另開 live 表）
    4. positions()／cash()：查庫存與可用餘額，引擎每天拿來和自己的帳對（對不上就停下來記 error，不自己猜）
在那之前，引擎若設成 broker=kgi 會在 configured() 這裡停下來，寫 last_error，不會送出任何單。
"""
import os

from .base import Broker, BrokerNotConfigured

ENV_KEYS = ('KGI_ID', 'KGI_PASSWORD', 'KGI_BRANCH', 'KGI_ACCOUNT')


class KgiBroker(Broker):
    name = 'kgi'

    def configured(self):
        missing = [k for k in ENV_KEYS if not os.environ.get(k)]
        if missing:
            return False, f'凱基 API 尚未設定：缺環境變數 {", ".join(missing)}（要先向凱基申請 API）'
        try:
            import kgiapp  # noqa: F401
        except ImportError:
            return False, '凱基 API 套件未安裝：pip install kgiapp（需 .NET Framework 4.5）'
        return False, '凱基下單尚未實作（brokers/kgi.py execute）'

    def execute(self, orders, exec_date):
        ok, why = self.configured()
        raise BrokerNotConfigured(why)

    def positions(self):
        raise BrokerNotConfigured(self.configured()[1])

    def cash(self):
        raise BrokerNotConfigured(self.configured()[1])
