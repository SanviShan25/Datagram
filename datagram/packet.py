# datagram/packet.py
import struct
from dataclasses import dataclass

# "!" = network byte order, no padding. I=4 bytes, B=1 byte, H=2 bytes.
# Fields: seq(4) ack(4) flags(1) payload_len(2) checksum(4) = 15 bytes
HEADER_FORMAT = "!IIBHI"
HEADER_SIZE = struct.calcsize(HEADER_FORMAT)  # 15

# Flags are bits, so they can be combined, e.g. DATA | FIN
DATA = 0b001
ACK = 0b010
FIN = 0b100

# ---------------------------------------------------------------------------
# Handwritten CRC-32 (IEEE 802.3, reflected). No zlib / binascii.
# A CRC treats the data as one huge binary number and keeps the remainder of
# dividing it by a fixed polynomial. Any flipped bit changes the remainder.
# ---------------------------------------------------------------------------
_POLY = 0xEDB88320  # CRC-32 polynomial, bit-reversed form


def _make_table():
    """Precompute the CRC of every possible single byte (0..255)."""
    table = []
    for i in range(256):
        crc = i
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ _POLY
            else:
                crc >>= 1
        table.append(crc)
    return table


_TABLE = _make_table()


def crc32(data: bytes) -> int:
    """CRC-32 of `data`, as an unsigned 32-bit integer."""
    crc = 0xFFFFFFFF                      # standard starting value
    for byte in data:
        crc = (crc >> 8) ^ _TABLE[(crc ^ byte) & 0xFF]
    return crc ^ 0xFFFFFFFF               # standard final inversion


@dataclass
class Packet:
    seq: int
    ack: int
    flags: int
    payload: bytes = b""

    def pack(self) -> bytes:
        """Serialise to wire bytes, computing the checksum last."""
        # The checksum lives inside the header but covers the header, so we
        # build the header with checksum=0 first, then fill the real value in.
        header = struct.pack(HEADER_FORMAT, self.seq, self.ack, self.flags,
                             len(self.payload), 0)
        checksum = crc32(header + self.payload)
        header = struct.pack(HEADER_FORMAT, self.seq, self.ack, self.flags,
                             len(self.payload), checksum)
        return header + self.payload

    @classmethod
    def unpack(cls, raw: bytes):
        """Parse wire bytes. Returns None if bad: the caller just discards it."""
        # Corrupt/truncated packets are normal on a lossy network,
        # so we return None instead of raising an exception.
        if len(raw) < HEADER_SIZE:
            return None  # truncated header

        seq, ack, flags, length, checksum = struct.unpack(
            HEADER_FORMAT, raw[:HEADER_SIZE])
        payload = raw[HEADER_SIZE:]

        if len(payload) != length:
            return None  # truncated or padded payload

        # Receiver recomputes the checksum the same way the sender did:
        # same header bytes with the checksum field zeroed.
        zeroed = struct.pack(HEADER_FORMAT, seq, ack, flags, length, 0)
        if crc32(zeroed + payload) != checksum:
            return None  # corrupted in transit

        return cls(seq, ack, flags, payload)