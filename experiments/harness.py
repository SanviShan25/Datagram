# experiments/harness.py
# One transfer = one data point. Every sweep script calls run_trial().
import csv
import hashlib
import os
import socket
import tempfile
import threading

from datagram.channel import Channel
from datagram.protocols.stop_wait import StopAndWait
from datagram.protocols.sr import SelectiveRepeat
from datagram.rto import RTOEstimator

# Column order of the CSV. Must match the dict run_trial returns.
FIELDS = ["protocol", "seed", "loss", "window", "reorder", "delay", "file_size",
          "rto", "reset_backoff", "elapsed_s", "goodput_bps", "packets_sent",
          "retransmissions", "hash_ok"]


# ====================================================================
# Part 1: small helpers
# ====================================================================
def sha256_of(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):   # chunks, not the whole file
            h.update(block)
    return h.hexdigest()


def make_protocol(name, sock, chan, window=8, rto=0.1, adaptive=False, reset=False):
    # ALL three protocols are built here, so fixed vs adaptive can't differ
    # by accident. The catch: rto means different things.
    # Case: gbn -> rto IS the timeout
    # Case: sw / sr -> rto only sets the linger, the timeout comes from est
    est = RTOEstimator(min_rto=0.05) if adaptive else RTOEstimator(fixed=rto)

    if name == "gbn":
        from datagram.protocols.gbn import GoBackN   # imported here, only when asked for
        assert not adaptive, "GoBackN has no adaptive RTO"
        assert not reset, "reset_on_retx_ack exists only in Selective Repeat"
        return GoBackN(sock, chan, window=window, rto=rto, max_retries=60)
    if name == "sw":
        assert not reset, "reset_on_retx_ack exists only in Selective Repeat"
        return StopAndWait(sock, chan, rto=rto, max_retries=60, est=est)
    if name == "sr":
        return SelectiveRepeat(sock, chan, window=window, rto=rto, max_retries=60,
                               est=est, reset_on_retx_ack=reset)
    raise ValueError(f"unknown protocol: {name}")


def check_timeout(name, proto, rto, adaptive):
    # Safety net: stop the run if a protocol is not using the timeout we
    # asked for, because the graph would compare unequal things.
    if adaptive:
        return                                   # adaptive learns its own, nothing to check
    used = proto.rto if name == "gbn" else proto.est.current_rto()
    assert used == rto, f"{name} uses timeout {used}, expected fixed {rto}"


# ====================================================================
# Part 2: one trial
# ====================================================================
def run_trial(protocol, seed, loss, window, reorder, file_size,
              rto=0.1, adaptive=False, reset=False, delay=0.01, join_timeout=180):
    # delay is ONE-way, applied in both directions. With delay=0 the ACK comes
    # back instantly on localhost, so a bigger window shows no benefit.
    # rto should stay above 2 * delay, otherwise the timer fires before the ACK.
    with tempfile.TemporaryDirectory() as folder:
        src = os.path.join(folder, "src.bin")
        dst = os.path.join(folder, "dst.bin")
        with open(src, "wb") as f:
            f.write(os.urandom(file_size))

        s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        r_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            s_sock.bind(("127.0.0.1", 0))
            r_sock.bind(("127.0.0.1", 0))

            # seed and seed + 1 so the two directions don't roll the same dice.
            # Same seed + same settings still gives the exact same run.
            s_chan = Channel(s_sock, r_sock.getsockname(), seed=seed,
                             loss=loss, reorder=reorder, delay=delay)
            r_chan = Channel(r_sock, s_sock.getsockname(), seed=seed + 1,
                             loss=loss, reorder=reorder, delay=delay)
            sender = make_protocol(protocol, s_sock, s_chan, window, rto, adaptive, reset)
            receiver = make_protocol(protocol, r_sock, r_chan, window, rto, adaptive, reset)
            check_timeout(protocol, sender, rto, adaptive)
            check_timeout(protocol, receiver, rto, adaptive)

            # A thread can't return a value, so it drops its stats in here
            result = {}

            def recv():
                try:
                    result["stats"] = receiver.receive_file(dst)
                except Exception as e:           # keep the error, don't hang the sweep
                    result["error"] = e

            t = threading.Thread(target=recv, daemon=True)
            t.start()
            s = sender.send_file(src)            # sender runs in the main thread
            t.join(timeout=join_timeout)

            assert not t.is_alive(), "receiver hung"
            assert "error" not in result, f"receiver failed: {result.get('error')}"
            r = result["stats"]

            # A wrong file is a bug, not a data point
            hash_ok = sha256_of(src) == sha256_of(dst)
            assert hash_ok, "hash mismatch: file arrived wrong"
        finally:
            s_sock.close()
            r_sock.close()

    # Which side do the numbers come from?
    # Case: time, packets_sent, retransmissions -> SENDER (what it really sent;
    #       the receiver's counters are ACKs sent and duplicates seen)
    # Case: bytes_delivered -> RECEIVER (what actually arrived)
    return {
        "protocol": protocol, "seed": seed, "loss": loss, "window": window,
        "reorder": reorder, "delay": delay, "file_size": file_size,
        "rto": "adaptive" if adaptive else rto,
        "reset_backoff": reset,
        "elapsed_s": s["elapsed_s"],
        "goodput_bps": r["bytes_delivered"] * 8 / s["elapsed_s"],
        "packets_sent": s["packets_sent"],
        "retransmissions": s["retransmissions"],
        "hash_ok": hash_ok,
    }


def write_csv(rows, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(rows)


if __name__ == "__main__":
    # Quick smoke test: 2 protocols x 2 loss levels x 2 seeds
    rows = []
    for protocol in ("sw", "sr"):
        for loss in (0.0, 0.1):
            for seed in (1, 2):
                row = run_trial(protocol, seed, loss, window=8, reorder=0.0,
                                file_size=30_000)
                print(protocol, loss, seed, round(row["goodput_bps"]), row["retransmissions"])
                rows.append(row)
    write_csv(rows, "results/smoke.csv")
    print("wrote results/smoke.csv")