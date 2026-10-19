import hashlib
import os
import random
import socket
import threading

from datagram.protocols.stop_wait import StopAndWait


class PassThrough:
    """Test-only: sends straight to the peer, no impairments."""
    def __init__(self, sock, peer):
        self.sock, self.peer = sock, peer

    def send(self, data):
        self.sock.sendto(data, self.peer)


class LossyChannel(PassThrough):
    """Test-only: drops each outgoing packet with probability `loss`."""
    def __init__(self, sock, peer, loss, seed):
        super().__init__(sock, peer)
        self.loss = loss
        self.rng = random.Random(seed)

    def send(self, data):
        if self.rng.random() >= self.loss:
            super().send(data)


def sha(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def run(size, loss, seed):
    src, dst = "src.bin", "dst.bin"
    with open(src, "wb") as f:
        f.write(os.urandom(size))

    s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    r_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s_sock.bind(("127.0.0.1", 0))
    r_sock.bind(("127.0.0.1", 0))
    s_addr, r_addr = s_sock.getsockname(), r_sock.getsockname()

    sender = StopAndWait(s_sock, LossyChannel(s_sock, r_addr, loss, seed),
                         rto=0.05, max_retries=60)
    receiver = StopAndWait(r_sock, LossyChannel(r_sock, s_addr, loss, seed + 1),
                           rto=0.05, max_retries=60, idle_timeout=5.0)

    out = {}
    t = threading.Thread(target=lambda: out.update(receiver.receive_file(dst)))
    t.start()
    stats = sender.send_file(src)
    t.join()
    s_sock.close()
    r_sock.close()

    ok = sha(src) == sha(dst)
    print(f"size={size:6d} loss={loss:.2f} hash_ok={ok} "
          f"sent={stats['packets_sent']} retx={stats['retransmissions']} "
          f"recv_dups={out['retransmissions']}")
    assert ok, "HASH MISMATCH"
    assert stats["bytes_delivered"] == size


for size in (0, 1, 2048, 2500, 50000):
    for loss in (0.0, 0.2, 0.4):
        run(size, loss, seed=42)
print("all passed")