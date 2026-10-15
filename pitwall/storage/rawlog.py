"""Raw packet files: every recorded datagram with its receive time.

One gzip file per session. Decompressed, the file is::

    MAGIC (8 bytes, b"PWRAW002"; b"PWRAW001" for files from older versions)
    record*  where record = <recv_time: f64 LE> <length: u16 LE> <payload: length bytes>

``recv_time`` is the receiving host's monotonic clock in seconds; only the
differences between records are meaningful. The payload is the UDP datagram
exactly as received, so it can be re-parsed or replayed later.

Version 2 files also hold one race-off packet each time the game leaves the
race (menu, pause, rewind screen, finish), so the recording can be segmented
again exactly as it was live. Version 1 files only hold race-on packets.

The writer flushes the compressor regularly, so a file left behind by a crash is
readable up to the last flush; the reader stops quietly at a truncated tail.
"""

from __future__ import annotations

import gzip
import struct
import zlib
from collections.abc import Iterator
from pathlib import Path

MAGIC = b"PWRAW002"
MAGIC_V1 = b"PWRAW001"
_VERSIONS = {MAGIC: 2, MAGIC_V1: 1}
_RECORD = struct.Struct("<dH")
_CHUNK = 1 << 16


class RawLogError(ValueError):
    pass


class RawWriter:
    def __init__(self, path: Path, *, compresslevel: int = 6) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = gzip.open(path, "wb", compresslevel=compresslevel)  # noqa: SIM115
        self._file.write(MAGIC)
        self.count = 0

    def append(self, recv_time: float, payload: bytes) -> int:
        """Write one record; returns its index."""
        self._file.write(_RECORD.pack(recv_time, len(payload)))
        self._file.write(payload)
        index = self.count
        self.count += 1
        return index

    def flush(self) -> None:
        self._file.flush()

    def close(self) -> None:
        if not self._file.closed:
            self._file.close()


def _decompressed_chunks(path: Path) -> Iterator[bytes]:
    decomp = zlib.decompressobj(wbits=16 + zlib.MAX_WBITS)
    with path.open("rb") as fh:
        while chunk := fh.read(_CHUNK):
            try:
                data = decomp.decompress(chunk)
            except zlib.error:
                return  # corrupt tail: keep what was readable
            if data:
                yield data
            if decomp.eof:
                return


def iter_records(
    path: Path, start: int = 0, count: int | None = None
) -> Iterator[tuple[float, bytes]]:
    """Yield ``(recv_time, payload)`` for records ``start .. start+count-1``."""
    end = None if count is None else start + count
    buf = bytearray()
    header_checked = False
    index = 0
    for chunk in _decompressed_chunks(path):
        buf += chunk
        pos = 0
        if not header_checked:
            if len(buf) < len(MAGIC):
                continue
            if bytes(buf[: len(MAGIC)]) not in _VERSIONS:
                raise RawLogError(f"{path.name}: not a pitwall raw packet file")
            header_checked = True
            pos = len(MAGIC)
        while len(buf) - pos >= _RECORD.size:
            recv_time, length = _RECORD.unpack_from(buf, pos)
            if len(buf) - pos - _RECORD.size < length:
                break
            if index >= start:
                body = pos + _RECORD.size
                yield recv_time, bytes(buf[body : body + length])
            pos += _RECORD.size + length
            index += 1
            if end is not None and index >= end:
                return
        del buf[:pos]


def read_records(path: Path, start: int = 0, count: int | None = None) -> list[tuple[float, bytes]]:
    return list(iter_records(path, start, count))


def raw_version(path: Path) -> int:
    """Format version of a raw packet file (1 or 2)."""
    with gzip.open(path, "rb") as fh:
        magic = fh.read(len(MAGIC))
    if magic not in _VERSIONS:
        raise RawLogError(f"{path.name}: not a pitwall raw packet file")
    return _VERSIONS[magic]
