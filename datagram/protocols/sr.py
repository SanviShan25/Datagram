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
        # Case: next_seq is inside the window [base, base+N) and the file
        #       still has packets left -> we may send it
        # Case: window is full, or every packet is already sent -> wait
        return self.next_seq < self.base + self.N and self.next_seq < self.total

    def on_sent(self, seq, now):
        # Called after every send, first send or resend
        self.tracker.on_send(seq, now)

        # Every sent packet gets its OWN timer, starting from this moment
        self.deadline[seq] = now + self.est.current_rto()   # this packet's own timer
        
        # Case: seq is the next never-sent packet -> a first send, advance
        # Case: seq is an old one -> a resend, next_seq stays where it is
        if seq == self.next_seq: 
            self.next_seq += 1

    def on_ack(self, seq, now):
        # The tracker applies Karn's rule: it only takes an RTT sample if
        # this packet was never resent
        self.tracker.on_ack(seq, now)

        self.acked.add(seq)                 # remember this packet is confirmed
        self.deadline.pop(seq, None)        # stop its timer
        
        # Case: seq == base -> the window slides past it and past any
        #       packets after it that are already acked
        # Case: seq > base (there is a hole at base) -> base stays put
        #       until the hole itself is acked
        # Case: a duplicate ACK -> harmless, nothing changes
        while self.base in self.acked: 
            self.base += 1

    def expired(self, now):
        # Case: deadline has passed and no ACK came -> resend ONLY this one
        # Case: acked packets have no deadline, so they are never resent
        return [s for s, d in self.deadline.items() if d <= now]

class SRReceiver:
    """Selective Repeat receiver: pure logic, no sockets yet

    on_packet() returns (ack_seq, delivered): the seq to ACK (or None)
    and the payloads that can now go to the file, in order.
    """

    def __init__(self, window):
        self.N = window
        self.rcv_base = 0           # next seq we need to deliver
        self.buffer = {}            # seq -> payload, held until its turn

    def on_packet(self, seq, payload):
        delivered = []

        # Case 1: below the window. Already delivered, so only re-ACK
        # (the sender's earlier ACK was probably lost)
        if seq < self.rcv_base:
            return seq, delivered

        # Case 2: inside the window [rcv_base, rcv_base + N)
        if self.rcv_base <= seq < self.rcv_base + self.N:
            if seq not in self.buffer:          # ignore a duplicate copy
                self.buffer[seq] = payload      # hold it until its turn
            while self.rcv_base in self.buffer: # release everything in order
                delivered.append(self.buffer.pop(self.rcv_base))
                self.rcv_base += 1
            return seq, delivered               # ACK this packet individually

        # Case 3: beyond the window. Ignore it, send no ACK
        return None, delivered