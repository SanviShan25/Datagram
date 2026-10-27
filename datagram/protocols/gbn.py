import socket
import time

from datagram.packet import Packet, DATA, ACK, FIN
from datagram.protocols.base import ARQProtocol
from datagram.protocols.stop_wait import split_file
from datagram.rto import RTOEstimator
from datagram.timers import RTTTracker


class GoBackN(ARQProtocol):
    """Go-Back-N ARQ: up to `window` packets in flight, cumulative ACKs,
    receiver accepts only in-order packets, one timer for the oldest
    unACKed packet. window=1 behaves like Stop-and-Wait."""

    def __init__(self, sock, channel, *, window=8, rto=0.5, max_retries=10,
                 idle_timeout=None, est=None, linger=None,
                 reset_on_retx_ack=False):
        if window < 1:
            raise ValueError("window must be at least 1")
        self.sock = sock
        self.channel = channel
        self.window = window
        self.est = est or RTOEstimator(initial_rto=rto)
        self.tracker = RTTTracker(self.est, reset_on_retx_ack=reset_on_retx_ack)
        self.rto = rto
        # max_retries = consecutive timeouts WITHOUT progress before giving up.
        self.max_retries = max_retries
        # Receiver: max silence before giving up. Defaults to 3x the largest
        # RTO the estimator can back off to, so backoff cannot trip it early.
        self.idle_timeout = (3 * self.est.max_rto if idle_timeout is None
                             else idle_timeout)
        # Receiver: silence needed after the FIN before it stops re-ACKing.
        self.linger = 10 * rto if linger is None else linger
        self._reset_stats()

    def _reset_stats(self):
        # packets_sent counts EVERY transmission (sender: data/FIN incl.
        # retransmissions; receiver: every ACK). retransmissions: sender = one
        # per resent packet; receiver = duplicates and repeated FINs received.
        self.stats = {"packets_sent": 0, "retransmissions": 0}

    # ------------------------------------------------------------ plumbing
    def _transmit(self, raw, is_retransmission):
        """Send one packet and count it. Every sender transmission goes here."""
        self.channel.send(raw)
        self.stats["packets_sent"] += 1
        if is_retransmission:
            self.stats["retransmissions"] += 1

    def _send_ack(self, ack_number):
        """ACKs also go through the channel, because ACKs can be lost too."""
        self.channel.send(Packet(seq=0, ack=ack_number, flags=ACK).pack())
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
                if hasattr(self.channel, "pump"):
                    self.channel.pump()   # deliver any delayed ACKs now due
                data, _addr = self.sock.recvfrom(2048)
            except socket.timeout:
                if time.monotonic() < deadline:
                    continue              # short poll expired, keep waiting
                raise                     # the real deadline passed
            except ConnectionResetError:
                return None               # Windows: peer port was closed
            return Packet.unpack(data)    # None if corrupt

    # -------------------------------------------------------------- sender
    def send_file(self, path):
        self._reset_stats()
        chunks = split_file(path)
        start = time.monotonic()

        # Pre-pack everything: index in this list == sequence number.
        # The FIN is just the last packet and goes through the window too.
        packets = [
            Packet(seq=i, ack=0, flags=DATA, payload=chunk).pack()
            for i, chunk in enumerate(chunks)
        ]
        packets.append(Packet(seq=len(chunks), ack=0, flags=FIN,
                              payload=b"").pack())
        total = len(packets)
        base = 0          # oldest unACKed packet
        next_seq = 0      # next packet to send for the first time
        timeouts = 0      # consecutive timeouts without progress
        deadline = None   # when the timer for `base` expires

        while base < total:
            # (a) Fill the window with first sends.
            while next_seq < total and next_seq < base + self.window:
                self._transmit(packets[next_seq], False)
                self.tracker.on_send(next_seq, time.monotonic())
                if base == next_seq:
                    # Window was empty: this packet is now the oldest.
                    deadline = time.monotonic() + self.est.current_rto()
                next_seq += 1

            # (b) Time left for the oldest packet. Computed fresh every pass
            # so stale ACKs and junk cannot push the deadline away.
            remaining = deadline - time.monotonic()

            # (c) Timeout: go back and resend the WHOLE outstanding window.
            if remaining <= 0:
                timeouts += 1
                if timeouts >= self.max_retries:
                    raise TimeoutError(
                        f"no progress at base={base} after {timeouts} "
                        f"consecutive timeouts"
                    )
                # Mark every packet in the window as retransmitted (Karn: no
                # RTT sample from them). Only the oldest packet backs the RTO
                # off, so one timeout doubles it once, not once per packet.
                for seq in range(base, next_seq):
                    self.tracker.on_timeout(seq, backoff=(seq == base))
                for seq in range(base, next_seq):
                    self._transmit(packets[seq], True)
                    self.tracker.on_send(seq, time.monotonic())
                # Restart AFTER the backoff, so the new deadline uses it.
                deadline = time.monotonic() + self.est.current_rto()
                continue

            # (d) Wait for an ACK, but only for the time that is left.
            try:
                reply = self._recv_packet(remaining)
            except socket.timeout:
                continue                  # loop re-checks the deadline
            if reply is None:
                # Junk, or a Windows reset. Short sleep so a burst of resets
                # cannot spin the CPU; the deadline is NOT touched.
                time.sleep(min(0.005, max(0.0, deadline - time.monotonic())))
                continue
            if not (reply.flags & ACK):
                continue

            # Cumulative ACK: accept only base <= ack < next_seq.
            if base <= reply.ack < next_seq:
                # Packets below reply.ack are covered by the cumulative ACK:
                # drop them from the tracker (no RTT sample from them).
                for seq in range(base, reply.ack):
                    self.tracker.discard(seq)
                # The ACKed packet itself may feed the RTO estimator
                # (tracker skips it if it was ever retransmitted: Karn).
                self.tracker.on_ack(reply.ack, time.monotonic())
                base = reply.ack + 1      # window slides
                timeouts = 0              # progress resets the counter
                if base < next_seq:
                    # Packets still outstanding: restart for the new oldest.
                    deadline = time.monotonic() + self.est.current_rto()
            # else: stale or impossible ACK -> ignore, timer untouched.

        elapsed = time.monotonic() - start
        return {
            "packets_sent": self.stats["packets_sent"],
            "retransmissions": self.stats["retransmissions"],
            "bytes_delivered": sum(len(c) for c in chunks),
            "elapsed_s": elapsed,
        }

    # ------------------------------------------------------------ receiver
    def receive_file(self, path):
        self._reset_stats()
        start = time.monotonic()
        expected = 0          # next in-order sequence number wanted
        delivered = 0         # payload bytes written
        fin_seq = None
        last_valid = time.monotonic()

        with open(path, "wb") as f:
            while fin_seq is None:
                remaining = self.idle_timeout - (time.monotonic() - last_valid)
                if remaining <= 0:
                    raise TimeoutError(
                        f"receiver idle for {self.idle_timeout}s, "
                        f"expected seq={expected}"
                    )
                try:
                    pkt = self._recv_packet(remaining)
                except socket.timeout:
                    continue
                if pkt is None:
                    continue              # corrupt or reset: ignore
                if not (pkt.flags & (DATA | FIN)):
                    continue              # not a data-side packet
                last_valid = time.monotonic()

                if pkt.seq == expected and (pkt.flags & FIN):
                    self._send_ack(pkt.seq)
                    fin_seq = pkt.seq
                elif pkt.seq == expected and (pkt.flags & DATA):
                    f.write(pkt.payload)  # in order: write exactly once
                    delivered += len(pkt.payload)
                    expected += 1
                    self._send_ack(pkt.seq)
                else:
                    # Out of order or duplicate: never write it. Re-ACK the
                    # LAST IN-ORDER packet (cumulative), not this packet's seq.
                    if pkt.seq < expected:
                        self.stats["retransmissions"] += 1
                    if expected > 0:
                        self._send_ack(expected - 1)
                    # expected == 0: nothing in order yet, ack -1 can't be sent

        elapsed = time.monotonic() - start    # BEFORE lingering

        # Linger: our FIN ACK may have been lost, so keep answering repeated
        # FINs until `linger` seconds of silence. Each repeat slides the window.
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
                self._send_ack(fin_seq)
                end = time.monotonic() + self.linger

        return {
            "packets_sent": self.stats["packets_sent"],
            "retransmissions": self.stats["retransmissions"],
            "bytes_delivered": delivered,
            "elapsed_s": elapsed,
        }