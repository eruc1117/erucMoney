"""
M10 Ensemble（加權集成）
────────────────────────
方法：對 M01/M02/M03 的測試集預測加權平均
特徵：依賴 M01~M03 的 results JSON
優勢：集成多個模型，降低單模型偏差

IMP-006：加入動態權重版本（依各模型近期 MAPE 反比加權）
"""
import numpy as np
from config import ENSEMBLE_WEIGHTS


def ensemble_predict(predictions: dict[str, np.ndarray]) -> np.ndarray:
    """
    固定權重加權集成（原始版本）。
    predictions: {"m01_vanilla": array, "m02_stacked": array, ...}
    """
    total_w, result = 0.0, None
    for key, w in ENSEMBLE_WEIGHTS.items():
        if key not in predictions:
            continue
        arr = np.array(predictions[key]).flatten()
        result = arr * w if result is None else result + arr * w
        total_w += w

    if result is None:
        raise ValueError("找不到任何基礎模型預測結果")
    return result / total_w if total_w != 1.0 else result


# ── IMP-006：動態權重集成 ───────────────────────────────────────────────────────

def compute_dynamic_weights(recent_maes: dict[str, float],
                             eps: float = 1e-8) -> dict[str, float]:
    """
    IMP-006：依各模型近期 MAE（或 MAPE）的反比計算動態加權。
    誤差越小的模型獲得越高的權重。

    Parameters
    ----------
    recent_maes : {"m01_vanilla": 0.032, "m02_stacked": 0.028, ...}
                  近期（例如最近 30 天測試集）的 MAE / MAPE 值
    eps         : 避免除以 0

    Returns
    -------
    weights : {"m01_vanilla": 0.28, "m02_stacked": 0.41, ...}  ─ 總和為 1.0
    """
    inv = {k: 1.0 / (v + eps) for k, v in recent_maes.items()}
    total = sum(inv.values())
    return {k: v / total for k, v in inv.items()}


def dynamic_ensemble_predict(predictions: dict[str, np.ndarray],
                              recent_maes: dict[str, float] = None) -> np.ndarray:
    """
    IMP-006：動態權重加權集成。
    若未提供 recent_maes，則回退至固定權重（ensemble_predict）。

    Parameters
    ----------
    predictions : {"m01_vanilla": array, ...}  各模型預測值
    recent_maes : {"m01_vanilla": 0.032, ...}  各模型近期誤差（愈小權重愈高）

    Returns
    -------
    y_pred : 加權平均後的集成預測值
    """
    if recent_maes is None:
        return ensemble_predict(predictions)

    # 只對有預測結果的模型計算
    available = {k: v for k, v in recent_maes.items() if k in predictions}
    if not available:
        return ensemble_predict(predictions)

    weights = compute_dynamic_weights(available)

    result, total_w = None, 0.0
    for key, w in weights.items():
        arr = np.array(predictions[key]).flatten()
        result = arr * w if result is None else result + arr * w
        total_w += w

    return result / total_w if abs(total_w - 1.0) > 1e-6 else result
