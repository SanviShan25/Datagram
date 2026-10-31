import hashlib
import inspect
import socket
import threading

import pytest

from datagram.channel import Channel
from datagram.rto import RTOEstimator
from datagram.protocols.gbn import GoBackN
from datagram.protocols.sr import SelectiveRepeat
from datagram.protocols.stop_wait import StopAndWait

RTO = 0.05          
LINGER = 0.3
RETRIES = 60        
FACTORIES = {
    "stop_and_wait": lambda s, ch: StopAndWait(
        s, ch, rto=RTO, max_retries=RETRIES, linger=LINGER,
        est=RTOEstimator(fixed=RTO)),
    "go_back_n": lambda s, ch: GoBackN(
        s, ch, window=8, rto=RTO, max_retries=RETRIES, linger=LINGER),
    "selective_repeat": lambda s, ch: SelectiveRepeat(
        s, ch, window=8, rto=RTO, max_retries=RETRIES, linger=LINGER,
        est=RTOEstimator(fixed=RTO)),
}

CONDITIONS = {
    "clean": {},
    "loss20": {"loss": 0.2},
    "loss_dup_corrupt": {"loss": 0.2, "dup": 0.1, "corrupt": 0.1},  # T10 case
    "reorder_delay": {"reorder": 0.2, "reorder_delay": 0.05, "delay": 0.01, "jitter": 0.005},
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def transfer(tmp_path, make, data, seed, **chan):
    src, dst = tmp_path / "src.bin", tmp_path / "dst.bin"
    src.write_bytes(data)
    s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    r_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s_sock.bind(("127.0.0.1", 0))
        r_sock.bind(("127.0.0.1", 0))
        s_ch = Channel(s_sock, r_sock.getsockname(), seed=seed, **chan)
        r_ch = Channel(r_sock, s_sock.getsockname(), seed=seed + 1000, **chan)
        sender, receiver = make(s_sock, s_ch), make(r_sock, r_ch)

        errors = []

        def rx():
            try:
                receiver.receive_file(str(dst))
            except Exception as e:
                errors.append(e)

        t = threading.Thread(target=rx)
        t.start()
        sender.send_file(str(src))
        t.join(timeout=30)
        assert not t.is_alive(), "receiver did not finish"
        assert not errors, f"receiver failed: {errors[0]!r}"
    finally:
        s_sock.close()
        r_sock.close()
    return src, dst


@pytest.mark.parametrize("size", [0, 1, 1023, 1024, 1025, 5000])
@pytest.mark.parametrize("seed", [1, 2])
@pytest.mark.parametrize("cond", CONDITIONS.keys())
@pytest.mark.parametrize("proto", FACTORIES.keys())
def test_file_arrives_intact(tmp_path, proto, cond, seed, size):
    data = bytes((i * 7) % 251 for i in range(size))
    src, dst = transfer(tmp_path, FACTORIES[proto], data, seed, **CONDITIONS[cond])
    assert sha(src) == sha(dst)


# Adaptive RTO (default estimator, no fixed RTO) on a clean network.
# Go-Back-N is skipped until it exposes the est argument. Adaptive RTO under
# heavy loss is measured by the experiments, not asserted here.
@pytest.mark.parametrize("size", [0, 1025, 5000])
@pytest.mark.parametrize("seed", [1, 2])
@pytest.mark.parametrize("proto", ["stop_and_wait", "go_back_n", "selective_repeat"])
def test_adaptive_rto_clean_file_arrives_intact(tmp_path, proto, seed, size):
    cls = {"stop_and_wait": StopAndWait, "go_back_n": GoBackN,
           "selective_repeat": SelectiveRepeat}[proto]
    params = inspect.signature(cls.__init__).parameters
    if "est" not in params:
        pytest.skip(f"{proto} does not expose adaptive RTO yet (fixed timeout)")
    kw = {"rto": RTO, "max_retries": RETRIES, "linger": LINGER}
    if "window" in params:
        kw["window"] = 8
    data = bytes((i * 7) % 251 for i in range(size))
    src, dst = transfer(tmp_path, lambda s, ch: cls(s, ch, **kw), data, seed)
    assert sha(src) == sha(dst)
