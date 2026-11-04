"""Supervise a capture daemon.

Quartz window capture occasionally blocks forever once the window has been ordered
out of the compositor. The daemon itself cannot notice (it is stuck inside the C
call), so an external supervisor watches the observation file's timestamp and
restarts the daemon if it goes stale.

usage: python supervisor.py <instance_id> [target_hz] [stale_seconds]
"""
import os
import signal
import subprocess
import sys
import time

OBS = "/tmp/nid_obs_{}.json"


def main():
    iid = sys.argv[1] if len(sys.argv) > 1 else "0"
    hz = sys.argv[2] if len(sys.argv) > 2 else "25"
    stale = float(sys.argv[3]) if len(sys.argv) > 3 else 5.0
    path = OBS.format(iid)
    here = os.path.dirname(os.path.abspath(__file__))
    restarts = 0
    while True:
        proc = subprocess.Popen([sys.executable, os.path.join(here, "capture_daemon.py"), iid, hz])
        print(f"[sup {iid}] daemon started pid={proc.pid} (restart #{restarts})", flush=True)
        try:
            while proc.poll() is None:
                time.sleep(1.0)
                try:
                    age = time.time() - os.path.getmtime(path)
                except OSError:
                    age = 999
                if age > stale:
                    print(f"[sup {iid}] stale for {age:.1f}s - restarting daemon", flush=True)
                    proc.send_signal(signal.SIGKILL)
                    proc.wait(timeout=5)
                    restarts += 1
                    break
            else:
                print(f"[sup {iid}] daemon exited rc={proc.returncode} - restarting", flush=True)
                restarts += 1
        except Exception as exc:                    # noqa: BLE001
            print(f"[sup {iid}] error: {exc}", flush=True)
            try:
                proc.send_signal(signal.SIGKILL)
            except Exception:
                pass
        time.sleep(0.5)


if __name__ == "__main__":
    main()
