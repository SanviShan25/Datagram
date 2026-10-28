# experiments/plots.py
# Reads the CSVs that run_sweeps.py wrote and makes the proposal's outputs:
#   1. goodput vs loss rate (three protocol lines)
#   2. goodput vs window size (Stop-and-Wait as a flat baseline)
#   3. retransmission count vs reordering probability
#   4. a short comparison table on RTO sensitivity
# It also prints a check of the claim and of the SHA-256 results.
# Run the sweeps FIRST, then from the repo root:  python -m experiments.plots
import pandas as pd                    # reads the CSV files and averages them
import matplotlib.pyplot as plt        # draws the graphs

NAMES = {"sw": "Stop-and-Wait", "gbn": "Go-Back-N", "sr": "Selective Repeat"}
COLORS = {"sw": "red", "gbn": "blue", "sr": "green"}


def load(name):
    # Read one results CSV. Trials that failed (completed=False) are left out
    # of the averages, but the number is printed so it can go in the report.
    df = pd.read_csv(f"results/{name}.csv")
    if "completed" in df.columns:
        ok = df["completed"].astype(bool)
        if (~ok).sum():
            print(f"{name}: {int((~ok).sum())} failed trial(s) excluded from the averages")
        df = df[ok]
    return df


def settings_note(df):
    # What was held constant, read from the CSV itself so it is always correct
    # (the proposal says file size and RTT stay constant)
    return (f"{df['file_size'].iloc[0] // 1000} KB file, "
            f"{df['delay'].iloc[0] * 1000:.0f} ms one-way delay, "
            f"fixed RTO {df['rto'].iloc[0]} s")


# ====================================================================
# Graph 1: goodput vs loss
# ====================================================================
def plot_goodput_vs_loss():
    df = load("exp1_goodput_vs_loss")                        # the whole CSV as a table

    # 5 seeds per setting -> one average per (protocol, loss)
    avg = df.groupby(["protocol", "loss"])["goodput_bps"].mean().reset_index()

    for p in ["sw", "gbn", "sr"]:
        rows = avg[avg["protocol"] == p]                     # only this protocol's rows
        plt.plot(rows["loss"] * 100, rows["goodput_bps"] / 1000,   # x in %, y in kbit/s
                 marker="o", color=COLORS[p], label=NAMES[p])

    plt.title(f"Goodput vs packet loss\nwindow {df['window'].iloc[0]}, {settings_note(df)}",
              fontsize=10)
    plt.xlabel("Packet loss (%)")
    plt.ylabel("Goodput (kbit/s)")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.savefig("results/exp1_goodput_vs_loss.png", dpi=150)
    plt.close()                                              # clear it for the next graph


# ====================================================================
# Graph 2: goodput vs window size
# ====================================================================
def plot_goodput_vs_window():
    df = load("exp2_goodput_vs_window")
    avg = df.groupby(["protocol", "window"])["goodput_bps"].mean().reset_index()

    for p in ["gbn", "sr"]:                                  # sw has no window to sweep
        rows = avg[avg["protocol"] == p]
        plt.plot(rows["window"], rows["goodput_bps"] / 1000,
                 marker="o", color=COLORS[p], label=NAMES[p])

    # Stop-and-Wait ran once (window 1) -> draw it as one flat dashed line
    sw = df[df["protocol"] == "sw"]["goodput_bps"].mean() / 1000
    plt.axhline(sw, color=COLORS["sw"], linestyle="--", label="Stop-and-Wait (window 1)")

    windows = [1, 2, 4, 8, 16, 32]
    plt.xscale("log", base=2)                                # windows double each step
    plt.xticks(windows, windows)                             # label the ticks 1, 2, 4 ...
    plt.title(f"Goodput vs window size\nloss {df['loss'].iloc[0] * 100:.0f}%, "
              f"{settings_note(df)}", fontsize=10)
    plt.xlabel("Window size (packets)")
    plt.ylabel("Goodput (kbit/s)")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.savefig("results/exp2_goodput_vs_window.png", dpi=150)
    plt.close()


