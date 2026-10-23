# End-to-end Selective Repeat over real localhost sockets. Every transfer ends
# with a SHA-256 match, because "no exception" does not prove the file arrived so...
import hashlib
import os
import socket
import threading

import pytest

from datagram.channel import Channel
from datagram.protocols.sr import SelectiveRepeat
from datagram.rto import RTOEstimator

RTO = 0.05


class ScriptedChannel:
    """Test-only: applies faults by send index (0 = first packet sent)."""

    def __init__(self, sock, peer, drop=()):
        self.sock, self.peer = sock, peer
        self.drop = set(drop)
        self.count = 0

    def pump(self):
        pass

    def send(self, data):
        n = self.count
        self.count += 1
        if n not in self.drop:
            self.sock.sendto(data, self.peer)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    return s


def transfer(tmp_path, data, window=8, make_send_chan=None, make_ack_chan=None,
             fixed=True):
    src, dst = tmp_path / "src.bin", tmp_path / "dst.bin"
    src.write_bytes(data)
    s_sock, r_sock = make_socket(), make_socket()
    s_addr, r_addr = s_sock.getsockname(), r_sock.getsockname()
    make_send_chan = make_send_chan or (lambda s, p: ScriptedChannel(s, p))
    make_ack_chan = make_ack_chan or (lambda s, p: ScriptedChannel(s, p))

    est = RTOEstimator(fixed=RTO) if fixed else RTOEstimator(min_rto=RTO)
    sender = SelectiveRepeat(s_sock, make_send_chan(s_sock, r_addr),
                             window=window, rto=RTO, est=est)
    receiver = SelectiveRepeat(r_sock, make_ack_chan(r_sock, s_addr),
                               window=window, rto=RTO, linger=0.5)
    out = {}

    def run_receiver():
        try:
            out["rx"] = receiver.receive_file(str(dst))
        except Exception as e:
            out["err"] = e

    t = threading.Thread(target=run_receiver)
    t.start()
    try:
        tx = sender.send_file(str(src))
    finally:
        t.join(timeout=20)
        s_sock.close()
        r_sock.close()
    assert not t.is_alive(), "receiver did not finish"
    assert "err" not in out, f"receiver raised: {out.get('err')!r}"
    return tx, out["rx"], src, dst


@pytest.mark.parametrize("size", [0, 100, 1024, 2048, 2500, 5000, 20000])
def test_clean_transfer(tmp_path, size):
    tx, rx, src, dst = transfer(tmp_path, os.urandom(size))
    assert sha(src) == sha(dst)
    assert tx["retransmissions"] == 0
    assert rx["bytes_delivered"] == size


def test_lost_packet_is_the_only_one_resent(tmp_path):
    # Drop the 2nd packet the sender emits (seq 1 of 0..4). SR must resend
    # ONLY that one; Go-Back-N would resend 1, 2, 3, 4.
    data = os.urandom(1024 * 5)
    tx, rx, src, dst = transfer(
        tmp_path, data, window=8,
        make_send_chan=lambda s, p: ScriptedChannel(s, p, drop=[1]))
    assert sha(src) == sha(dst)
    assert tx["retransmissions"] == 1


def test_lost_ack_does_not_break_transfer(tmp_path):
    data = os.urandom(1024 * 4)
    tx, rx, src, dst = transfer(
        tmp_path, data,
        make_ack_chan=lambda s, p: ScriptedChannel(s, p, drop=[0, 2]))
    assert sha(src) == sha(dst)
    assert rx["bytes_delivered"] == len(data)


def test_lost_final_ack_receiver_lingers(tmp_path):
    # 2 data packets + FIN = 3 ACKs; drop the last one (the FIN's)
    data = os.urandom(1024 * 2)
    tx, rx, src, dst = transfer(
        tmp_path, data,
        make_ack_chan=lambda s, p: ScriptedChannel(s, p, drop=[2]))
    assert sha(src) == sha(dst)


@pytest.mark.parametrize("window", [1, 2, 4, 16])
def test_window_sizes(tmp_path, window):
    tx, rx, src, dst = transfer(tmp_path, os.urandom(10000), window=window)
    assert sha(src) == sha(dst)


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_random_20_percent_loss_both_ways(tmp_path, seed):
    tx, rx, src, dst = transfer(
        tmp_path, os.urandom(1024 * 12), window=4,
        make_send_chan=lambda s, p: Channel(s, p, seed=seed, loss=0.2),
        make_ack_chan=lambda s, p: Channel(s, p, seed=seed + 1, loss=0.2))
    assert sha(src) == sha(dst)
    assert tx["retransmissions"] > 0


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_loss_dup_corrupt_delay_reorder(tmp_path, seed):
    faults = dict(loss=0.1, dup=0.15, corrupt=0.1, reorder=0.2,
                  reorder_delay=0.02, delay=0.005, jitter=0.003)
    tx, rx, src, dst = transfer(
        tmp_path, os.urandom(1024 * 12), window=6,
        make_send_chan=lambda s, p: Channel(s, p, seed=seed, **faults),
        make_ack_chan=lambda s, p: Channel(s, p, seed=seed + 1, **faults))
    assert sha(src) == sha(dst)


def test_adaptive_rto_transfer(tmp_path):
    tx, rx, src, dst = transfer(
        tmp_path, os.urandom(1024 * 12), fixed=False,
        make_send_chan=lambda s, p: Channel(s, p, seed=7, loss=0.1, delay=0.01),
        make_ack_chan=lambda s, p: Channel(s, p, seed=8, loss=0.1, delay=0.01))
    assert sha(src) == sha(dst)