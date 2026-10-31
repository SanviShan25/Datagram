# Go-Back-N with the tracker: adaptive RTO, fixed RTO, and the reset option.
import hashlib
import os
import socket
import threading

import pytest

from datagram.channel import Channel
from datagram.protocols.gbn import GoBackN
from datagram.rto import RTOEstimator


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    return s


def run(tmp_path, est, loss=0.0, delay=0.0, seed=1, reset=False, size=1024 * 20):
    src, dst = tmp_path / "src.bin", tmp_path / "dst.bin"
    src.write_bytes(os.urandom(size))
    s_sock, r_sock = make_socket(), make_socket()
    s_addr, r_addr = s_sock.getsockname(), r_sock.getsockname()
    sender = GoBackN(s_sock,
                     Channel(s_sock, r_addr, seed=seed, loss=loss, delay=delay),
                     window=8, rto=0.05, max_retries=200, est=est,
                     reset_on_retx_ack=reset)
    receiver = GoBackN(r_sock,
                       Channel(r_sock, s_addr, seed=seed + 1, loss=loss, delay=delay),
                       window=8, rto=0.05, linger=0.3, idle_timeout=20)
    out = {}

    def rx():
        try:
            out["rx"] = receiver.receive_file(str(dst))
        except Exception as e:
            out["err"] = e

    t = threading.Thread(target=rx, daemon=True)
    t.start()
    try:
        tx = sender.send_file(str(src))
    finally:
        t.join(timeout=20)
        s_sock.close()
        r_sock.close()
    assert "err" not in out, out.get("err")
    assert sha(src) == sha(dst)
    return tx, sender


def test_default_is_fixed_rto(tmp_path):
    tx, sender = run(tmp_path, est=None)
    assert sender.est.fixed == 0.05
    assert tx["retransmissions"] == 0


def test_adaptive_learns_rto_from_clean_acks(tmp_path):
    est = RTOEstimator(min_rto=0.05, initial_rto=0.5)
    tx, sender = run(tmp_path, est=est, delay=0.01)
    assert est.srtt is not None              # the tracker fed it samples
    assert est.current_rto() < 0.5           # and the RTO came down from 0.5


@pytest.mark.parametrize("seed", [1, 2, 3])
@pytest.mark.parametrize("reset", [False, True])
def test_adaptive_transfer_under_loss(tmp_path, seed, reset):
    est = RTOEstimator(min_rto=0.05)
    tx, sender = run(tmp_path, est=est, loss=0.2, seed=seed, reset=reset)
    assert tx["retransmissions"] > 0


def test_fixed_est_is_never_changed_by_loss(tmp_path):
    est = RTOEstimator(fixed=0.05)
    run(tmp_path, est=est, loss=0.2)
    assert est.current_rto() == 0.05
