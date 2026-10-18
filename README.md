# Datagram

Datagram is a university networking project focused on reliable file transfer over UDP using swappable Automatic Repeat reQuest (ARQ) protocols. It includes a packet format with CRC32 validation, an adaptive retransmission-timeout estimator, and a seeded channel emulator for simulating network conditions. The ARQ protocol implementations and complete file-transfer workflow are still in progress.

## Packet format

Each packet consists of a 15-byte header followed by its payload. The header uses the network-byte-order `struct` format `!IIBHI`:

| Field | Size | Purpose |
| --- | ---: | --- |
| `seq` | 4 bytes | Sequence number |
| `ack` | 4 bytes | Acknowledgment number |
| `flags` | 1 byte | Packet type and control flags |
| `payload_len` | 2 bytes | Payload length in bytes |
| `checksum` | 4 bytes | CRC32 checksum used to detect corruption |

The `flags` field is a bitmask: `DATA` is `0b001`, `ACK` is `0b010`, and `FIN` is `0b100`. Flags can be combined with bitwise OR, for example, `DATA | FIN`.

To compute the checksum, the sender packs the header with its checksum field set to zero, appends the payload, and computes `zlib.crc32(header + payload)`, masked to 32 bits. The receiver reconstructs the header with the checksum field zeroed and repeats the calculation over the header and payload. A mismatch means the packet is rejected.

`Packet.unpack()` returns `None` for malformed input: a truncated header, a payload whose actual size does not match `payload_len`, or a checksum mismatch. Corruption and truncation are expected possibilities on an unreliable network, so returning `None` lets the caller discard a bad packet without handling an exception for each malformed datagram.

## Channel emulator

`Channel` sits between a protocol and a UDP socket and applies configurable effects to outgoing packet bytes:

| Parameter | Purpose |
| --- | --- |
| `loss` | Probability that a packet is dropped |
| `corrupt` | Probability that one bit is flipped |
| `dup` | Probability that a packet is delivered twice |
| `reorder` | Probability that a packet receives extra delay |
| `reorder_delay` | Extra delay for a reordered packet, in seconds |
| `delay` | Base one-way delay, in seconds |
| `jitter` | Maximum positive or negative variation around the base delay, in seconds |
| `seed` | Seed for the channel's random number generator |
| `clock` | Callable returning the current time in seconds; defaults to `time.monotonic` |

The emulator uses its own `random.Random(seed)` so its random choices are reproducible and do not consume or change the application's global random sequence. For every packet, it draws every random value in a fixed order, even if the packet is dropped or an effect is disabled. This keeps subsequent draws aligned when comparing runs that vary one setting, such as the loss probability.

Scheduled deliveries are stored in a min-heap as `(delivery_time, counter, data)` entries. The counter breaks ties so packet bytes do not need to be compared. `send()` schedules one or two copies with their respective jitter and any selected reordering delay, then calls `pump()`. `pump()` sends each queued packet whose delivery time has arrived through the socket's `sendto()` method. With zero delay, delivery can happen immediately inside `send()`. `pending()` reports the number of packets still waiting in the queue.

The clock is injectable so tests can advance fake time deterministically and check delivery timing without waiting in real time.

## How to run tests

From the repository root, run:

```bash
python3 -m pytest tests -v
```

## Project status

- **Implemented:** packet serialization, parsing, and CRC32 validation; seeded channel emulation; adaptive retransmission-timeout estimation.
- **In progress:** Stop-and-Wait, Go-Back-N, and Selective Repeat ARQ protocols. The files in `datagram/protocols/` are currently empty.

## License

No license file or license declaration is present in the repository, so the project's license is unspecified.
