# Datagram

## Project Overview

Datagram is a Python project containing an adaptive retransmission-timeout (RTO) estimator. It updates a timeout from round-trip-time (RTT) samples using a smoothed RTT (SRTT) and RTT variation (RTTVAR), and applies exponential backoff after a timeout.

The project also contains a file-transfer application over UDP with swappable ARQ (Automatic Repeat reQuest) protocols. A shared packet format with a CRC32 checksum, a seeded channel emulator, and a Stop-and-Wait protocol (sender and receiver) are implemented. Go-Back-N and Selective Repeat are in progress. Transfers are verified by comparing SHA-256 hashes of the source and received files. It is built for the Computer Networks course (project P3, Reliable Data Transfer over UDP)

The RTO estimator is currently standalone: Stop-and-Wait uses a fixed timeout and is not yet connected to it.

## Features

- Calculates an RTO from RTT samples using SRTT and RTTVAR.
- Supports configurable minimum and maximum RTO bounds.
- Applies exponential backoff after a timeout.
- Can use a fixed timeout that does not learn from RTT samples.
- Includes a small executable demonstration in the estimator module.
-Reliable, in-order, byte-exact file delivery over UDP using Stop-and-Wait ARQ
-Receiver detects duplicates: they are re-ACKed but never written twice.
-Corrupt and truncated packets are detected by CRC32 and discarded.
-Seeded channel emulator, so lossy runs are reproducible (loss and corruption; duplication, delay and reordering are covered by tests/test_channel_v2.py).
-Uniform stats from every protocol: packets_sent, retransmissions, bytes_delivered, elapsed_s.

## Project Structure

```text
Datagram/
└── datagram/
    ├── __init__.py   # Empty Python package marker
    └── rto.py        # RTO estimator and executable demonstration
```
Datagram/
├── tests/
│   ├── test_channel.py
│   ├── test_channel_v2.py
│   ├── test_loopback.py       # End-to-end transfers with hash check, seed sweep
│   ├── test_packet.py
│   ├── test_rto.py
│   ├── test_sender_timeout.py # Sender with no receiver: retry limit and stats
│   ├── test_split.py          # Chunking edge cases
│   └── test_timers.py
└── datagram/
    ├── __init__.py   # Empty Python package marker
    ├── channel.py    # Channel emulator
    ├── packet.py     # Packet format, pack/unpack, CRC32
    ├── timers.py     # Timer helpers
    ├── protocols/
    │   ├── __init__.py
    │   ├── base.py       # ARQProtocol interface
    │   └── stop_wait.py  # Stop-and-Wait sender and receiver
    └── rto.py        # RTO estimator and executable demonstration

This structure reflects the project files present when this README was updated. No dependency manifest or build configuration is present. Tests are in tests/ and use pytest.

## Prerequisites

- Python 3. The repository does not declare a minimum or tested Python version.
- Git, if cloning the repository.
-pytest, only to run the tests.

The source imports no third-party packages.

## Installation

Clone the repository and enter its directory:

```bash
git clone https://github.com/SanviShan25/Datagram.git
cd Datagram
```

No package installation step is defined by the repository.

To run the tests, install pytest:

```bash
pip install pytest
```

## Build and Run

### Build Instructions (To Be Updated)

No build system or build configuration is present. The project can be run directly with Python.

Run the included demonstration from the repository root:

```bash
python3 datagram/rto.py
```
Run the Tests:

Run from the repository root. Use python -m pytest (not bare pytest) so the datagram package is importable:

```bash
python -m pytest tests -v
```
Main test files for Stop-and-Wait:

-test_split.py: chunking of an empty file (no chunks), a 2500-byte file (1024 + 1024 + 452) and a 2048-byte file (two chunks, no stray empty chunk).
-test_sender_timeout.py: with no receiver, the sender stops after exactly max_retries transmissions and raises TimeoutError.
-test_loopback.py: real sender and receiver over the Channel, across file sizes 0, 1, 2048, 2500 and 50000 bytes and several loss/corruption settings, plus a 20-seed sweep. Each transfer is checked by SHA-256 hash and byte counts, and the test also asserts that the impairments fired and caused retransmissions. The full run takes about a minute because the receiver lingers briefly after each transfer.

## Usage Example

Run the built-in demonstration:

```bash
python3 datagram/rto.py
```

The demonstration submits three RTT samples to `RTOEstimator`, prints the resulting estimator state, then applies and prints a timeout backoff.

The estimator can also be imported from the package:

```python
from datagram.rto import RTOEstimator

estimator = RTOEstimator()
estimator.on_rtt_sample(0.100)

print(estimator.current_rto())
estimator.on_timeout()
print(estimator.current_rto())
```

Times are represented as numeric values; the source's demonstration uses seconds.

Stop-and-Wait transfer: 

