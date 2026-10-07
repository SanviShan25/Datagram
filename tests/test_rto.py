from datagram.rto import RTOEstimator


def close(a, b):
    # floats are inexact, so compare with a tiny tolerance
    return abs(a - b) < 1e-9


def make():
    # min_rto=0 and a big max_rto so the clamp doesn't hide the maths
    return RTOEstimator(min_rto=0.0, max_rto=10.0)


def test_initial_rto_before_any_sample():
    # before any RTT is measured, we use the configured starting timeout
    est = RTOEstimator(initial_rto=0.5)
    assert close(est.current_rto(), 0.5)

def test_timeout_before_any_sample():
    est = RTOEstimator(initial_rto=0.5, min_rto=0.0, max_rto=10.0)
    est.on_timeout()
    assert close(est.current_rto(), 1.0)

def test_first_sample():
    est = make()
    est.on_rtt_sample(0.100)
    assert close(est.srtt, 0.100)       # SRTT = R
    assert close(est.rttvar, 0.050)     # RTTVAR = R/2
    assert close(est.current_rto(), 0.300)


def test_second_sample():
    est = make()
    est.on_rtt_sample(0.100)
    est.on_rtt_sample(0.140)
    assert close(est.srtt, 0.105)
    assert close(est.rttvar, 0.0475)
    assert close(est.current_rto(), 0.295)


def test_third_sample():
    est = make()
    for r in (0.100, 0.140, 0.120):
        est.on_rtt_sample(r)
    assert close(est.srtt, 0.106875)
    assert close(est.rttvar, 0.039375)
    assert close(est.current_rto(), 0.264375)


def test_timeout_doubles_rto():
    est = make()
    est.on_rtt_sample(0.100)            # rto is now 0.300
    est.on_timeout()
    assert close(est.current_rto(), 0.600)


def test_repeated_timeouts_keep_doubling():
    est = make()
    est.on_rtt_sample(0.100)            # 0.3
    est.on_timeout()                    # 0.6
    est.on_timeout()                    # 1.2
    assert close(est.current_rto(), 1.200)


def test_sample_after_timeout_recomputes_rto():
    # a fresh good sample replaces the backed-off value with the formula
    est = make()
    est.on_rtt_sample(0.100)            # srtt 0.1, rttvar 0.05
    est.on_timeout()                    # rto 0.6
    est.on_rtt_sample(0.100)            # rttvar = 0.75*0.05 + 0.25*0 = 0.0375
    assert close(est.rttvar, 0.0375)
    assert close(est.current_rto(), 0.250)   # 0.1 + 4*0.0375


def test_min_clamp():
    # a tiny RTT would give rto 0.003, but the floor is 0.05
    est = RTOEstimator(min_rto=0.05, max_rto=10.0)
    est.on_rtt_sample(0.001)
    assert close(est.current_rto(), 0.05)


def test_max_clamp_on_sample():
    # R=0.5 gives rto 1.5, but the ceiling is 1.0
    est = RTOEstimator(min_rto=0.0, max_rto=1.0)
    est.on_rtt_sample(0.500)
    assert close(est.current_rto(), 1.0)


def test_max_clamp_on_timeout():
    # backoff must not grow past max_rto
    est = RTOEstimator(initial_rto=0.8, min_rto=0.0, max_rto=1.0)
    est.on_timeout()                    # 1.6 would exceed the cap
    assert close(est.current_rto(), 1.0)


def test_fixed_mode_never_changes():
    est = RTOEstimator(fixed=0.2)
    est.on_rtt_sample(0.500)
    est.on_timeout()
    assert close(est.current_rto(), 0.2)