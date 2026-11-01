import socket
import time
from datagram.rto import RTOEstimator
from datagram.timers import RTTTracker
from datagram.packet import Packet, DATA, ACK, FIN
from datagram.protocols.base import ARQProtocol

CHUNK = 1024


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
                 idle_timeout=None, linger=None, est=None, reset_on_retx_ack=False):
        self.sock = sock
        self.channel = channel            # anything with .send(bytes)
        self.est = est or RTOEstimator(initial_rto=rto)          # sender: RTT estimator for adaptive RTO
        self.tracker = RTTTracker(self.est, reset_on_retx_ack=reset_on_retx_ack)
        self.rto = rto                    # seconds, fixed for now
        self.max_retries = max_retries    # total transmissions per packet
        self.idle_timeout = idle_timeout  # receiver: max silence before giving up
        # Receiver: after the FIN, stay up until this much SILENCE has passed,
        # re-ACKing repeated FINs. The window slides: each repeated FIN restarts
        # it. 10*rto means ~10 consecutive lost FINs are needed to strand the sender.
        self.idle_timeout = 3 * self.est.max_rto if idle_timeout is None else idle_timeout
        self.linger = 10 * rto if linger is None else linger
        self._reset_stats()

    def _reset_stats(self):
        # SENDER rule: packets_sent counts EVERY transmission, including
        # retransmissions. retransmissions counts only the repeats, so
        # first sends = packets_sent - retransmissions.
        # RECEIVER rule: packets_sent counts ACKs sent. retransmissions counts
        # duplicate packets received (and re-ACKed).
        self.stats = {"packets_sent": 0, "retransmissions": 0}

    # ------------------------------------------------------------ sender
    def _send_and_wait(self, pkt):
        """Send one packet; return only when its ACK arrives.

        max_retries = total transmissions (1 first send + max_retries-1 repeats).
        Raises TimeoutError if no ACK arrives after all of them.
        """
        raw = pkt.pack()
        for attempt in range(self.max_retries):
            self.tracker.on_send(pkt.seq , time.monotonic())

            self.channel.send(raw)
            self.stats["packets_sent"] += 1
            if attempt > 0:
                self.stats["retransmissions"] += 1

            # Deadline is computed ONCE per attempt. Every recvfrom gets only
            # the time remaining, so junk or stale ACKs cannot postpone it.
            
            current_rto = self.est.current_rto()

            deadline = time.monotonic() + current_rto

            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    self.tracker.on_timeout(pkt.seq)
                    break  # resend

                try:
                    self.sock.settimeout(min(remaining, 0.005))
                    self.channel.pump()

                    data, _addr = self.sock.recvfrom(2048)
                except socket.timeout:
                    if time.monotonic() < deadline:
                        continue
                    self.tracker.on_timeout(pkt.seq)
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
                    self.tracker.on_ack(pkt.seq, time.monotonic())
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

    # ---------------------------------------------------------- receiver
    def _send_ack(self, seq):
        """ACK carries ack=seq of the packet being acknowledged."""
        self.channel.send(Packet(seq=0, ack=seq, flags=ACK).pack())
        self.stats["packets_sent"] += 1

    def _recv_packet(self, timeout):
        """Return a valid Packet, None for junk/reset, raise socket.timeout."""
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise socket.timeout()

            try:
                self.sock.settimeout(min(remaining, 0.005))
                self.channel.pump()          # deliver any delayed ACKs now due

                data, _addr = self.sock.recvfrom(2048)

            except socket.timeout:
                if time.monotonic() < deadline:
                    continue                 # short poll expired, keep waiting
                raise                        # the real deadline passed

            except ConnectionResetError:
                return None                  # Windows: peer port was closed

            return Packet.unpack(data)       # None if corrupt
        

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

        # Sliding linger: if our FIN ACK was lost, the sender keeps
        # retransmitting the FIN. Keep answering until `linger` seconds of
        # silence. Each repeated FIN restarts the window.
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
                end = time.monotonic() + self.linger   # slide the window

        return {
            "packets_sent": self.stats["packets_sent"],
            "retransmissions": self.stats["retransmissions"],
            "bytes_delivered": bytes_delivered,
            "elapsed_s": elapsed,
        }