from datagram.protocols.sr import SRReceiver


def test_in_order_delivers_immediately():
    r = SRReceiver(window=4)
    ack, out = r.on_packet(0, b"a")
    assert ack == 0 and out == [b"a"]
    assert r.rcv_base == 1


def test_out_of_order_is_buffered_then_released():
    r = SRReceiver(window=4)
    r.on_packet(0, b"a")
    ack, out = r.on_packet(2, b"c")
    assert ack == 2 and out == []          # ACKed, but held back
    ack, out = r.on_packet(3, b"d")
    assert ack == 3 and out == []
    assert r.rcv_base == 1                 # stuck at the hole
    ack, out = r.on_packet(1, b"b")        # the hole fills
    assert ack == 1 and out == [b"b", b"c", b"d"]
    assert r.rcv_base == 4


def test_duplicate_below_window_is_reacked_not_redelivered():
    r = SRReceiver(window=4)
    r.on_packet(0, b"a")
    ack, out = r.on_packet(0, b"a")        # the sender's ACK was lost
    assert ack == 0 and out == []


def test_beyond_window_is_ignored():
    r = SRReceiver(window=4)
    ack, out = r.on_packet(9, b"z")
    assert ack is None and out == []