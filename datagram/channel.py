# datagram/channel.py
import heapq
import random
import time

from datagram.packet import HEADER_SIZE


class Channel:
    """A fake bad network between a protocol and the real UDP socket.

    send() decides what happens to a packet and schedules it; pump() does the
    actual delivery once its time has come. With delay=0 a packet is delivered
    immediately inside send(), exactly like v1.
    """

    def __init__(self, sock, peer, seed=42, loss=0.0, corrupt=0.0,
                 dup=0.0, reorder=0.0, reorder_delay=0.05,
                 delay=0.0, jitter=0.0, clock=time.monotonic):
        self.sock = sock
        self.peer = peer
        self.loss = loss                    # P(packet vanishes)
        self.corrupt = corrupt              # P(one bit flipped)
        self.dup = dup                      # P(packet delivered twice)
        self.reorder = reorder              # P(packet gets extra delay)
        self.reorder_delay = reorder_delay  # seconds of extra delay when reordered
        self.delay = delay                  # base one-way delay (seconds)
        self.jitter = jitter                # delay varies by +/- jitter seconds
        self.rng = random.Random(seed)      # our OWN generator -> reproducible
        self.clock = clock                  # injectable, so tests can fake time
        self._queue = []                    # min-heap of (deliver_at, counter, data)
        self._counter = 0                   # tie-breaker so bytes are never compared
        self.stats = {
            "sent": 0,
            "dropped": 0,
            "corrupted": 0,
            "duplicated": 0,
            "delivered": 0,
        }

    def send(self, data: bytes) -> None:
        self.stats["sent"] += 1

        # Roll EVERY die for EVERY packet, in a fixed order, even if the packet
        # is later dropped. That way changing one setting (say loss) never
        # shifts the random numbers used by the others, so experiments that
        # vary one parameter stay comparable.
        r_drop = self.rng.random()
        r_corrupt = self.rng.random()
        r_dup = self.rng.random()
        r_reorder = self.rng.random()
        r_jitter = [self.rng.random(), self.rng.random()]  # one per copy
        r_pos = self.rng.random()                          # which byte to flip
        r_bit = self.rng.random()                          # which bit to flip

        if r_drop < self.loss:
            self.stats["dropped"] += 1
            return

        if r_corrupt < self.corrupt:
            self.stats["corrupted"] += 1
            data = self._flip_bit(data, r_pos, r_bit)

        copies = 2 if r_dup < self.dup else 1
        if copies == 2:
            self.stats["duplicated"] += 1

        now = self.clock()
        for k in range(copies):
            # Each copy gets its OWN jitter, so a duplicate can overtake or
            # trail the original, like on a real network.
            d = self.delay + (2 * r_jitter[k] - 1) * self.jitter
            if r_reorder < self.reorder:
                d += self.reorder_delay  # held back, so later packets overtake it
            d = max(0.0, d)
            heapq.heappush(self._queue, (now + d, self._counter, data))
            self._counter += 1

        self.pump()  # deliver anything already due (everything, if delay=0)

    def pump(self) -> None:
        """Deliver every queued packet whose time has come."""
        now = self.clock()
        while self._queue and self._queue[0][0] <= now:
            _, _, data = heapq.heappop(self._queue)
            self.sock.sendto(data, self.peer)
            self.stats["delivered"] += 1

    def pending(self) -> int:
        """Number of packets still waiting in the delay queue."""
        return len(self._queue)

    def _flip_bit(self, data: bytes, r_pos: float, r_bit: float) -> bytes:
        if not data:
            return data
        buf = bytearray(data)
        # Prefer a payload byte so the checksum is what catches it
        if len(buf) > HEADER_SIZE:
            i = HEADER_SIZE + int(r_pos * (len(buf) - HEADER_SIZE))
        else:
            i = int(r_pos * len(buf))
        buf[i] ^= 1 << int(r_bit * 8)
        return bytes(buf)