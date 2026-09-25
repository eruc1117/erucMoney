@echo off
REM 整夜跑：等 venv 裝好 → 新聞向量 → 全部模型（y1）→ 主要模型（y3）
REM 用 PowerShell Start-Process 獨立啟動，不依附任何終端。日誌在 logs\。
cd /d E:\Desktop\coding\money\NewsModels
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8

:wait
venv\Scripts\python.exe -c "import sentence_transformers, jieba, lightgbm, xgboost, transformers" >nul 2>&1
if errorlevel 1 (
  echo %date% %time% waiting for venv >> logs\overnight.log
  timeout /t 30 /nobreak >nul
  goto wait
)
echo %date% %time% venv ready >> logs\overnight.log

venv\Scripts\python.exe embed.py > logs\embed.log 2>&1
echo %date% %time% embed done >> logs\overnight.log

venv\Scripts\python.exe run_all.py --skip-done > logs\run_all.out 2>&1
echo %date% %time% y1 done >> logs\overnight.log

venv\Scripts\python.exe run_all.py --label y3 --skip-done --models majority,price_logreg,dict_xgb,tfidf_logreg,emb_xgb,sentzh_xgb,fused_lgbm,mlp_fused,stocknet_lite,han,ding_cnn,transformer > logs\run_all_y3.out 2>&1
echo %date% %time% y3 done >> logs\overnight.log

venv\Scripts\python.exe run_all.py --label y5 --skip-done --models majority,price_logreg,dict_xgb,emb_xgb,fused_lgbm,han,stocknet_lite > logs\run_all_y5.out 2>&1
echo %date% %time% y5 done >> logs\overnight.log
