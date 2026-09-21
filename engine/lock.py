from __future__ import annotations

import os
import sys
from pathlib import Path

try:
    import fcntl
except ImportError:
    fcntl = None
try:
    import msvcrt
except ImportError:
    msvcrt = None


class InstanceLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fh = None

    def acquire(self, hold: bool = False) -> bool:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self._fh = open(self.path, "a+b")
            self._fh.seek(0, os.SEEK_END)
            if self._fh.tell() == 0:
                self._fh.write(b"0")
                self._fh.flush()
            if fcntl is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            elif msvcrt is not None:
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                self.release()
                return False
        except OSError:
            self.release()
            return False
        if hold:
            self._fh.seek(0)
            self._fh.write(str(os.getpid()).encode() + b"\n")
            self._fh.flush()
        else:
            self.release()
        return True

    def release(self) -> None:
        if self._fh is None:
            return
        try:
            if fcntl is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
            elif msvcrt is not None:
                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
        try:
            self._fh.close()
        except OSError:
            pass
        self._fh = None