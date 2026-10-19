from datagram.protocols.stop_wait import split_file
for n in (0, 2500, 2048):
    open("t.bin", "wb").write(b"x" * n)
    print(n, [len(c) for c in split_file("t.bin")])