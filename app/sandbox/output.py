"""Drain child output continuously while retaining only a fixed byte budget."""

import os
import threading
from types import TracebackType


class CappedOutput:
    def __init__(self, limit: int = 20000, *, tail_limit: int = 0):
        if limit < 1:
            raise ValueError("Output budget must be positive")
        self.tail_limit = tail_limit
        self.tail = bytearray()
        self.limit = limit
        self.total_bytes = 0
        self._buffer = bytearray()
        self._read_fd, write_fd = os.pipe()
        self._writer = os.fdopen(write_fd, "wb", buffering=0)
        self._thread = threading.Thread(target=self._drain, daemon=True)
        self._thread.start()

    def _drain(self) -> None:
        try:
            while chunk := os.read(self._read_fd, 8192):
                self.total_bytes += len(chunk)
                if self.tail_limit:
                    self.tail.extend(chunk)
                    del self.tail[:-self.tail_limit]
                remaining = self.limit - len(self._buffer)
                if remaining > 0:
                    self._buffer.extend(chunk[:remaining])
        finally:
            os.close(self._read_fd)

    def fileno(self) -> int:
        return self._writer.fileno()

    @property
    def truncated(self) -> bool:
        return self.total_bytes > self.limit

    def finish(self) -> bytes:
        self._writer.close()
        self._thread.join(timeout=5)
        if self._thread.is_alive():
            raise OSError("Child output pipe did not close")
        return bytes(self._buffer)

    def __enter__(self) -> "CappedOutput":
        return self

    def __exit__(
        self, exc_type: type | None, exc: BaseException | None, traceback: TracebackType | None
    ) -> None:
        self.finish()
