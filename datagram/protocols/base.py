class ARQProtocol:
    """Common interface so the app can swap protocols freely."""

    def send_file(self, path: str) -> dict:
        """Send the file. Return stats: packets_sent, retransmissions,
        bytes_delivered, elapsed_s."""
        raise NotImplementedError

    def receive_file(self, path: str) -> dict:
        """Receive into path. Return the same stats keys."""
        raise NotImplementedError   