# ====================================================================
# Graph 3: retransmissions vs reordering
# ====================================================================
def plot_retx_vs_reorder():
    df = load("exp3_retx_vs_reorder")
    avg = df.groupby(["protocol", "reorder"])["retransmissions"].mean().reset_index()

    for p in ["sw", "gbn", "sr"]:
        rows = avg[avg["protocol"] == p]
        plt.plot(rows["reorder"] * 100, rows["retransmissions"],
                 marker="o", color=COLORS[p], label=NAMES[p])

    plt.title(f"Retransmissions vs reordering probability\nloss {df['loss'].iloc[0] * 100:.0f}%, "
              f"window {df['window'].iloc[0]}, {settings_note(df)}", fontsize=10)
    plt.xlabel("Reordering probability (%)")
    plt.ylabel("Retransmissions per transfer")
    plt.legend()
    plt.grid(alpha=0.3)
    plt.savefig("results/exp3_retx_vs_reorder.png", dpi=150)
    plt.close()


# ====================================================================
# Table: RTO sensitivity (a table, not a graph)
# ====================================================================
def rto_table():
    df = pd.read_csv("results/exp4_rto_variants.csv")

    # Give every row a readable name for its RTO variant
    names = []
    for rto, reset in zip(df["rto"], df["reset_backoff"]):
        if rto == "adaptive" and reset:
            names.append("Adaptive + reset")
        elif rto == "adaptive":
            names.append("Adaptive")
        else:
            names.append(f"Fixed {rto} s")
    df["variant"] = names

    # Mean goodput over the runs that finished (failed runs have no goodput)
    done_rows = df[df["completed"] == True]
    mean = done_rows.pivot_table(index="variant", columns="loss",
                                 values="goodput_bps", aggfunc="mean") / 1000

    # How many runs finished, out of how many were tried
    finished = df.pivot_table(index="variant", columns="loss",
                              values="completed", aggfunc="sum").astype(int)
    total = df.groupby(["variant", "loss"]).size().unstack()

    table = (mean.round(1).astype(str) + " ("
             + finished.astype(str) + "/" + total.astype(str) + ")")
    table.columns = [f"{round(l * 100)}% loss" for l in table.columns]

    print("\nGoodput kbit/s (finished runs / total runs), Selective Repeat")
    print(table)
    table.to_csv("results/exp4_rto_goodput_table.csv")

# ====================================================================
# Does the data support the proposal's claim? (prints numbers only)
# ====================================================================
def claim_check():
    # Claim: SR beats GBN when loss > 5%, and both beat Stop-and-Wait.
    # Say in the report what the numbers show, even if the claim holds only partly.
    df = load("exp1_goodput_vs_loss")
    table = df.pivot_table(index="loss", columns="protocol", values="goodput_bps",
                           aggfunc="mean") / 1000
    print("\nMean goodput (kbit/s) per loss level")
    print(table.round(0))

    above = table[table.index > 0.051]                       # loss above 5% only
    wins = (above["sr"] > above["gbn"]).sum()
    print(f"\nSR beats GBN at {wins} of {len(above)} loss levels above 5%")
    for p in ["gbn", "sr"]:
        wins = (table[p] > table["sw"]).sum()
        print(f"{NAMES[p]} beats Stop-and-Wait at {wins} of {len(table)} loss levels")

    # Second half of the claim: both beat Stop-and-Wait at every window size above 1
    df2 = load("exp2_goodput_vs_window")
    sw = df2[df2["protocol"] == "sw"]["goodput_bps"].mean()          # one flat baseline
    by_window = df2.pivot_table(index="window", columns="protocol", values="goodput_bps",
                                aggfunc="mean")
    big = by_window[by_window.index > 1]                             # non-trivial windows
    for p in ["gbn", "sr"]:
        wins = (big[p] > sw).sum()
        print(f"{NAMES[p]} beats Stop-and-Wait at {wins} of {len(big)} window sizes above 1")


# ====================================================================
# Integrity: did every transfer pass the SHA-256 check? (core deliverable)
# ====================================================================
def integrity_check():
    for name in ["exp1_goodput_vs_loss", "exp2_goodput_vs_window",
                 "exp3_retx_vs_reorder", "exp4_rto_variants"]:
        df = pd.read_csv(f"results/{name}.csv")                      # raw: failed rows included
        failed = int((~df["completed"].astype(bool)).sum()) if "completed" in df.columns else 0
        ok = int((df["hash_ok"] == True).sum())                      # True counts as 1
        print(f"{name}: {ok} of {len(df) - failed} completed transfers matched their "
              f"SHA-256 hash ({failed} failed)")
        if "error" in df.columns:
            bad = int(df["error"].astype(str).str.contains("hash mismatch").sum())
            if bad:
                print(f"  WARNING: {bad} hash mismatch(es) in {name}")

                
if __name__ == "__main__":
    plot_goodput_vs_loss()
    plot_goodput_vs_window()
    plot_retx_vs_reorder()
    rto_table()
    claim_check()
    integrity_check()