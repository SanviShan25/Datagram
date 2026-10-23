# tests/fakes.py
# Test double ONLY. Not a protocol: it copies the file locally and returns
# plausible stats. It lets the experiment harness and other modules be built
# against the agreed ARQProtocol interface before Stop-and-Wait exists.
import shutil
import time

from datagram.protocols.base import ARQProtocol


class FakeProtocol(ARQProtocol):
    def send_file(self, path: str) -> dict:
        start = time.monotonic()
        self._copied = path
        return {
            "packets_sent": 0,
            "retransmissions": 0,
            "bytes_delivered": 0,
            "elapsed_s": time.monotonic() - start,
        }

    def receive_file(self, path: str) -> dict:
        start = time.monotonic()
        shutil.copyfile(self._copied, path)
        return {
            "packets_sent": 0,
            "retransmissions": 0,
            "bytes_delivered": 0,
            "elapsed_s": time.monotonic() - start,
        }