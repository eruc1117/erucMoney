"""Iteration 85 跑批：依事前登記（iter85_hypothesis.md）用 portfolio_backtest.py 的 CLI 逐條跑，參數原樣、不調。
用法（Crawler 目錄）：PYTHONUTF8=1 python ../AI/experiments/iter85_run.py dev | valid <signal> ；輸出同時寫 AI/experiments/iter85_<段>.log"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
CRAWLER = os.path.join(HERE, '..', '..', 'Crawler')
DEV = [('nsblf', 'H26 放空流量反向單獨（Iteration 85）'),
       ('win3+mom+nsblf', 'H27 放空流量反向相加（Iteration 85）'),
       ('indlead', 'H28 產業領先股單獨（Iteration 85）'),
       ('win3+mom+indlead', 'H29 產業領先股相加（Iteration 85）')]
seg = sys.argv[1]
todo = DEV if seg == 'dev' else [(sys.argv[2], f'Iteration 85 驗證期一次（登記規則：開發期過門檻且兩項超過 #30）')]
log = open(os.path.join(HERE, f'iter85_{seg}.log'), 'a', encoding='utf-8')
for sig, note in todo:
    args = [sys.executable, 'portfolio_backtest.py', '--signal', sig, '--segment', seg, '--tranches', '3', '--tsmc-weight', 'est',
            '--name', f'{sig}-t3-tsmcest-{seg}', '--notes', note]
    print('>>', ' '.join(args[1:]), flush=True)
    log.write('>> ' + ' '.join(args[1:]) + '\n')
    p = subprocess.run(args, cwd=CRAWLER, capture_output=True, text=True, encoding='utf-8', errors='replace',
                       env={**os.environ, 'PYTHONUTF8': '1', 'PYTHONWARNINGS': 'ignore'})
    out = p.stdout + p.stderr
    log.write(out + '\n')
    tail = [ln for ln in out.splitlines() if '[backtest] #' in ln or '年化主動' in ln or 'Error' in ln or 'Traceback' in ln]
    print('\n'.join(tail[-3:]) or out[-600:], flush=True)
    if p.returncode != 0:
        print('exit', p.returncode, flush=True)
        sys.exit(p.returncode)
log.close()
