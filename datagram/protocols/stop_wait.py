import socket
import time
from datagram.packet import Packet, DATA, ACK, FIN
from datagram.protocols.base import ARQProtocol

CHUNK = 1024

"""
# TEMPORARY: remove when Sanvi's channel lands on main.
class RawChannel:
    def __init__(self, sock, peer):
        self.sock, self.peer = sock, peer

    def send(self, data):
        self.sock.sendto(data, self.peer)
"""

def split_file(path, chunk_size=CHUNK):
    """Return a list of byte strings of at most chunk_size bytes.

    Empty file -> []. A file of exactly 2*chunk_size -> 2 chunks,
    because the loop stops on the first empty read (no stray empty chunk).
    """
    chunks = []
    with open(path, "rb") as f:
        while True:
            data = f.read(chunk_size)
            if not data:
                break
            chunks.append(data)
    return chunks


class StopAndWait(ARQProtocol):
    def __init__(self, sock, channel, rto=0.5, max_retries=10,
                 idle_timeout=5.0, linger=None):
        self.sock = sock
        self.channel = channel          # anything with .send(bytes)
        self.rto = rto                  # seconds, fixed for now
        self.max_retries = max_retries  # total transmissions per packet
        self.idle_timeout = idle_timeout  # receiver: max silence before giving up
        # receiver: how long to stay up after the FIN to re-ACK repeated FINs
        self.linger = 3 * rto if linger is None else linger
        self._reset_stats()

    def _reset_stats(self):
        # SENDER rule: packets_sent counts EVERY transmission, including
        # retransmissions. retransmissions counts only the repeats, so
        # first sends = packets_sent - retransmissions.
        # RECEIVER rule: packets_sent counts ACKs sent. retransmissions counts
        # duplicate packets received (and re-ACKed).
        self.stats = {"packets_sent": 0, "retransmissions": 0}

    #sender
    def _send_and_wait(self, pkt):
        """Send one packet; return only when its ACK arrives.

        max_retries = total transmissions (1 first send + max_retries-1 repeats).
        Raises TimeoutError if no ACK arrives after all of them.
        """
        raw = pkt.pack()
        for attempt in range(self.max_retries):
            self.channel.send(raw)
            self.stats["packets_sent"] += 1
            if attempt > 0:
                self.stats["retransmissions"] += 1

            # Deadline is computed ONCE per attempt. Every recvfrom gets only
            # the time remaining, so junk or stale ACKs cannot postpone it.
            deadline = time.monotonic() + self.rto

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break  # resend

                try:
                    self.sock.settimeout(remaining)
                    data, _addr = self.sock.recvfrom(2048)
                except socket.timeout:
                    break  # resend
                except ConnectionResetError:
                    # Windows WinError 10054: nothing listening on the peer port.
                    # Treat as "no ACK yet". Sleep briefly so we don't spin,
                    # and keep waiting until the deadline.
                    time.sleep(min(remaining, 0.01))
                    continue

                reply = Packet.unpack(data)
                if reply is None:
                    continue  # corrupt or truncated: ignore
                if (reply.flags & ACK) and reply.ack == pkt.seq:
                    return
                # stale or duplicate ACK: ignore, deadline unchanged

        raise TimeoutError(
            f"no ACK for seq={pkt.seq} after {self.max_retries} transmissions"
        )

    def send_file(self, path):
        self._reset_stats()
        chunks = split_file(path)
        start = time.monotonic()

        for i, chunk in enumerate(chunks):
            self._send_and_wait(Packet(seq=i, ack=0, flags=DATA, payload=chunk))

        # FIN takes the next sequence number, empty payload, same wait logic.
        self._send_and_wait(Packet(seq=len(chunks), ack=0, flags=FIN, payload=b""))

        elapsed = time.monotonic() - start
        return {
            "packets_sent": self.stats["packets_sent"],
            "retransmissions": self.stats["retransmissions"],
            "bytes_delivered": sum(len(c) for c in chunks),
            "elapsed_s": elapsed,
        }

    #receiver
    def _send_ack(self, seq):
        """ACK carries ack=seq of the packet being acknowledged."""
        self.channel.send(Packet(seq=0, ack=seq, flags=ACK).pack())
        self.stats["packets_sent"] += 1

    def _recv_packet(self, timeout):
        """Return a valid Packet, None for junk/reset, raise socket.timeout."""
        self.sock.settimeout(timeout)
        try:
            data, _addr = self.sock.recvfrom(2048)
        except ConnectionResetError:
            return None  # Windows: an earlier send hit a closed port; ignore
        return Packet.unpack(data)  # None if corrupt

    def receive_file(self, path):
        self._reset_stats()
        start = time.monotonic()
        expected = 0
        bytes_delivered = 0
        fin_seq = None
        last_valid = time.monotonic()

        with open(path, "wb") as f:
            while fin_seq is None:
                remaining = self.idle_timeout - (time.monotonic() - last_valid)
                if remaining <= 0:
                    raise TimeoutError(
                        f"receiver idle for {self.idle_timeout}s, expected seq={expected}"
                    )
                try:
                    pkt = self._recv_packet(remaining)
                except socket.timeout:
                    continue  # loop re-checks the idle deadline
                if pkt is None:
                    continue  # corrupt or reset: ignore
                last_valid = time.monotonic()

                if pkt.flags & FIN:
                    if pkt.seq == expected:
                        self._send_ack(pkt.seq)
                        fin_seq = pkt.seq
                    continue

                if pkt.flags & DATA:
                    if pkt.seq == expected:
                        f.write(pkt.payload)           # new data: write once
                        bytes_delivered += len(pkt.payload)
                        expected += 1
                        self._send_ack(pkt.seq)
                    elif pkt.seq < expected:
                        self.stats["retransmissions"] += 1
                        self._send_ack(pkt.seq)        # duplicate: re-ACK, no write
                    # seq > expected cannot happen in stop-and-wait: ignore

        elapsed = time.monotonic() - start  # measured BEFORE lingering

        # Linger: if our FIN ACK was lost, the sender retransmits the FIN.
        # Keep answering it so the sender does not fail on a finished transfer.
        end = time.monotonic() + self.linger
        while True:
            remaining = end - time.monotonic()
            if remaining <= 0:
                break
            try:
                pkt = self._recv_packet(remaining)
            except socket.timeout:
                break
            if pkt is not None and (pkt.flags & FIN) and pkt.seq == fin_seq:
                self.stats["retransmissions"] += 1
                self._send_ack(pkt.seq)

        return {
            "packets_sent": self.stats["packets_sent"],
            "retransmissions": self.stats["retransmissions"],
            "bytes_delivered": bytes_delivered,
            "elapsed_s": elapsed,
        }