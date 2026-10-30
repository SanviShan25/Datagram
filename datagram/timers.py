from datagram.rto import RTOEstimator


class RTTTracker:
    def __init__(self, estimator, reset_on_retx_ack=False):
        self.est = estimator
        self.reset_on_retx_ack = reset_on_retx_ack   # deviation from textbook Karn
        self.sent_at = {}            # seq -> time it was last sent
        self.retransmitted = set()   # seqs that were resent at least once

    def on_send(self, seq, now):
        # called for the first send AND for every resend
        self.sent_at[seq] = now

    def on_timeout(self, seq, backoff=True):
        # timer fired: this packet is now ambiguous(Karn's rule), and back off
        self.retransmitted.add(seq)

        # SR can expire several packets at once; the caller backs off
        # only once per sweep by passing backoff=False for the rest
        if backoff:
            self.est.on_timeout()

    def discard(self, seq):
           # A cumulative ACK covered this packet, but its own ACK was never seen,
           # so a sample taken now would include the wait for a later ACK.
           # Forget it without measuring.
           self.sent_at.pop(seq, None)
           self.retransmitted.discard(seq)

    def on_ack(self, seq, now):
        # a duplicate or unknown ACK has nothing to measure
        if seq not in self.sent_at:
            return

        r = now - self.sent_at[seq]              # A: RTT = ack time - send time

        # Karn's rule: a retransmitted packet's ACK is ambiguous (original or
        # resend?), so its RTT must never reach the estimator
        if seq not in self.retransmitted:        # B
            self.est.on_rtt_sample(r)            # clean packet: measure as usual
        elif self.reset_on_retx_ack:
            # Still no sample (ambiguous), but clear the backoff so one bad
            # patch doesn't leave the RTO stuck at the cap
            self.est.reset_backoff()
        del self.sent_at[seq]                    # C: forget this packet
        self.retransmitted.discard(seq)