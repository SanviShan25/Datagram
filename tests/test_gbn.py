# tests/test_gbn.py
# Tests for Go-Back-N. Contract these tests assume (agree it with the team,
# then keep README and tests in sync if you change any of it):
#   GoBackN(sock, channel, *, window=8, rto=0.5, max_retries=10,
#           idle_timeout=5.0, linger=None)
#   - ack = N means "everything up to and including N arrived in order"
#   - FIN is just the last packet in the sequence (seq = number of data chunks)
#   - receiver discards out-of-order packets and re-ACKs the last in-order one
#   - receiver sends NO ACK if nothing in-order has arrived yet (expected == 0)
#   - max_retries = consecutive timeouts without progress before TimeoutError
#   - timeout resends the WHOLE outstanding window; each resent packet counts
#     as one retransmission
import hashlib
import math
import os
import socket
import threading

import pytest

from datagram.channel import Channel
from datagram.packet import Packet, DATA, ACK, FIN
from datagram.protocols.gbn import GoBackN
from datagram.protocols.stop_wait import StopAndWait
from datagram.rto import RTOEstimator

RTO = 0.05


# ---------------------------------------------------------------- helpers
def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def make_socket():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    return s


class ScriptedChannel:
    """Test-only: drops/corrupts by send index. Not the project's Channel."""

    def __init__(self, sock, peer, drop=()):
        self.sock, self.peer, self.drop, self.count = sock, peer, set(drop), 0

    def send(self, data):
        n = self.count
        self.count += 1
        if n not in self.drop:
            self.sock.sendto(data, self.peer)


def transfer(tmp_path, size, protocol=GoBackN, window=8, loss=0.0, corrupt=0.0,
             seed=42, rto=RTO, max_retries=60, ack_drop=(), delay =0.0):
    src, dst = tmp_path / "src.bin", tmp_path / "dst.bin"
    src.write_bytes(os.urandom(size))
    s_sock, r_sock = make_socket(), make_socket()
    out, err = {}, []
    try:
        s_addr, r_addr = s_sock.getsockname(), r_sock.getsockname()
        s_chan = Channel(s_sock, r_addr, seed=seed, loss=loss, corrupt=corrupt, delay=delay)
        if ack_drop:
            r_chan = ScriptedChannel(r_sock, s_addr, drop=ack_drop)
        else:
            r_chan = Channel(r_sock, s_addr, seed=seed + 1, loss=loss, corrupt=corrupt, delay=delay)
        kw = {"window": window} if protocol is GoBackN else {"est": RTOEstimator(fixed=rto)}
        sender = protocol(s_sock, s_chan, rto=rto, max_retries=max_retries, **kw)
        receiver = protocol(r_sock, r_chan, rto=rto, max_retries=max_retries,
                            idle_timeout=5.0, linger=0.3, **kw)

        def worker():
            try:
                out.update(receiver.receive_file(str(dst)))
            except Exception as e:
                err.append(e)

        t = threading.Thread(target=worker, daemon=True)
        t.start()
        try:
            tx = sender.send_file(str(src))
        finally:
            t.join(timeout=15)
    finally:
        s_sock.close()
        r_sock.close()
    assert not t.is_alive(), "receiver hung"
    if err:
        raise err[0]
    assert sha(src) == sha(dst), "HASH MISMATCH"
    assert tx["bytes_delivered"] == size and out["bytes_delivered"] == size
    return tx, out


# ------------------------------------------- clean link, many windows/sizes
@pytest.mark.parametrize("window", [1, 2, 4, 8, 16])
@pytest.mark.parametrize("size", [0, 1, 1024, 2500, 50000])
def test_clean_transfer(tmp_path, size, window):
    tx, rx = transfer(tmp_path, size, window=window, rto=0.3)
    assert tx["retransmissions"] == 0
    assert rx["retransmissions"] == 0
    assert tx["packets_sent"] == math.ceil(size / 1024) + 1     # data + FIN


def test_window_1_behaves_like_stop_and_wait(tmp_path):
    gbn, _ = transfer(tmp_path, 5000, window=1, rto=0.3)
    sw, _ = transfer(tmp_path, 5000, protocol=StopAndWait, rto=0.3)
    assert gbn["packets_sent"] == sw["packets_sent"]
    assert gbn["retransmissions"] == sw["retransmissions"] == 0


# ------------------------------------------------ loss, corruption, seeds
@pytest.mark.parametrize("window", [1, 4, 8])
@pytest.mark.parametrize("loss,corrupt", [(0.2, 0.0), (0.4, 0.0), (0.0, 0.1), (0.2, 0.1)])
def test_recovers_from_impairment(tmp_path, window, loss, corrupt):
    tx, _ = transfer(tmp_path, 20000, window=window, loss=loss, corrupt=corrupt)
    assert tx["retransmissions"] > 0


@pytest.mark.parametrize("seed", range(15))
def test_seed_sweep(tmp_path, seed):
    transfer(tmp_path, 10000, window=8, loss=0.3, corrupt=0.1, seed=seed)


