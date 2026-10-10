"""Observe and collect the approved CPU-only pilot. No publishing or launching."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT/'dirtb'))
import kaggle_rotate as k

ID = 'tishaferdous/confibench-cpu-only-interruption-replay-validation'
DEST = ROOT/'kaggle_runs/cbq_cpu_resume_oct4'
if '--revision' in sys.argv:
    revision = int(sys.argv[sys.argv.index('--revision')+1])
    DEST = ROOT/'kaggle_runs'/f'cbq_cpu_resume_oct4_v{revision}'


def main():
    DEST.mkdir(exist_ok=True)
    account = k.accounts()[1]
    deadline = time.monotonic()+15*60
    while time.monotonic() < deadline:
        status = k.kaggle(['kernels','status',ID], account, timeout=90).strip()
        print(datetime.now(timezone.utc).isoformat(), status, flush=True)
        (DEST/'status.json').write_text(json.dumps({'checked_at':datetime.now(timezone.utc).isoformat(),
          'kernel':ID,'status':status,'gpu_enabled':False}, indent=2))
        if any(word in status for word in ('COMPLETE','ERROR','CANCEL_ACKNOWLEDGED')):
            result = k.kaggle(['kernels','output',ID,'-p',str(DEST),
                              '--file-pattern','cpu_*','--page-size','200'],account,timeout=240)
            print(result[-1800:],flush=True)
            report = DEST/'cpu_resume_report.json'
            if report.exists():
                print(report.read_text(),flush=True)
            else:
                for phase in ('cpu_phase1.log','cpu_phase2.log'):
                    f=DEST/phase
                    if f.exists(): print(phase, f.read_text(errors='replace')[-3500:],flush=True)
                print('No resume report; inspect downloaded kernel log. No GPU job launched.',flush=True)
            return
        time.sleep(20)
    print('Observation limit reached; no relaunch. Pilot is independently time-bounded.',flush=True)


if __name__=='__main__': main()
