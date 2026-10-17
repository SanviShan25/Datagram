# tests/test_channel.py
from datagram.channel import Channel
from datagram.packet import Packet, DATA


class FakeSocket:
    def __init__(self):
        self.sent = []

    def sendto(self, data, peer):
        self.sent.append(data)


def run(seed, n=10_000, **kwargs):
    sock = FakeSocket()
    ch = Channel(sock, ("127.0.0.1", 9999), seed=seed, **kwargs)
    pkt = Packet(1, 0, DATA, b"x" * 100).pack()
    for _ in range(n):
        ch.send(pkt)
    return ch, sock


def test_loss_rate_is_honoured():
    ch, _ = run(seed=1, loss=0.10)
    assert 0.09 < ch.stats["dropped"] / ch.stats["sent"] < 0.11


def test_zero_loss_delivers_everything():
    ch, sock = run(seed=1, loss=0.0, n=1000)
    assert len(sock.sent) == 1000


def test_same_seed_same_outcome():
    a, _ = run(seed=7, n=1000, loss=0.2, corrupt=0.2)
    b, _ = run(seed=7, n=1000, loss=0.2, corrupt=0.2)
    assert a.stats == b.stats


def test_different_seed_different_outcome():
    a, _ = run(seed=1, n=1000, loss=0.2)
    b, _ = run(seed=2, n=1000, loss=0.2)
    assert a.stats != b.stats


def test_corruption_flips_exactly_one_bit():
    pkt = Packet(1, 0, DATA, b"x" * 100).pack()
    _, sock = run(seed=3, n=200, corrupt=1.0)
    for out in sock.sent:
        diff = sum(bin(a ^ b).count("1") for a, b in zip(pkt, out))
        assert diff == 1


def test_checksum_catches_every_corrupted_packet():
    _, sock = run(seed=4, n=500, corrupt=1.0)
    assert all(Packet.unpack(out) is None for out in sock.sent)