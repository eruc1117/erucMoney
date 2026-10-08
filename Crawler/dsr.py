"""
Deflated Sharpe Ratio（Bailey & López de Prado 2014, Journal of Portfolio Management）

測了 N 個版本，最好的那個 Sharpe 光靠運氣就會升到 SR*；DSR 是「真實 Sharpe 大於 SR*」的機率。

    SR* = sqrt(V) · [ (1−γ) Φ⁻¹(1 − 1/N) + γ Φ⁻¹(1 − 1/(N·e)) ]        γ = 0.5772（Euler–Mascheroni）
    DSR = Φ( (SR − SR*) · sqrt(T − 1) / sqrt(1 − γ₃·SR + (γ₄ − 1)/4 · SR²) )

SR、SR*、V 都是**同一個頻率**的 Sharpe（這裡用月）；T 是樣本數（月數）；γ₃、γ₄ 是報酬的偏態與峰態（峰態是 Pearson，常態 = 3）。
N 從 portfolio_runs.experiment_n 來，V 是日誌裡各版本月 Sharpe 的變異數（只有一個版本時給 0 → SR* = 0，DSR 退化成一般的 PSR）。
"""

import math

EULER_GAMMA = 0.5772156649


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def norm_ppf(p: float) -> float:
    """標準常態分位數（Acklam 近似，誤差 1e-9 等級；不想為此拉 scipy）。"""
    if not 0.0 < p < 1.0:
        raise ValueError('p 必須在 (0, 1)')
    a = (-3.969683028665376e+01, 2.209460984245205e+02, -2.759285104469687e+02, 1.383577518672690e+02, -3.066479806614716e+01, 2.506628277459239e+00)
    b = (-5.447609879822406e+01, 1.615858368580409e+02, -1.556989798598866e+02, 6.680131188771972e+01, -1.328068155288572e+01)
    c = (-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e+00, -2.549732539343734e+00, 4.374664141464968e+00, 2.938163982698783e+00)
    d = (7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e+00, 3.754408661907416e+00)
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / ((((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1)
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1)


def expected_max_sharpe(n_trials: int, var_sharpe: float) -> float:
    """SR*：N 個獨立版本、Sharpe 變異數 V 時，純靠運氣的最佳 Sharpe 期望值。N ≤ 1 或 V ≤ 0 → 0。"""
    if n_trials <= 1 or var_sharpe <= 0:
        return 0.0
    return math.sqrt(var_sharpe) * ((1 - EULER_GAMMA) * norm_ppf(1 - 1 / n_trials)
                                    + EULER_GAMMA * norm_ppf(1 - 1 / (n_trials * math.e)))


def moments(returns: list) -> tuple:
    """(mean, std, skew, kurtosis[Pearson]) — 母體矩，樣本少時不做修正（DSR 原文也沒有）。"""
    n = len(returns)
    if n < 2:
        return 0.0, 0.0, 0.0, 3.0
    m = sum(returns) / n
    d2 = sum((x - m) ** 2 for x in returns) / n
    sd = math.sqrt(d2)
    if sd == 0:
        return m, 0.0, 0.0, 3.0
    skew = sum((x - m) ** 3 for x in returns) / n / sd ** 3
    kurt = sum((x - m) ** 4 for x in returns) / n / sd ** 4
    return m, sd, skew, kurt


def sharpe(returns: list) -> float:
    m, sd, _, _ = moments(returns)
    return m / sd if sd > 0 else 0.0


def deflated_sharpe(returns: list, n_trials: int, var_sharpe: float) -> dict:
    """月報酬序列 → {sr, sr_star, dsr, T, skew, kurt}。dsr 是機率，門檻 0.95。"""
    t = len(returns)
    m, sd, skew, kurt = moments(returns)
    sr = m / sd if sd > 0 else 0.0
    sr_star = expected_max_sharpe(n_trials, var_sharpe)
    if t < 3 or sd == 0:
        return {'sr': sr, 'sr_star': sr_star, 'dsr': 0.0, 'T': t, 'skew': skew, 'kurt': kurt}
    denom = 1 - skew * sr + (kurt - 1) / 4 * sr ** 2
    if denom <= 0:
        return {'sr': sr, 'sr_star': sr_star, 'dsr': 0.0, 'T': t, 'skew': skew, 'kurt': kurt}
    z = (sr - sr_star) * math.sqrt(t - 1) / math.sqrt(denom)
    return {'sr': sr, 'sr_star': sr_star, 'dsr': norm_cdf(z), 'T': t, 'skew': skew, 'kurt': kurt}
