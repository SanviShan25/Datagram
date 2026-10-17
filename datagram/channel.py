# datagram/channel.py
import random

from datagram.packet import HEADER_SIZE


class Channel:
    def __init__(self, sock, peer, seed=42, loss=0.0, corrupt=0.0):
        self.sock = sock
        self.peer = peer
        self.loss = loss
        self.corrupt = corrupt
        self.rng = random.Random(seed)
        self.stats = {
            "sent": 0,
            "dropped": 0,
            "corrupted": 0,
            "delivered": 0,
        }

    def send(self, data: bytes) -> None:
        self.stats["sent"] += 1

        # Always consume the same two random numbers per packet, so changing
        # one setting (e.g. loss) doesn't shift the other's random stream.
        drop_roll = self.rng.random()
        corrupt_roll = self.rng.random()

        if drop_roll < self.loss:
            self.stats["dropped"] += 1
            return

        if corrupt_roll < self.corrupt:
            self.stats["corrupted"] += 1
            data = self._flip_bit(data)

        self.sock.sendto(data, self.peer)
        self.stats["delivered"] += 1

    def _flip_bit(self, data: bytes) -> bytes:
        if not data:
            return data

        buf = bytearray(data)

        # Prefer a payload byte so the checksum is what catches it
        if len(buf) > HEADER_SIZE:
            i = self.rng.randrange(HEADER_SIZE, len(buf))
        else:
            i = self.rng.randrange(len(buf))

        bit = self.rng.randrange(8)
        buf[i] ^= (1 << bit)

        return bytes(buf)