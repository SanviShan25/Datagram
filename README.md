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

## Contributors

Git commit history identifies these contributors:

- Sanvi Shan
- Shilpa Kumari

## Future Enhancements

These are possible follow-up ideas, not features currently implemented:

- Add tests for RTT updates, clamping, fixed timeouts, and backoff.
- Document the supported Python version and add project/dependency metadata.
- Integrate the estimator with a datagram transport if a complete transport implementation is intended.
- Define how RTT samples from retransmitted packets should be handled.

## License

No license file or license declaration is present in the repository. The project's license is unspecified.
