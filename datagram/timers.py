from datagram.rto import RTOEstimator


class RTTTracker:
    def __init__(self, estimator):
        self.est = estimator
        self.sent_at = {}            # seq -> time it was last sent
        self.retransmitted = set()   # seqs that were resent at least once

    def on_send(self, seq, now):
        # called for the first send AND for every resend
        self.sent_at[seq] = now

    def on_timeout(self, seq):
        # timer fired: this packet is now ambiguous, and back off
        self.retransmitted.add(seq)
        self.est.on_timeout()

    def on_ack(self, seq, now):
        # a duplicate or unknown ACK has nothing to measure
        if seq not in self.sent_at:
            return

        r = now - self.sent_at[seq]              # A: RTT = ack time - send time

        # Karn's rule: a retransmitted packet's ACK is ambiguous (original or
        # resend?), so its RTT must never reach the estimator
        if seq not in self.retransmitted:        # B
            self.est.on_rtt_sample(r)

        del self.sent_at[seq]                    # C: forget this packet
        self.retransmitted.discard(seq)