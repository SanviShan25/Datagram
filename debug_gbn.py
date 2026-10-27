"""Diagnostic only: delete after use. Run from the repo root:  python debug_gbn.py

Same transfer (20000 bytes, window 4, 20% loss, seed 42) under three settings:
  A: defaults
  B: defaults, but the receiver lingers 10 s after the FIN
  C: reset_on_retx_ack=True (backoff cleared on ACK progress)
Each run is capped at 40 s and prints the sender's RTO every 2 s, then who
finished when and any error. Compare A, B and C.
"""
import os
import socket
import threading
import time

from datagram.channel import Channel
from datagram.protocols.gbn import GoBackN

CAP = 40.0


def run(label, window=4, loss=0.2, size=20000, seed=42,
        reset=False, rx_linger=None):
    print(f"\n=== {label}: window={window} loss={loss} "
          f"reset_on_retx_ack={reset} receiver linger={rx_linger} ===")
    src, dst = "dbg_src.bin", "dbg_dst.bin"
    with open(src, "wb") as f:
        f.write(os.urandom(size))

    s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    r_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s_sock.bind(("127.0.0.1", 0))
    r_sock.bind(("127.0.0.1", 0))
    s_chan = Channel(s_sock, r_sock.getsockname(), seed=seed, loss=loss)
    r_chan = Channel(r_sock, s_sock.getsockname(), seed=seed + 1, loss=loss)

    sender = GoBackN(s_sock, s_chan, window=window, rto=0.05, max_retries=60,
                     reset_on_retx_ack=reset)
    receiver = GoBackN(r_sock, r_chan, window=window, rto=0.05,
                       max_retries=60, linger=rx_linger)
    out = {}
    start = time.monotonic()

    def send():
        try:
            out["sender"] = sender.send_file(src)
        except Exception as e:
            out["sender_error"] = repr(e)
        out["sender_done_at"] = round(time.monotonic() - start, 1)

    def recv():
        try:
            out["receiver"] = receiver.receive_file(dst)
        except Exception as e:
            out["receiver_error"] = repr(e)
        out["receiver_done_at"] = round(time.monotonic() - start, 1)

    threads = [threading.Thread(target=send, daemon=True),
               threading.Thread(target=recv, daemon=True)]
    for t in threads:
        t.start()

    while time.monotonic() - start < CAP and any(t.is_alive() for t in threads):
        time.sleep(2)
        print(f"t={time.monotonic() - start:5.1f}s "
              f"rto={sender.est.current_rto():.3f} "
              f"sent={sender.stats['packets_sent']} "
              f"retx={sender.stats['retransmissions']}")

    alive = [t.is_alive() for t in threads]
    print("sender  :", out.get("sender") or out.get("sender_error")
          or "STILL RUNNING", "done_at", out.get("sender_done_at"))
    print("receiver:", out.get("receiver") or out.get("receiver_error")
          or "STILL RUNNING", "done_at", out.get("receiver_done_at"))
    print("threads still alive (sender, receiver):", alive)
    s_sock.close()
    r_sock.close()


if __name__ == "__main__":
    run("A defaults")
    run("B long receiver linger", rx_linger=10.0)
    run("C reset backoff on progress", reset=True)