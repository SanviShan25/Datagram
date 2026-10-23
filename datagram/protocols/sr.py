import socket
import time
 
from datagram.packet import Packet, DATA, ACK, FIN
from datagram.protocols.base import ARQProtocol
from datagram.protocols.stop_wait import split_file
from datagram.rto import RTOEstimator
from datagram.timers import RTTTracker
 
SLICE = 0.005   # max seconds to block on the socket, so timers and pump() stay responsive
 
 
# ====================================================================
# Part 1: the logic (pure, no sockets). This is the brain of Selective Repeat.
# ====================================================================
class SRSender:
    """Selective Repeat sender: pure logic, no sockets.

    The caller's loop asks can_send(), sends a packet, calls on_sent();
    feeds ACKs to on_ack(); and resends whatever expired() returns.
    """

    def __init__(self, total, window, tracker, est):
        self.total = total          # number of packets in the file (incl. FIN)
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
    
    def collect_timeouts(self, now):
        """Return the seqs to resend. Backs off the RTO once, not per packet."""
        due = sorted(self.expired(now))
        for i, seq in enumerate(due):
            # backoff only for the first expired packet; the rest are still
            # marked as retransmitted (Karn's rule) but don't double the RTO again
            self.tracker.on_timeout(seq, backoff=(i == 0))
        return due

