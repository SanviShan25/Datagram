import socket
import time
from datagram.protocols.stop_wait import StopAndWait, RawChannel

with open("t.bin", "wb") as f:
    f.write(b"x" * 2500)

sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
sock.bind(("127.0.0.1", 0))
peer = ("127.0.0.1", 9)  # nothing listening

sw = StopAndWait(sock, RawChannel(sock, peer), rto=0.1, max_retries=3)
t = time.monotonic()
try:
    sw.send_file("t.bin")
except TimeoutError as e:
    print("raised:", e)
print("elapsed: %.2f s" % (time.monotonic() - t))
print(sw.stats)