from datagram.rto import RTOEstimator
from datagram.timers import RTTTracker
from datagram.protocols.sr import SRSender


def make(total=6, window=4):
    est = RTOEstimator(initial_rto=0.5, min_rto=0.0, max_rto=10.0)
    return SRSender(total, window, RTTTracker(est), est)


def fill_window(s, now=0.0):
    while s.can_send():
        s.on_sent(s.next_seq, now)


def test_window_limits_sending():
    s = make()
    fill_window(s)
    assert s.next_seq == 4            # sent 0..3, window is full
    assert not s.can_send()


def test_ack_slides_window_and_allows_new_send():
    s = make()
    fill_window(s)
    s.on_ack(0, 0.1)
    assert s.base == 1
    assert s.can_send()               # seq 4 now fits in [1, 5)


def test_gap_keeps_base_until_hole_is_acked():
    s = make()
    fill_window(s)
    s.on_ack(0, 0.1)
    s.on_ack(2, 0.1)
    s.on_ack(3, 0.1)
    assert s.base == 1                # packet 1 still missing
    s.on_ack(1, 0.2)
    assert s.base == 4                # slides past 1, 2, 3


def test_expired_lists_only_overdue_unacked_packets():
    s = make()
    fill_window(s)                    # deadlines at 0.5
    s.on_ack(0, 0.1)
    assert s.expired(0.4) == []
    assert sorted(s.expired(0.5)) == [1, 2, 3]