class SRReceiver:
    """Selective Repeat receiver: pure logic, no sockets .

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


# ====================================================================
# Part 2: the driver. Connects the logic to a real socket and a Channel,
# with the same interface as StopAndWait (send_file / receive_file).
# ====================================================================
class SelectiveRepeat(ARQProtocol):
    """Runs SRSender / SRReceiver over a real socket and a Channel."""
 
    def __init__(self, sock, channel, window=8, rto=0.5, est=None,
                 max_retries=60, idle_timeout=5.0, linger=None):
        self.sock = sock
        self.channel = channel                  # anything with .send(bytes) and .pump()
        self.window = window
        self.est = est or RTOEstimator()        # est=RTOEstimator(fixed=x) -> fixed baseline
        self.tracker = RTTTracker(self.est)
        self.max_retries = max_retries          # total transmissions per packet
        self.idle_timeout = idle_timeout        # receiver: max silence before giving up
        # After the FIN is delivered, keep re-ACKing until this much silence
        self.linger = 10 * rto if linger is None else linger
        self._reset_stats()
 
    def _reset_stats(self):
        # Same meaning as StopAndWait. Sender: packets_sent counts every
        # transmission, retransmissions only the repeats. Receiver:
        # packets_sent counts ACKs, retransmissions counts duplicates received.
        self.stats = {"packets_sent": 0, "retransmissions": 0}
 
    # ------------------------------------------------------------ sender
    def _transmit(self, raw, is_resend):
        self.channel.send(raw)
        self.stats["packets_sent"] += 1
        if is_resend:
            self.stats["retransmissions"] += 1
 
    def send_chunks(self, chunks):
        self._reset_stats()
        start = time.monotonic()
 
        # Packet i carries chunk i; the FIN takes the next seq, empty payload
        packets = [Packet(seq=i, ack=0, flags=DATA, payload=c)
                   for i, c in enumerate(chunks)]
        packets.append(Packet(seq=len(chunks), ack=0, flags=FIN, payload=b""))
        raw = [p.pack() for p in packets]
        total = len(raw)
 
        snd = SRSender(total, self.window, self.tracker, self.est)
        tries = {}                                   # seq -> transmissions so far
 
        while snd.base < total:                      # done when the FIN is acked
            # 1. Fill the window with never-sent packets
            while snd.can_send():
                seq = snd.next_seq
                self._transmit(raw[seq], is_resend=False)
                tries[seq] = 1
                snd.on_sent(seq, time.monotonic())
 
            # 2. Deliver delayed packets, then wait briefly for one ACK
            self.channel.pump()
            self.sock.settimeout(SLICE)
            try:
                data, _addr = self.sock.recvfrom(2048)
            except socket.timeout:
                data = None
            except ConnectionResetError:             # Windows: peer port not open yet
                data = None
            if data is not None:
                reply = Packet.unpack(data)          # None = corrupt, ignore
                if (reply is not None and reply.flags & ACK
                        and 0 <= reply.ack < total):
                    # ACK carries ack=seq of the packet it confirms
                    snd.on_ack(reply.ack, time.monotonic())
 
            # 3. Resend ONLY the packets whose own timer expired
            now = time.monotonic()
            for seq in snd.collect_timeouts(now):
                tries[seq] += 1
                if tries[seq] > self.max_retries:
                    raise TimeoutError(
                        f"no ACK for seq={seq} after {self.max_retries} transmissions")
                self._transmit(raw[seq], is_resend=True)
                snd.on_sent(seq, time.monotonic())   # restarts its timer
 
        return {
            "packets_sent": self.stats["packets_sent"],
            "retransmissions": self.stats["retransmissions"],
            "bytes_delivered": sum(len(c) for c in chunks),
            "elapsed_s": time.monotonic() - start,
        }
 
    def send_file(self, path):
        return self.send_chunks(split_file(path))
 
    # ---------------------------------------------------------- receiver
    def _send_ack(self, seq):
        # ACK carries ack=seq of the packet being acknowledged
        self.channel.send(Packet(seq=0, ack=seq, flags=ACK).pack())
        self.stats["packets_sent"] += 1
 
    def _recv_packet(self, timeout):
        """Return a valid Packet or None (junk / reset / nothing yet)."""
        self.channel.pump()                          # deliver any delayed ACKs now due
        self.sock.settimeout(min(timeout, SLICE))
        try:
            data, _addr = self.sock.recvfrom(2048)
        except (socket.timeout, ConnectionResetError):
            return None
        return Packet.unpack(data)
 
    def receive_chunks(self, write):
        """Call write(payload) for each payload, in order."""
        self._reset_stats()
        start = time.monotonic()
        rcv = SRReceiver(self.window)
        bytes_delivered = 0
        fin_seq = None
        last_valid = time.monotonic()
 
        def handle(pkt):
            nonlocal bytes_delivered, fin_seq
            if pkt.flags & FIN:
                fin_seq = pkt.seq
            elif not (pkt.flags & DATA):
                return
            # a copy we already have (delivered or buffered) is a duplicate
            if pkt.seq < rcv.rcv_base or pkt.seq in rcv.buffer:
                self.stats["retransmissions"] += 1
            ack, delivered = rcv.on_packet(pkt.seq, pkt.payload)
            for payload in delivered:
                write(payload)
                bytes_delivered += len(payload)
            if ack is not None:
                self._send_ack(ack)                  # ACK each packet individually
 
        # Phase 1: until the FIN and everything before it is delivered
        while fin_seq is None or rcv.rcv_base <= fin_seq:
            if time.monotonic() - last_valid > self.idle_timeout:
                raise TimeoutError(
                    f"receiver idle for {self.idle_timeout}s, expected seq={rcv.rcv_base}")
            pkt = self._recv_packet(self.idle_timeout)
            if pkt is None:
                continue
            last_valid = time.monotonic()
            handle(pkt)
 
        elapsed = time.monotonic() - start           # measured BEFORE lingering
 
        # Phase 2: our last ACKs may have been lost, so keep answering resends
        # until `linger` seconds of silence. Each valid packet restarts it.
        end = time.monotonic() + self.linger
        while time.monotonic() < end:
            pkt = self._recv_packet(end - time.monotonic())
            if pkt is not None:
                handle(pkt)
                end = time.monotonic() + self.linger
 
        return {
            "packets_sent": self.stats["packets_sent"],
            "retransmissions": self.stats["retransmissions"],
            "bytes_delivered": bytes_delivered,
            "elapsed_s": elapsed,
        }
 
    def receive_file(self, path):
        with open(path, "wb") as f:
            return self.receive_chunks(f.write)