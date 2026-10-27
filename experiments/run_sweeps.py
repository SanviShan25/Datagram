# experiments/run_sweeps.py
# How to use: change `which` and `quick` at the very bottom, then run from
# the repo root:
#   python -m experiments.run_sweeps
# Each experiment writes results/<name>.csv, one row per trial.
import time

from experiments.harness import run_trial, write_csv

FILE_SIZE = 50_000          # bytes per transfer (about 49 packets)
SEEDS = [1, 2, 3, 4, 5]     # every config runs once per seed, then we average
RTO = 0.1                   # ONE fixed RTO for all protocols, above 2 * DELAY
DELAY = 0.01                # 10 ms each way, so ACKs are not instant
LOSS_FIXED = 0.05           # loss held constant in the reorder sweep
LOSS_WINDOW = 0.10          # loss held constant in the window sweep (the claim is for > 5%)


def sweep(name, configs, seeds, file_size):
    # Always write what finished, even if a run crashes half way.
    # A trial that fails is recorded (completed=False + error text) and the
    # sweep goes on with the next one, so one bad trial can't kill the run.
    rows, total, t0 = [], len(configs) * len(seeds), time.time()
    failed = 0
    try:
        for cfg in configs:
            for seed in seeds:
                try:
                    rows.append(run_trial(seed=seed, file_size=file_size, delay=DELAY, **cfg))
                except Exception as e:
                    failed += 1
                    print(f"[{name}] FAILED {cfg} seed={seed}: {e}", flush=True)
                    rows.append({
                        "protocol": cfg["protocol"], "seed": seed, "loss": cfg["loss"],
                        "window": cfg["window"], "reorder": cfg["reorder"],
                        "delay": DELAY, "file_size": file_size,
                        "rto": "adaptive" if cfg.get("adaptive") else cfg["rto"],
                        "reset_backoff": cfg.get("reset", False),
                        "completed": False, "error": str(e)[:300],
                    })
                print(f"[{name}] {len(rows)}/{total}  {time.time() - t0:.0f}s  {cfg}", flush=True)
    finally:
        if rows:
            write_csv(rows, f"results/{name}.csv")
            print(f"wrote results/{name}.csv ({len(rows)} rows, {failed} failed)")


# ====================================================================
# The four experiments: each returns a list of configs for sweep()
# ====================================================================
def exp1_goodput_vs_loss(protocols):
    # Vary loss only, same fixed RTO for every protocol
    return [dict(protocol=p, loss=l, window=8, reorder=0.0, rto=RTO)
            for p in protocols for l in (0.0, 0.05, 0.1, 0.15, 0.2, 0.25, 0.3)]


def exp2_goodput_vs_window(protocols):
    # Vary window only. Stop-and-Wait is window 1 by definition, so it runs
    # ONCE as a flat baseline line instead of being swept.
    configs = [dict(protocol=p, loss=LOSS_WINDOW, window=w, reorder=0.0, rto=RTO)
               for p in protocols if p != "sw" for w in (1, 2, 4, 8, 16, 32)]
    if "sw" in protocols:
        configs.append(dict(protocol="sw", loss=LOSS_WINDOW, window=1, reorder=0.0, rto=RTO))
    return configs


def exp3_retx_vs_reorder(protocols):
    # Vary reorder only, loss stays fixed
    return [dict(protocol=p, loss=LOSS_FIXED, window=8, reorder=r, rto=RTO)
            for p in protocols for r in (0.0, 0.05, 0.1, 0.2, 0.3)]


def exp4_rto_variants(_protocols): # unused: this experiment always runs on sr
    # reset_on_retx_ack only exists in Selective Repeat -> all variants run on sr
    # Case: adaptive          -> default estimator
    # Case: adaptive + reset  -> same, but backoff resets on a retx ACK
    # Case: fixed             -> RTOEstimator(fixed=r), several baselines
    base = dict(protocol="sr", window=8, reorder=0.0, rto=RTO)
    variants = [dict(adaptive=True),
                dict(adaptive=True, reset=True)]
    variants += [dict(adaptive=False, rto=r) for r in (0.05, 0.1, 0.3)]
    return [{**base, "loss": l, **v} for v in variants for l in (0.0, 0.1, 0.2, 0.3)]


EXPERIMENTS = {"exp1": ("exp1_goodput_vs_loss", exp1_goodput_vs_loss),
               "exp2": ("exp2_goodput_vs_window", exp2_goodput_vs_window),
               "exp3": ("exp3_retx_vs_reorder", exp3_retx_vs_reorder),
               "exp4": ("exp4_rto_variants", exp4_rto_variants)}

if __name__ == "__main__":
    which = "all"      # "exp1", "exp2", "exp3", "exp4" or "all"
    quick = False         # True = tiny test run, False = the real full run
    protocols = ["sw", "gbn", "sr"]

    seeds, size = ([1], 20_000) if quick else (SEEDS, FILE_SIZE)
    for key in (EXPERIMENTS if which == "all" else [which]):
        name, build = EXPERIMENTS[key]
        sweep(name, build(protocols), seeds, size)