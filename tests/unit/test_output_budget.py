import os
import threading

from app.sandbox.output import CappedOutput


def test_large_output_is_drained_with_fixed_retention():
    with CappedOutput(limit=1024) as capture:

        def producer():
            for _ in range(128):
                os.write(capture.fileno(), b"x" * 8192)

        thread = threading.Thread(target=producer)
        thread.start()
        thread.join(timeout=5)
        assert not thread.is_alive(), "Discarded output must not block the producer"
        data = capture.finish()
        assert data == b"x" * 1024
        assert capture.total_bytes == 1024 * 1024
        assert capture.truncated


def test_small_output_is_complete_and_finish_is_idempotent():
    with CappedOutput(limit=1024) as capture:
        os.write(capture.fileno(), "中文日志".encode("utf-8"))
        assert capture.finish().decode("utf-8") == "中文日志"
        assert capture.finish().decode("utf-8") == "中文日志"
        assert not capture.truncated