```python
import socket
import threading
from datagram.channel import Channel
from datagram.protocols.stop_wait import StopAndWait

s_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
r_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
s_sock.bind(("127.0.0.1", 0))
r_sock.bind(("127.0.0.1", 0))

sender = StopAndWait(
    s_sock, Channel(s_sock, r_sock.getsockname(), seed=42, loss=0.2, corrupt=0.1),
    rto=0.05, max_retries=60)
receiver = StopAndWait(
    r_sock, Channel(r_sock, s_sock.getsockname(), seed=43, loss=0.2, corrupt=0.1),
    rto=0.05, max_retries=60)

t = threading.Thread(target=receiver.receive_file, args=("dst.bin",))
t.start()
stats = sender.send_file("src.bin")   # packets_sent, retransmissions, ...
t.join()
```

## Packet Format and ACK Semantics

*Status: proposed on 2026-10-12, pending confirmation from all four members. Remove this line once everyone has agreed.*

All three ARQ protocols (Stop-and-Wait, Go-Back-N, Selective Repeat) share one packet format and one set of conventions. The format is implemented in `datagram/packet.py`.

### Header (15 bytes, network byte order)

| Field | Type | Meaning |
|---|---|---|
| `seq` | uint32 | Index of this packet |
| `ack` | uint32 | Which packet is being acknowledged |
| `flags` | uint8 | bit0 = `DATA`, bit1 = `ACK`, bit2 = `FIN` |
| `payload_len` | uint16 | Number of data bytes after the header |
| `checksum` | uint32 | CRC32 over the header (checksum field zeroed) and the payload |

### Conventions

1. **Sequence numbers** count packets, not bytes, and start at 0.
2. **ACK meaning:**
   - Stop-and-Wait and Selective Repeat: `ack = N` means packet N specifically arrived.
   - Go-Back-N: `ack = N` means every packet up to and including N arrived in order (cumulative).
3. **End of file** is signalled by a final packet with the `FIN` flag and an empty payload. This also covers an empty file (zero `DATA` packets, then `FIN`).
4. **Payload size** is 1024 bytes per packet.
5. **Sending** goes through `channel.send(raw_bytes)`, including ACKs, because ACKs can be lost too. Receiving uses `sock.recvfrom(2048)`.
6. **Corrupt packets:** `Packet.unpack` returns `None` for a corrupt, truncated or padded packet. Receivers and senders ignore these.
7. **Stats:** every protocol's `send_file` and `receive_file` returns a dict with the keys `packets_sent`, `retransmissions`, `bytes_delivered` and `elapsed_s`. The experiment harness reads these by name.

Stop-and-Wait Design Notes: 
-One timer deadline per attempt. The deadline is computed once when a packet is sent, and each recvfrom only gets the time remaining. Stale ACKs and junk packets therefore cannot postpone a retransmission.
-max_retries counts total transmissions. max_retries=3 means 1 first send plus 2 retransmissions, then TimeoutError.
-Stats counting rule (sender). packets_sent counts every transmission, including retransmissions. retransmissions counts only the repeats, so first sends = packets_sent - retransmissions.
-Stats counting rule (receiver). packets_sent counts ACKs sent. retransmissions counts duplicate packets received and re-ACKed.
-Duplicate DATA. A packet with seq < expected is a duplicate caused by a lost ACK. The receiver re-ACKs it and does not write it again.
-FIN linger. After ACKing the FIN, the receiver stays up and re-ACKs repeated FINs until 10 * rto of silence has passed (the window restarts on each repeated FIN). Without this, a lost FIN ACK would leave the sender retransmitting into a closed receiver. No finite linger removes the problem entirely (the Two Generals problem); in the worst case the sender fails with TimeoutError instead of hanging or corrupting data.
-Idle timeout. The receiver raises TimeoutError if nothing valid arrives for idle_timeout seconds.
-Windows. ConnectionResetError (WinError 10054) from recvfrom is treated as "no ACK yet".
-Goodput. bytes_delivered / elapsed_s. The receiver's elapsed_s is measured up to the first ACK of the FIN, so lingering does not distort it.

Known Limitations:
-Stop-and-Wait uses a fixed RTO and does not yet use RTOEstimator.
-Go-Back-N, Selective Repeat and the experiment runner are not complete yet.

## Contributors

Git commit history identifies these contributors:

- Sanvi Shan
- Shilpa Kumari
- Samridhya Mukherjee

## Future Enhancements

These are possible follow-up ideas, not features currently implemented:

- Document the supported Python version and add project/dependency metadata.
- Document the supported Python version and add project/dependency metadata.
- Integrate the estimator with the ARQ protocols, starting with Stop-and-Wait.
- Define how RTT samples from retransmitted packets should be handled.
-Implement Go-Back-N and Selective Repeat.
-Experiments: goodput versus loss rate, goodput versus window size, retransmissions versus reordering probability, sensitivity to RTO tuning.
-Stretch goals: SACK blocks, sliding-window flow control, connection setup and teardown, Nagle-style coalescing.

## License

No license file or license declaration is present in the repository. The project's license is unspecified.
