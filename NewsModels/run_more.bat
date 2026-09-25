@echo off
cd /d E:\Desktop\coding\money\NewsModels
set PYTHONUTF8=1
set PYTHONIOENCODING=utf-8
echo %date% %time% run_more start >> logs\overnight.log
venv\Scripts\python.exe run_all.py --skip-done > logs\run_all_b.out 2>&1
echo %date% %time% y1 batch2 done >> logs\overnight.log
venv\Scripts\python.exe run_all.py --label y3 --skip-done > logs\run_all_y3.out 2>&1
echo %date% %time% y3 done >> logs\overnight.log
venv\Scripts\python.exe run_all.py --label y5 --skip-done > logs\run_all_y5.out 2>&1
echo %date% %time% y5 done >> logs\overnight.log
