@echo off
cd /d E:\Desktop\coding\money\NewsModels
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
:wait
findstr /c:"y5 done" logs\overnight.log >nul 2>&1 || (timeout /t 60 /nobreak >nul & goto wait)
echo %date% %time% v1 start >> logs\overnight.log
venv\Scripts\python.exe run_all.py --label v1 --skip-done --models majority,price_logreg,gru_price,dict_xgb,news_only_xgb,sentzh_xgb,attn_logreg,emb_xgb,fused_lgbm,lr_fused,stocknet_lite,han,ding_cnn,transformer > logs\run_all_v1.out 2>&1
echo %date% %time% v1 done >> logs\overnight.log
