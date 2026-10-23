# tests/test_protocols.py
# Test suite for Stop-and-Wait. Every transfer test ends with a SHA-256 match,
# because "no exception" does not prove the file arrived correctly.
#
# FaultyChannel and RandomLossChannel are TEST-ONLY helpers. They are not the
# project's channel emulator (that is Sanvi's channel.py).
import hashlib
import os
import random
import socket
import threading

import pytest

from datagram.rto import RTOEstimator
from datagram.protocols.stop_wait import StopAndWait, split_file

RTO = 0.1


# ---------------------------------------------------------------- helpers
class FaultyChannel:
    """Applies scripted faults by send index (0 = first packet this channel sends)."""

    def __init__(self, sock, peer, drop=(), dup=(), corrupt=()):
        self.sock, self.peer = sock, peer
        self.drop, self.dup, self.corrupt = set(drop), set(dup), set(corrupt)
        self.count = 0

    def pump(self):
        pass

    def send(self, data):
        n = self.count
        self.count += 1
        if n in self.drop:
            return
        if n in self.corrupt:
            b = bytearray(data)
            b[-1] ^= 0x01                      # flip one bit
            data = bytes(b)
        self.sock.sendto(data, self.peer)
        if n in self.dup:
            self.sock.sendto(data, self.peer)


class RandomLossChannel:
    """Drops each packet with probability `loss`, seeded so runs repeat."""

    def __init__(self, sock, peer, loss, seed):
        self.sock, self.peer = sock, peer
        self.loss, self.rng = loss, random.Random(seed)

    def pump(self):
        pass

    def send(self, data):
        if self.rng.random() >= self.loss:
            self.sock.sendto(data, self.peer)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    return s


def transfer(tmp_path, data, make_send_chan=None, make_ack_chan=None,
             rto=RTO, max_retries=10):
    """Run one sender and one receiver on localhost. Returns (tx, rx, src, dst)."""
    src, dst = tmp_path / "src.bin", tmp_path / "dst.bin"
    src.write_bytes(data)

    s_sock, r_sock = make_socket(), make_socket()
    s_addr, r_addr = s_sock.getsockname(), r_sock.getsockname()
    make_send_chan = make_send_chan or (lambda sock, peer: FaultyChannel(sock, peer))
    make_ack_chan = make_ack_chan or (lambda sock, peer: FaultyChannel(sock, peer))

    sender = StopAndWait(s_sock, make_send_chan(s_sock, r_addr),
                         rto=rto, max_retries=max_retries,
                         est=RTOEstimator(fixed=rto))
    receiver = StopAndWait(r_sock, make_ack_chan(r_sock, s_addr),
                           rto=rto, linger=0.5, idle_timeout=5.0)

    out = {}

    def run_receiver():
        try:
            out["rx"] = receiver.receive_file(str(dst))
        except Exception as e:             # surface receiver errors in the test
            out["err"] = e

    t = threading.Thread(target=run_receiver)
    t.start()
    try:
        tx = sender.send_file(str(src))
    finally:
        t.join(timeout=15)
        s_sock.close()
        r_sock.close()
    assert not t.is_alive(), "receiver did not finish"
    assert "err" not in out, f"receiver raised: {out.get('err')!r}"
    return tx, out["rx"], src, dst


# ------------------------------------------------------ split_file (unit)
def test_split_empty_file(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"")
    assert split_file(str(p)) == []


def test_split_exact_multiple_has_no_stray_chunk(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"x" * 2048)
    assert [len(c) for c in split_file(str(p))] == [1024, 1024]


def test_split_short_last_chunk(tmp_path):
    p = tmp_path / "f"
    p.write_bytes(b"x" * 2500)
    assert [len(c) for c in split_file(str(p))] == [1024, 1024, 452]


# ------------------------------------------------ transfers: sizes, clean
@pytest.mark.parametrize("size", [0, 100, 1024, 2048, 2500, 5000])
def test_clean_transfer(tmp_path, size):
    data = os.urandom(size)
    tx, rx, src, dst = transfer(tmp_path, data, rto=0.3)
    assert sha(src) == sha(dst)
    assert rx["bytes_delivered"] == size
    assert tx["bytes_delivered"] == size
    assert tx["retransmissions"] == 0


