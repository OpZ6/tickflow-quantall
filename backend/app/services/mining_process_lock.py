from __future__ import annotations

import os
import time
from pathlib import Path
from typing import BinaryIO


class MiningProcessLockError(RuntimeError):
    """Another application process owns mining for this data directory."""


class MiningProcessLock:
    def __init__(self, data_dir: Path) -> None:
        self._path = Path(data_dir) / ".mining_process.lock"
        self._stream: BinaryIO | None = None

    def acquire(self) -> None:
        if self._stream is not None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(self._path, os.O_RDWR | os.O_CREAT, 0o600)
        stream = os.fdopen(descriptor, "r+b")
        try:
            stream.seek(0, os.SEEK_END)
            if stream.tell() == 0:
                stream.write(b"0")
                stream.flush()
            os.set_inheritable(stream.fileno(), False)
            _try_lock_file(stream)
            _write_owner_record(stream)
        except BaseException:
            stream.close()
            raise
        self._stream = stream

    def release(self) -> None:
        stream = self._stream
        if stream is None:
            return
        self._stream = None
        try:
            _clear_owner_record(stream)
        finally:
            try:
                _unlock_file(stream)
            finally:
                stream.close()


def _write_owner_record(stream: BinaryIO) -> None:
    record = f"\npid={os.getpid()}\nacquired_at={time.time():.6f}\n".encode("ascii")
    stream.seek(1)
    stream.write(record)
    stream.truncate()
    stream.flush()


def _clear_owner_record(stream: BinaryIO) -> None:
    stream.seek(1)
    stream.truncate()
    stream.flush()


def _try_lock_file(stream: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        last_error: OSError | None = None
        # uvicorn --reload can briefly overlap the old and new worker during
        # startup. Give the old process a short window to release its lock.
        for _ in range(10):
            try:
                stream.seek(0)
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError as exc:
                last_error = exc
                time.sleep(0.1)
        raise MiningProcessLockError(
            "another application process already owns mining for this data directory"
        ) from last_error

    import fcntl

    try:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        raise MiningProcessLockError(
            "another application process already owns mining for this data directory"
        ) from exc


def _unlock_file(stream: BinaryIO) -> None:
    if os.name == "nt":
        import msvcrt

        stream.seek(0)
        msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
