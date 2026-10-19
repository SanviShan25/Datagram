# Datagram

## Project Overview

Datagram is a Python project containing an adaptive retransmission-timeout (RTO) estimator. It updates a timeout from round-trip-time (RTT) samples using a smoothed RTT (SRTT) and RTT variation (RTTVAR), and applies exponential backoff after a timeout.

The current source implements timeout estimation only. It does not send or receive datagrams or implement a complete networking protocol.

## Features

- Calculates an RTO from RTT samples using SRTT and RTTVAR.
- Supports configurable minimum and maximum RTO bounds.
- Applies exponential backoff after a timeout.
- Can use a fixed timeout that does not learn from RTT samples.
- Includes a small executable demonstration in the estimator module.

## Project Structure

```text
Datagram/
└── datagram/
    ├── __init__.py   # Empty Python package marker
    └── rto.py        # RTO estimator and executable demonstration
```

This structure reflects the project files present when this README was prepared. No dependency manifest, build configuration, or test suite is present.

## Prerequisites

- Python 3. The repository does not declare a minimum or tested Python version.
- Git, if cloning the repository.

The source imports no third-party packages.

## Installation

Clone the repository and enter its directory:

```bash
git clone https://github.com/SanviShan25/Datagram.git
cd Datagram
```

No package installation step is defined by the repository.

## Build and Run

### Build Instructions (To Be Updated)

No build system or build configuration is present. The project can be run directly with Python.

Run the included demonstration from the repository root:

```bash
python3 datagram/rto.py
```

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

## Contributors

Git commit history identifies these contributors:

- Sanvi Shan
- Shilpa Kumari
- Samridhya Mukherjee

## Future Enhancements

These are possible follow-up ideas, not features currently implemented:

- Add tests for RTT updates, clamping, fixed timeouts, and backoff.
- Document the supported Python version and add project/dependency metadata.
- Integrate the estimator with a datagram transport if a complete transport implementation is intended.
- Define how RTT samples from retransmitted packets should be handled.

## License

No license file or license declaration is present in the repository. The project's license is unspecified.
