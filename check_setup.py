"""Sends ONE tiny request to every model in the config, to check keys, model names and network before a long run.
    python check_setup.py --config config.free.json"""
import argparse, json, time
from run_experiments import make_client

ap = argparse.ArgumentParser(); ap.add_argument("--config", required=True); a = ap.parse_args()
cfg = json.load(open(a.config))
for name, m in cfg["models"].items():
    try:
        t = time.time()
        r = make_client(m).generate("Reply with the single word OK.", "ping", 0.5)
        print(f"[ok]   {name:18s} {time.time() - t:4.1f}s  -> {r.strip()[:30]!r}")
    except Exception as e:      # noqa: BLE001
        print(f"[FAIL] {name:18s} {type(e).__name__}: {str(e)[:160]}")