# ------------------------------------------------------ faults, one at a time
def test_dropped_data_packet_is_retransmitted(tmp_path):
    tx, rx, src, dst = transfer(
        tmp_path, os.urandom(3000),
        make_send_chan=lambda s, p: FaultyChannel(s, p, drop={0}))
    assert sha(src) == sha(dst)
    assert tx["retransmissions"] >= 1


def test_dropped_ack_is_reacked_not_rewritten(tmp_path):
    # Dropping the first ACK makes the sender resend packet 0. The receiver must
    # re-ACK it WITHOUT writing it twice; a double write would break the hash.
    tx, rx, src, dst = transfer(
        tmp_path, os.urandom(3000),
        make_ack_chan=lambda s, p: FaultyChannel(s, p, drop={0}))
    assert sha(src) == sha(dst)
    assert tx["retransmissions"] >= 1
    assert rx["retransmissions"] >= 1      # receiver saw the duplicate


def test_duplicated_data_packet_is_written_once(tmp_path):
    tx, rx, src, dst = transfer(
        tmp_path, os.urandom(3000),
        make_send_chan=lambda s, p: FaultyChannel(s, p, dup={1}))
    assert sha(src) == sha(dst)
    assert rx["retransmissions"] >= 1


def test_corrupted_data_packet_is_discarded_then_recovered(tmp_path):
    tx, rx, src, dst = transfer(
        tmp_path, os.urandom(3000),
        make_send_chan=lambda s, p: FaultyChannel(s, p, corrupt={1}))
    assert sha(src) == sha(dst)
    assert tx["retransmissions"] >= 1


def test_corrupted_ack_is_ignored(tmp_path):
    tx, rx, src, dst = transfer(
        tmp_path, os.urandom(3000),
        make_ack_chan=lambda s, p: FaultyChannel(s, p, corrupt={0}))
    assert sha(src) == sha(dst)
    assert tx["retransmissions"] >= 1


def test_lost_final_ack_receiver_lingers_and_reacks_fin(tmp_path):
    # 5000 bytes = 5 DATA + 1 FIN -> receiver sends ACKs 0..5; index 5 is the FIN ACK.
    tx, rx, src, dst = transfer(
        tmp_path, os.urandom(5000),
        make_ack_chan=lambda s, p: FaultyChannel(s, p, drop={5}))
    assert sha(src) == sha(dst)
    assert tx["retransmissions"] >= 1      # sender had to resend the FIN
    assert rx["retransmissions"] >= 1      # receiver re-ACKed it while lingering


# ------------------------------------------------ random loss, both directions
@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_random_20_percent_loss_both_ways(tmp_path, seed):
    tx, rx, src, dst = transfer(
        tmp_path, os.urandom(10_000),
        make_send_chan=lambda s, p: RandomLossChannel(s, p, 0.20, seed),
        make_ack_chan=lambda s, p: RandomLossChannel(s, p, 0.20, seed + 100),
        rto=0.05, max_retries=20)
    assert sha(src) == sha(dst)


# ------------------------------------------------------------ failure paths
def test_sender_gives_up_after_max_retries(tmp_path):
    src = tmp_path / "src.bin"
    src.write_bytes(b"hello")
    s_sock, silent = make_socket(), make_socket()     # `silent` never replies
    sender = StopAndWait(s_sock, FaultyChannel(s_sock, silent.getsockname()),
                         rto=0.05, max_retries=3, est=RTOEstimator(fixed=0.05))
    with pytest.raises(TimeoutError):
        sender.send_file(str(src))
    assert sender.stats["packets_sent"] == 3
    assert sender.stats["retransmissions"] == 2
    s_sock.close()
    silent.close()


def test_receiver_gives_up_when_nothing_arrives(tmp_path):
    r_sock = make_socket()
    receiver = StopAndWait(r_sock, FaultyChannel(r_sock, ("127.0.0.1", 9)),
                           idle_timeout=0.2)
    with pytest.raises(TimeoutError):
        receiver.receive_file(str(tmp_path / "out.bin"))
    r_sock.close()