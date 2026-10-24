# tests/test_packet.py
import os
import zlib

from datagram.packet import Packet, DATA, ACK, FIN, HEADER_SIZE, crc32


def make_packet():
    return Packet(seq=5, ack=3, flags=DATA, payload=b"hello world")


def test_header_size_is_15_bytes():
    assert HEADER_SIZE == 15


def test_round_trip():
    p = make_packet()
    assert Packet.unpack(p.pack()) == p


def test_empty_payload_round_trip():
    # An empty file or a pure ACK has no payload, and must still work
    p = Packet(seq=0, ack=7, flags=ACK, payload=b"")
    assert Packet.unpack(p.pack()) == p


def test_combined_flags_round_trip():
    p = Packet(seq=9, ack=0, flags=DATA | FIN, payload=b"last chunk")
    assert Packet.unpack(p.pack()) == p


def test_corrupted_payload_is_rejected():
    raw = bytearray(make_packet().pack())
    raw[-1] ^= 0b00000001  # flip a single bit in the payload
    assert Packet.unpack(bytes(raw)) is None


def test_corrupted_header_is_rejected():
    raw = bytearray(make_packet().pack())
    raw[0] ^= 0b00000001  # flip a bit in the seq field
    assert Packet.unpack(bytes(raw)) is None


def test_truncated_header_is_rejected():
    raw = make_packet().pack()
    assert Packet.unpack(raw[:HEADER_SIZE - 1]) is None


def test_truncated_payload_is_rejected():
    raw = make_packet().pack()
    assert Packet.unpack(raw[:-3]) is None


def test_empty_bytes_is_rejected():
    assert Packet.unpack(b"") is None


def test_crc32_known_vector():
    assert crc32(b"123456789") == 0xCBF43926   # standard CRC-32 check value


def test_crc32_matches_reference_implementation():
    # zlib is used here ONLY as a reference answer to check our own crc32
    for n in (0, 1, 15, 100, 1039):
        data = os.urandom(n)
        assert crc32(data) == zlib.crc32(data) & 0xFFFFFFFF