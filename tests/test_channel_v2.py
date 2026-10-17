# tests/test_channel_v2.py
from datagram.channel import Channel
from datagram.packet import Packet, DATA

PEER = ("127.0.0.1", 9999)


class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendto(self, data, peer):
        self.sent.append(data)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def make(**kw):
    clock, sock = FakeClock(), FakeSocket()
    ch = Channel(sock, PEER, clock=clock, **kw)
    return ch, sock, clock


def run_sequence(seed, n=200, **kw):
    """Send n numbered packets 10 ms apart; return seq numbers in arrival order."""
    ch, sock, clock = make(seed=seed, **kw)
    for i in range(n):
        ch.send(Packet(i, 0, DATA, b"x").pack())
        clock.advance(0.01)
        ch.pump()
    clock.advance(10)
    ch.pump()
    return [Packet.unpack(d).seq for d in sock.sent]


def test_no_delay_delivers_immediately():
    ch, sock, _ = make(seed=1)
    ch.send(Packet(1, 0, DATA, b"hi").pack())
    assert len(sock.sent) == 1


def test_duplication_delivers_twice():
    ch, sock, _ = make(seed=1, dup=1.0)
    for i in range(100):
        ch.send(Packet(i, 0, DATA, b"x").pack())
    assert len(sock.sent) == 200
    assert ch.stats["duplicated"] == 100


def test_delay_holds_packet_until_due():
    ch, sock, clock = make(seed=1, delay=0.1)
    ch.send(Packet(1, 0, DATA, b"hi").pack())
    assert len(sock.sent) == 0
    clock.advance(0.05)
    ch.pump()
    assert len(sock.sent) == 0          # still too early
    clock.advance(0.06)
    ch.pump()
    assert len(sock.sent) == 1          # now due


def test_jitter_stays_within_bounds():
    ch, _, _ = make(seed=2, delay=0.1, jitter=0.05)
    for i in range(500):
        ch.send(Packet(i, 0, DATA, b"x").pack())
    times = [t for t, _, _ in ch._queue]
    assert all(0.05 <= t <= 0.15 for t in times)
    assert len(set(times)) > 400        # and they really do vary


def test_reordering_changes_arrival_order_but_loses_nothing():
    seqs = run_sequence(seed=3, reorder=0.3, reorder_delay=1.0)
    assert seqs != sorted(seqs)         # some packets arrived out of order
    assert sorted(seqs) == list(range(200))


def test_no_reordering_keeps_order():
    seqs = run_sequence(seed=3)
    assert seqs == list(range(200))


def test_same_seed_same_arrival_order():
    kw = dict(loss=0.1, dup=0.1, reorder=0.2, reorder_delay=0.5,
              delay=0.05, jitter=0.02)
    assert run_sequence(5, **kw) == run_sequence(5, **kw)


def test_different_seed_different_arrival_order():
    kw = dict(reorder=0.3, reorder_delay=1.0)
    assert run_sequence(5, **kw) != run_sequence(6, **kw)