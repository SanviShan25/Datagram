import pytest

from datagram.protocols.stop_wait import split_file


@pytest.mark.parametrize("size, expected", [
    (0, []),                       # empty file -> no chunks
    (1, [1]),
    (1024, [1024]),                # exactly one chunk
    (1025, [1024, 1]),
    (2048, [1024, 1024]),          # exact multiple: no stray empty chunk
    (2500, [1024, 1024, 452]),     # uneven last chunk
])
def test_chunk_sizes(tmp_path, size, expected):
    path = tmp_path / "t.bin"
    path.write_bytes(b"x" * size)
    chunks = split_file(str(path))
    assert [len(c) for c in chunks] == expected


def test_chunks_reassemble_to_original(tmp_path):
    # Non-uniform content, so a reordered or dropped byte would be noticed.
    data = bytes(range(256)) * 10 + b"tail"
    path = tmp_path / "t.bin"
    path.write_bytes(data)
    assert b"".join(split_file(str(path))) == data


def test_custom_chunk_size(tmp_path):
    path = tmp_path / "t.bin"
    path.write_bytes(b"x" * 10)
    assert [len(c) for c in split_file(str(path), chunk_size=4)] == [4, 4, 2]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))