# Datagram

## Project Overview

Datagram is a Python project for reliable file transfer over UDP. UDP only sends bytes to an address; it does not promise delivery, order, uniqueness or integrity. Datagram adds those promises with sequence numbers, checksums, acknowledgements, timeouts and retransmission, using three swappable ARQ (Automatic Repeat reQuest) protocols: Stop-and-Wait, Go-Back-N and Selective Repeat. A seeded channel emulator injects loss, duplication, reordering, corruption and delay, so every protocol can be tested and compared under identical conditions. Each transfer is verified by comparing SHA-256 hashes of the source and received files. 

An adaptive retransmission-timeout (RTO) estimator (Jacobson/Karels, with Karn's rule) sets the timer from measured round-trip times. Stop-and-Wait and Selective Repeat use it through `est=`; Go-Back-N currently uses a fixed timeout.

## Features

- Calculates an RTO from RTT samples using SRTT and RTTVAR.
- Supports configurable minimum and maximum RTO bounds.
- Applies exponential backoff after a timeout.
- Can use a fixed timeout that does not learn from RTT samples.
- Includes a small executable demonstration in the estimator module.
- Reliable, in-order, byte-exact file delivery over UDP using Stop-and-Wait ARQ
- Go-Back-N ARQ with a configurable sliding window, cumulative ACKs, a single timer for the oldest unACKed packet, and whole-window   retransmission on timeout. With window=1 it behaves like Stop-and-Wait.
- Receiver detects duplicates: they are re-ACKed but never written twice.
- Corrupt and truncated packets are detected by CRC32 and discarded.
- Seeded channel emulator, so lossy runs are reproducible (loss and corruption; duplication, delay and reordering are covered by tests/test_channel_v2.py).
- Uniform stats from every protocol: packets_sent, retransmissions, bytes_delivered, elapsed_s.
- Adaptive RTO (Jacobson/Karels) with Karn’s rule and an optional backoff reset.
- Selective Repeat ARQ with per-packet ACKs and timers and a receiver out-of-order buffer.

## Project Structure
```text
Datagram/
├── tests/
│   ├── test_channel.py
│   ├── test_channel_v2.py
│   ├── test_gbn.py            # Go-Back-N tests: receiver, window, loss, seeds
│   ├── test_loopback.py       # End-to-end transfers with hash check, seed sweep
│   ├── test_packet.py
│   ├── test_rto.py
│   ├── test_sender_timeout.py # Sender with no receiver: retry limit and stats
│   ├── test_split.py          # Chunking edge cases
│   ├── test_timers.py
│   ├── test_sr_sender.py       # Selective Repeat sender tests
│   ├── test_sr_receiver.py     # Selective Repeat receiver tests
│   └── test_sr_loopback.py     # Selective Repeat end-to-end transfers with hash check, seed sweep
│
└── datagram/
    ├── __init__.py   # Empty Python package marker
    ├── channel.py    # Channel emulator
    ├── packet.py     # Packet format, pack/unpack, CRC32
    ├── timers.py     # Timer helpers
    ├── protocols/
    │   ├── __init__.py
    │   ├── base.py       # ARQProtocol interface
    │   ├── gbn.py        # Go-Back-N sender and receiver
    │   ├── sr.py        # Selective Repeat sender, receiver and driver
    │   └── stop_wait.py  # Stop-and-Wait sender and receiver
    └── rto.py        # RTO estimator and executable demonstration
``` 
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

Main test file for Go-Back-N:

test_gbn.py: covers the receiver (driven by hand, with no sender), the sender with a silent receiver (window limit, whole-window resend, giving up after max_retries), clean transfers including window=1 as the Stop-and-Wait case, and transfers under loss and corruption across several seeds, including lost ACKs. Run it alone with:

```bash
python -m pytest tests/test_gbn.py -v
```
Main test files for Selective Repeat:

- test_sr_sender.py and test_sr_receiver.py: the window, per-packet deadlines, burst timeouts backing off once, and the receiver's three cases (below the window, inside it, beyond it).
- test_sr_loopback.py: real transfers over the Channel with a SHA-256 match, including one lost packet leading to exactly one retransmission, lost ACKs, a lost final ACK, window sizes 1 to 16, 20% loss both ways across seeds, and loss, duplication, corruption and reordering together.

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

Note: in Stop-and-Wait and Selective Repeat the timeout comes from `est`. With no `est` it is adaptive and starts at 0.5 s. `rto=` only sets the receiver's linger time. For a fixed timeout pass `est=RTOEstimator(fixed=0.05)`.

Go-Back-N transfer (same setup as above; only the class and the keyword-only window argument change):

```python
from datagram.protocols.gbn import GoBackN

sender = GoBackN(
    s_sock, Channel(s_sock, r_sock.getsockname(), seed=42, loss=0.2, corrupt=0.1),
    window=8, rto=0.05, max_retries=60)
receiver = GoBackN(
    r_sock, Channel(r_sock, s_sock.getsockname(), seed=43, loss=0.2, corrupt=0.1),
    window=8, rto=0.05, max_retries=60)
```

Selective Repeat transfer (same setup; `window` sets the window size):

```python
from datagram.protocols.sr import SelectiveRepeat

sender = SelectiveRepeat(
    s_sock, Channel(s_sock, r_sock.getsockname(), seed=42, loss=0.2),
    window=8, rto=0.05)
receiver = SelectiveRepeat(
    r_sock, Channel(r_sock, s_sock.getsockname(), seed=43, loss=0.2),
    window=8, rto=0.05)
```

## Adaptive RTO and Karn's Rule (`rto.py`, `timers.py`)

- `RTOEstimator` turns measured round-trip times into a retransmission timeout (RFC 6298, Jacobson/Karels). The first sample sets SRTT = R and RTTVAR = R/2. After that, RTTVAR updates first and then SRTT (alpha = 1/8, beta = 1/4). RTO = SRTT + 4 x RTTVAR, clamped between `min_rto` and `max_rto`. Each timeout doubles the RTO (exponential backoff). `RTOEstimator(fixed=x)` is a fixed-timeout baseline that never learns.
- `RTTTracker` sits between a protocol and the estimator and enforces Karn's rule: no RTT sample is taken from a retransmitted packet, because its ACK is ambiguous. A protocol calls `on_send(seq, now)` on every send and resend, `on_ack(seq, now)` when an ACK arrives, and `on_timeout(seq)` when a timer fires. If several packets time out together, pass `backoff=False` for all but the first so the RTO doubles once. `discard(seq)` forgets a packet without measuring it (for cumulative ACKs).
- Optional `reset_on_retx_ack=True`: when a retransmitted packet is finally ACKed, the RTO returns to the formula value (still no sample). This is a deliberate deviation from textbook Karn. Without it, at 20-30% loss the backed-off RTO stays high and transfers slow down sharply or stall. The experiment results will quantify this.
- Currently exposed by `SelectiveRepeat`; Stop-and-Wait and Go-Back-N will expose it with the adaptive-RTO change.

## Selective Repeat (`protocols/sr.py`)

- `SRSender`: the window is `[base, base + N)`. Every packet in flight has its own deadline. ACKs are per packet, and `base` slides past consecutive ACKed packets. On timeout only the expired packets are resent, and the RTO backs off once per burst.
- `SRReceiver`, by sequence number: below the window, re-ACK it but never deliver it again. Inside the window, ACK it, buffer it if it is new, and deliver every consecutive packet starting at `rcv_base`. Beyond the window, ignore it.
- `SelectiveRepeat(sock, channel, window=8, rto=0.5, est=None, ...)` has the same `send_file` / `receive_file` interface and stats as the other protocols. The FIN is the last packet, and the receiver lingers after it to re-ACK a lost FIN ACK.

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

Go-Back-N Design Notes : 
- Constructor. GoBackN(sock, channel, *, window=8, rto=0.5, max_retries=10, idle_timeout=5.0, linger=None). Everything after channel is keyword-only.
- Sliding window. Up to window packets are in flight. base is the oldest unACKed packet and next_seq is the next packet to send for the first time. The FIN is the last packet (seq = len(chunks)) and goes through the window like any other packet.
- Cumulative ACK. ack = N means every packet up to N arrived in order. The sender accepts only base <= ack < next_seq; an older or impossible ACK is ignored.
- Receiver accepts only in-order packets. An in-order packet is written once and ACKed. An out-of-order packet or a duplicate is never written. The receiver re-ACKs the last in-order packet (expected - 1), not the duplicate's own seq. While nothing is in order yet (expected == 0), it sends no ACK.
- One timer, for base. It starts when a packet is sent into an empty window and restarts when an ACK advances base (with packets still outstanding) and after a timeout resend. Duplicate or stale ACKs, junk and corrupt packets never touch it, so they cannot postpone a retransmission.
- Timeout means "go back". The sender resends the whole outstanding window, base up to next_seq - 1, and each resent packet counts as one retransmission.
max_retries differs from Stop-and-Wait. Here it counts consecutive timeouts without progress. It resets to 0 whenever base advances, and - TimeoutError is raised when the counter reaches max_retries, before resending.
- Stats counting rule. packets_sent counts every transmission (on the receiver, every ACK sent). Sender retransmissions is one per   resent packet. Receiver retransmissions counts duplicates (seq < expected) and repeated FINs.
- Linger, idle timeout and Windows handling work as in Stop-and-Wait. elapsed_s is measured before lingering.

Known Limitations:
- Go-Back-N uses a fixed timeout; it does not use the RTO estimator yet.
- The experiment runner is not complete yet.

## Contributors

Git commit history identifies these contributors:

- Sanvi Shan
- Shilpa Kumari
- Samridhya Mukherjee
- Akshita Singh

## Future Enhancements

- Document the supported Python version and add project/dependency metadata.
- Adaptive RTO inside Go-Back-N.
- Experiments: goodput versus loss rate, goodput versus window size, retransmissions versus reordering probability, sensitivity to RTO tuning.
- Stretch goals: SACK blocks, sliding-window flow control, connection setup and teardown, Nagle-style coalescing.

## License

No license file or license declaration is present in the repository. The project's license is unspecified.
