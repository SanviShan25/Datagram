import hashlib
import math
import os
import socket
import threading

import pytest

from datagram.channel import Channel
from datagram.protocols.stop_wait import StopAndWait
from datagram.rto import RTOEstimator
RTO = 0.05
JOIN_TIMEOUT = 15  # seconds; a hung receiver fails the test instead of hanging it


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run(tmp_path, size, loss, corrupt, seed):
    """One end-to-end transfer through the real Channel. Asserts correctness
    AND that the recovery paths actually ran. Returns the collected numbers."""
    src = tmp_path / "src.bin"
    dst = tmp_path / "dst.bin"
    src.write_bytes(os.urandom(size))

    s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    r_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    out, recv_err = {}, []
    try:
        s_sock.bind(("127.0.0.1", 0))
        r_sock.bind(("127.0.0.1", 0))
        s_addr, r_addr = s_sock.getsockname(), r_sock.getsockname()

        # Different seeds per direction so the two channels don't mirror each other.
        s_chan = Channel(s_sock, r_addr, seed=seed, loss=loss, corrupt=corrupt)
        r_chan = Channel(r_sock, s_addr, seed=seed + 1, loss=loss, corrupt=corrupt)

        sender = StopAndWait(s_sock, s_chan, rto=RTO, max_retries=60, est=RTOEstimator(fixed=RTO))
        receiver = StopAndWait(r_sock, r_chan, rto=RTO, max_retries=60,
                               idle_timeout=5.0)

        def recv_worker():
            try:
                out.update(receiver.receive_file(str(dst)))
            except Exception as e:  # surface the REAL receiver error
                recv_err.append(e)

        t = threading.Thread(target=recv_worker, daemon=True)
        t.start()
        try:
            stats = sender.send_file(str(src))
        finally:
            t.join(timeout=JOIN_TIMEOUT)
    finally:
        s_sock.close()
        r_sock.close()

    assert not t.is_alive(), "receiver thread did not finish (hang)"
    if recv_err:
        raise recv_err[0]

    dropped = s_chan.stats["dropped"] + r_chan.stats["dropped"]
    corrupted = s_chan.stats["corrupted"] + r_chan.stats["corrupted"]
    impaired = dropped + corrupted

    # --- correctness ---
    assert sha(src) == sha(dst), "HASH MISMATCH"
    assert os.path.getsize(dst) == size
    assert stats["bytes_delivered"] == size
    assert out["bytes_delivered"] == size

    # --- the recovery paths really ran ---
    if loss > 0 or corrupt > 0:
        assert impaired > 0, (
            "impairment was configured but never fired; this run proves nothing"
        )
    if impaired > 0:
        # Every dropped/corrupted packet forces at least one sender retransmission.
        assert stats["retransmissions"] > 0
    else:
        # Clean link: no retransmissions, no duplicates, exact packet count
        # (data chunks + 1 FIN). A failure here on a very slow machine can
        # mean RTO is too small for it, not a protocol bug.
        assert stats["retransmissions"] == 0
        assert out["retransmissions"] == 0
        assert stats["packets_sent"] == math.ceil(size / 1024) + 1

    return {"stats": stats, "out": out, "dropped": dropped, "corrupted": corrupted}


@pytest.mark.parametrize("size", [0, 1, 2048, 2500, 50000])
@pytest.mark.parametrize("loss,corrupt", [
    (0.0, 0.0), (0.2, 0.0), (0.4, 0.0), (0.0, 0.1), (0.2, 0.1),
])
def test_loopback(tmp_path, size, loss, corrupt):
    run(tmp_path, size, loss, corrupt, seed=42)


@pytest.mark.parametrize("seed", range(20))
def test_seed_sweep(tmp_path, seed):
    """Same harsh setting across 20 seeds = 20 different loss patterns.
    A failing seed is reproducible: run(tmp_path, 5000, 0.3, 0.1, seed=<n>)."""
    run(tmp_path, 5000, 0.3, 0.1, seed)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))