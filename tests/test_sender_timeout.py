import socket
import time

import pytest

from datagram.channel import Channel
from datagram.protocols.stop_wait import StopAndWait

RTO = 0.1


@pytest.mark.parametrize("max_retries", [1, 3, 5])
def test_sender_gives_up_after_max_retries(tmp_path, max_retries):
    """No receiver: sender must stop after exactly max_retries transmissions."""
    src = tmp_path / "t.bin"
    src.write_bytes(b"x" * 2500)

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.bind(("127.0.0.1", 0))
        peer = ("127.0.0.1", 9)  # nothing listening
        # Channel defaults (loss=0, corrupt=0) make it a pass-through.
        sw = StopAndWait(sock, Channel(sock, peer), rto=RTO,
                         max_retries=max_retries)

        t0 = time.monotonic()
        with pytest.raises(TimeoutError) as excinfo:
            sw.send_file(str(src))
        elapsed = time.monotonic() - t0
    finally:
        sock.close()

    # It failed on the very first packet (seq 0), not later.
    assert "seq=0" in str(excinfo.value)

    # max_retries counts TOTAL transmissions: 1 first send + (n-1) repeats.
    assert sw.stats["packets_sent"] == max_retries
    assert sw.stats["retransmissions"] == max_retries - 1

    # It really waited one RTO per attempt (lower bound is deterministic),
    # and did not spin through retries instantly or hang.
    assert elapsed >= max_retries * RTO * 0.95
    assert elapsed < max_retries * RTO + 1.0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))