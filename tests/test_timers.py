from datagram.rto import RTOEstimator
from datagram.timers import RTTTracker


def close(a, b):
    return abs(a - b) < 1e-9


def make():
    est = RTOEstimator(min_rto=0.0, max_rto=10.0)
    return est, RTTTracker(est)


def test_clean_ack_feeds_estimator():
    est, t = make()
    t.on_send(1, 0.0)
    t.on_ack(1, 0.1)
    assert close(est.srtt, 0.1)
    assert close(est.current_rto(), 0.3)


def test_retransmitted_ack_is_ignored():
    est, t = make()
    t.on_send(1, 0.0)
    t.on_ack(1, 0.1)             # srtt 0.1, rto 0.3
    t.on_send(2, 0.2)
    t.on_timeout(2)              # rto doubles to 0.6, packet 2 is now ambiguous
    t.on_send(2, 0.5)            # the resend
    t.on_ack(2, 0.6)             # ambiguous: must NOT change srtt
    assert close(est.srtt, 0.1)
    assert close(est.current_rto(), 0.6)    # backoff stays


def test_next_clean_ack_resumes_estimation():
    est, t = make()
    t.on_send(1, 0.0)
    t.on_ack(1, 0.1)
    t.on_send(2, 0.2)
    t.on_timeout(2)
    t.on_send(2, 0.5)
    t.on_ack(2, 0.6)
    t.on_send(3, 1.0)
    t.on_ack(3, 1.1)             # clean sample brings the formula back
    assert close(est.rttvar, 0.0375)
    assert close(est.current_rto(), 0.25)


def test_unknown_ack_is_ignored():
    est, t = make()
    t.on_ack(99, 1.0)
    assert est.srtt is None


def test_state_cleared_after_ack():
    est, t = make()
    t.on_send(1, 0.0)
    t.on_timeout(1)
    t.on_ack(1, 0.5)
    assert 1 not in t.sent_at
    assert 1 not in t.retransmitted