# -------------------------------------- Go-Back-N specific sender behaviour
def test_lost_ack_is_covered_by_a_later_cumulative_ack(tmp_path):
    # Drop only the ACK for packet 0. The ACK for packet 1 acknowledges both,
    # so with a big enough RTO the sender must NOT retransmit anything.
    tx, _ = transfer(tmp_path, 5000, window=8, rto=0.5, ack_drop={0})
    assert tx["retransmissions"] == 0


def _silent_receiver_run(tmp_path, window, max_retries, rto=0.2):
    """Sender talks to a socket that never ACKs. Returns (seqs it saw, sender)."""
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * 10_000)                   # 10 chunks + FIN
    s_sock, silent = make_socket(), make_socket()
    sender = GoBackN(s_sock, ScriptedChannel(s_sock, silent.getsockname()),
                     window=window, rto=rto, max_retries=max_retries)
    try:
        with pytest.raises(TimeoutError):
            sender.send_file(str(src))
        silent.settimeout(0.05)
        seqs = []
        while True:
            try:
                data, _ = silent.recvfrom(2048)
            except socket.timeout:
                break
            seqs.append(Packet.unpack(data).seq)
    finally:
        s_sock.close()
        silent.close()
    return seqs, sender


def test_never_more_than_window_packets_outstanding(tmp_path):
    seqs, sender = _silent_receiver_run(tmp_path, window=4, max_retries=1)
    assert seqs == [0, 1, 2, 3]                      # first burst = exactly one window
    assert sender.stats["packets_sent"] == 4


def test_timeout_resends_the_whole_window(tmp_path):
    seqs, sender = _silent_receiver_run(tmp_path, window=3, max_retries=2)
    assert seqs == [0, 1, 2, 0, 1, 2]                # window, then the same window again
    assert sender.stats["retransmissions"] == 3


def test_gives_up_after_max_retries_timeouts(tmp_path):
    seqs, sender = _silent_receiver_run(tmp_path, window=2, max_retries=3)
    assert seqs == [0, 1] * 3
    assert sender.stats["retransmissions"] == 4


# ------------------------------------ Go-Back-N specific receiver behaviour
class RawPeer:
    """A hand-driven peer so a test can feed the receiver exact packets."""

    def __init__(self, tmp_path):
        self.r_sock, self.t_sock = make_socket(), make_socket()
        self.path = tmp_path / "out.bin"
        self.receiver = GoBackN(self.r_sock,
                                Channel(self.r_sock, self.t_sock.getsockname()),
                                window=4, rto=0.1, linger=0.1, idle_timeout=3.0)
        self.out, self.err = {}, []

        def worker():
            try:
                self.out.update(self.receiver.receive_file(str(self.path)))
            except Exception as e:
                self.err.append(e)

        self.thread = threading.Thread(target=worker, daemon=True)
        self.thread.start()

    def send(self, seq, flags=DATA, payload=b""):
        self.t_sock.sendto(Packet(seq=seq, ack=0, flags=flags, payload=payload).pack(),
                           self.r_sock.getsockname())

    def ack(self, timeout=1.0):
        """Next ACK number the receiver sent, or None if it stayed silent."""
        self.t_sock.settimeout(timeout)
        try:
            data, _ = self.t_sock.recvfrom(2048)
        except socket.timeout:
            return None
        pkt = Packet.unpack(data)
        assert pkt.flags & ACK
        return pkt.ack

    def finish(self):
        self.thread.join(timeout=5)
        self.r_sock.close()
        self.t_sock.close()
        assert not self.thread.is_alive(), "receiver hung"
        if self.err:
            raise self.err[0]


def test_receiver_discards_out_of_order_and_reacks_last_in_order(tmp_path):
    p = RawPeer(tmp_path)
    p.send(0, payload=b"a"); assert p.ack() == 0
    p.send(2, payload=b"c"); assert p.ack() == 0     # gap: re-ACK 0, NOT 2
    p.send(1, payload=b"b"); assert p.ack() == 1
    p.send(2, payload=b"c"); assert p.ack() == 2     # now in order
    p.send(3, flags=FIN);    assert p.ack() == 3
    p.finish()
    assert p.path.read_bytes() == b"abc"             # packet 2 written exactly once


def test_receiver_stays_silent_until_something_arrives_in_order(tmp_path):
    p = RawPeer(tmp_path)
    p.send(1, payload=b"b")
    assert p.ack(timeout=0.3) is None                # nothing in order yet: no ACK
    p.send(0, payload=b"a"); assert p.ack() == 0
    p.send(1, payload=b"b"); assert p.ack() == 1
    p.send(2, flags=FIN);    assert p.ack() == 2
    p.finish()
    assert p.path.read_bytes() == b"ab"


def test_receiver_does_not_write_duplicates(tmp_path):
    p = RawPeer(tmp_path)
    p.send(0, payload=b"a"); assert p.ack() == 0
    p.send(0, payload=b"a"); assert p.ack() == 0     # duplicate: re-ACK, no write
    p.send(1, flags=FIN);    assert p.ack() == 1
    p.finish()
    assert p.path.read_bytes() == b"a"


@pytest.mark.parametrize("delay", [0.01, 0.02])
def test_delay_alone_needs_no_retransmissions(tmp_path, delay):
 tx, _ = transfer(tmp_path, 20000, window=8, rto=0.3, delay=delay)
 assert tx["retransmissions"] == 0