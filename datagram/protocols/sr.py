class SRSender:
    """Selective Repeat sender: pure logic, no sockets yet.

    The caller's loop asks can_send(), sends a packet, calls on_sent();
    feeds ACKs to on_ack(); and resends whatever expired() returns.
    """

    def __init__(self, total, window, tracker, est):
        self.total = total          # number of packets in the file
        self.N = window             # window size
        self.base = 0               # oldest unacked seq
        self.next_seq = 0           # next never-sent seq
        self.acked = set()          # seqs the receiver confirmed
        self.deadline = {}          # seq -> time its timer expires
        self.tracker = tracker      # Karn's rule + RTT measuring
        self.est = est              # gives the current RTO

    def can_send(self):
        # Room in the window [base, base+N) and still packets left to send
        return self.next_seq < self.base + self.N and self.next_seq < self.total

    def on_sent(self, seq, now):
        # Called after every send, first send or resend
        self.tracker.on_send(seq, now)
        self.deadline[seq] = now + self.est.current_rto()   # this packet's own timer
        if seq == self.next_seq:    # a first send, not a resend
            self.next_seq += 1

    def on_ack(self, seq, now):
        self.tracker.on_ack(seq, now)       # Karn's rule happens in here
        self.acked.add(seq)                 # remember this packet is confirmed
        self.deadline.pop(seq, None)        # stop its timer
        while self.base in self.acked:      # slide past consecutive acked packets
            self.base += 1

    def expired(self, now):
        # Seqs whose timer has run out: resend only these
        return [s for s, d in self.deadline.items() if d <= now]