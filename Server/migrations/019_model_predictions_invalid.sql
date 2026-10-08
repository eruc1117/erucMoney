-- 預測台帳的事後作廢欄位（2026-09-29）
-- ─────────────────────────────────────────────────────────────────────────────
-- 跳空模型 8/7 ~ 9/22 的線上紀錄，推論時餵的夜盤特徵是「當天早上收的那一場」，
-- 算出來的是當天已發生的跳空，卻標成明天的預測（預測值與當天已實現跳空相關 0.76、
-- 與目標日 −0.03；AI/Doc/ModelAccuracy.md 第二節）。這些紀錄不能算成績，
-- 但也不刪——留著才對得出「當時線上到底輸出了什麼」。
--
-- 規則：invalid_reason 非 NULL 的列，model_lifecycle 評估與 models/registry 的
-- pred_resolved 一律不計；resolve_predictions 照常回填 actual_value（稽核用）。

ALTER TABLE model_predictions ADD COLUMN IF NOT EXISTS invalid_reason TEXT;

-- 作廢跳空模型在修正日之前的所有紀錄（v1、v2 同一種推論寫法）
UPDATE model_predictions p
   SET invalid_reason = 'night_alignment: 推論用的是當天已收的夜盤，預測的是已發生的跳空（2026-09-29 修正）'
  FROM model_versions v
 WHERE v.id = p.model_version_id
   AND v.model_type = 'gap'
   AND p.predicted_on < DATE '2026-09-25'
   AND p.invalid_reason IS NULL;
