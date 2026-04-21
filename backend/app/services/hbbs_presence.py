"""
hbbs_presence — query a RustDesk OSS hbbs server for peer online status.

hbbs keeps each peer's last heartbeat timestamp in memory (not in the sqlite DB).
The official RustDesk client asks hbbs for liveness via the rendezvous proto's
OnlineRequest message on the NAT test TCP port (= main port - 1, default 21115).

We speak just enough of that protocol here — no deps beyond stdlib:
  * hand-rolled protobuf encoder/decoder for the two message types we need
  * custom varint-tagged length prefix framing used by hbb_common::BytesCodec

Reference: rustdesk/hbb_common/protos/rendezvous.proto
  message OnlineRequest  { string id = 1; repeated string peers = 2; }
  message OnlineResponse { bytes states = 1; }
  message RendezvousMessage { oneof union {
      OnlineRequest  online_request  = 23;
      OnlineResponse online_response = 24;
      ...
  } }

Response bitmap: bit i (MSB-first within each byte) is 1 if peers[i] is online,
  where online = last heartbeat received in the past 30s (REG_TIMEOUT in hbbs).
"""

from __future__ import annotations

import logging
import socket
import struct
from dataclasses import dataclass
from typing import Dict, Iterable, List, Sequence

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# protobuf wire-format helpers (minimal — only what we use)
# ---------------------------------------------------------------------------

_WT_VARINT = 0
_WT_LEN = 2


def _encode_varint(n: int) -> bytes:
    if n < 0:
        raise ValueError("varint cannot encode negative")
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        if n:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _decode_varint(buf: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    result = 0
    while True:
        if pos >= len(buf):
            raise ValueError("truncated varint")
        b = buf[pos]
        pos += 1
        result |= (b & 0x7F) << shift
        if not (b & 0x80):
            return result, pos
        shift += 7
        if shift >= 64:
            raise ValueError("varint too long")


def _tag(field_num: int, wire_type: int) -> bytes:
    return _encode_varint((field_num << 3) | wire_type)


def _encode_string(field_num: int, value: str) -> bytes:
    payload = value.encode("utf-8")
    return _tag(field_num, _WT_LEN) + _encode_varint(len(payload)) + payload


def _encode_submessage(field_num: int, payload: bytes) -> bytes:
    return _tag(field_num, _WT_LEN) + _encode_varint(len(payload)) + payload


# ---------------------------------------------------------------------------
# the two messages we actually care about
# ---------------------------------------------------------------------------


def _encode_online_request(requester_id: str, peers: Sequence[str]) -> bytes:
    body = bytearray()
    body += _encode_string(1, requester_id)  # string id = 1
    for p in peers:
        body += _encode_string(2, p)  # repeated string peers = 2
    return bytes(body)


def _encode_rendezvous_with_online_request(
    requester_id: str, peers: Sequence[str]
) -> bytes:
    inner = _encode_online_request(requester_id, peers)
    # oneof field: online_request = 23
    return _encode_submessage(23, inner)


def _parse_online_response_states(rendezvous_bytes: bytes) -> bytes | None:
    """Walk the outer RendezvousMessage, find the online_response (field 24),
    then walk its inner OnlineResponse to pull out states (field 1, bytes)."""
    pos = 0
    while pos < len(rendezvous_bytes):
        tag, pos = _decode_varint(rendezvous_bytes, pos)
        field_num = tag >> 3
        wire_type = tag & 0x7
        if wire_type != _WT_LEN:
            # we only expect LEN-delimited fields inside RendezvousMessage
            # if we see anything else, skip best-effort
            if wire_type == _WT_VARINT:
                _, pos = _decode_varint(rendezvous_bytes, pos)
                continue
            raise ValueError(f"unexpected wire type {wire_type} at pos {pos}")
        length, pos = _decode_varint(rendezvous_bytes, pos)
        sub = rendezvous_bytes[pos : pos + length]
        pos += length
        if field_num != 24:
            continue
        # inside OnlineResponse: field 1, bytes = states
        ipos = 0
        while ipos < len(sub):
            itag, ipos = _decode_varint(sub, ipos)
            ifield = itag >> 3
            iwt = itag & 0x7
            if iwt != _WT_LEN:
                if iwt == _WT_VARINT:
                    _, ipos = _decode_varint(sub, ipos)
                    continue
                raise ValueError(f"unexpected inner wire type {iwt}")
            ilen, ipos = _decode_varint(sub, ipos)
            val = sub[ipos : ipos + ilen]
            ipos += ilen
            if ifield == 1:
                return val
        return b""
    return None


# ---------------------------------------------------------------------------
# hbb_common::BytesCodec framing
# ---------------------------------------------------------------------------
#
# Variable-length header. Low 2 bits of the first byte = (header_len - 1).
# The header, read as a little-endian integer, >> 2 = payload length.
#
#   len <= 0x3F          1-byte header
#   len <= 0x3FFF        2-byte header (little-endian u16)
#   len <= 0x3FFFFF      3-byte header
#   len <= 0x3FFFFFFF    4-byte header (little-endian u32)


def _frame_encode(payload: bytes) -> bytes:
    n = len(payload)
    if n <= 0x3F:
        header = bytes([(n << 2) & 0xFF])
    elif n <= 0x3FFF:
        header = struct.pack("<H", ((n << 2) & 0xFFFF) | 0x1)
    elif n <= 0x3FFFFF:
        v = (n << 2) | 0x2
        header = struct.pack("<H", v & 0xFFFF) + bytes([(v >> 16) & 0xFF])
    elif n <= 0x3FFFFFFF:
        header = struct.pack("<I", (n << 2) | 0x3)
    else:
        raise ValueError("payload too large for hbbs frame")
    return header + payload


def _frame_decode_from_socket(sock: socket.socket, timeout_s: float) -> bytes:
    sock.settimeout(timeout_s)
    first = _recv_exact(sock, 1)
    head_len = (first[0] & 0x3) + 1
    if head_len > 1:
        rest = _recv_exact(sock, head_len - 1)
    else:
        rest = b""
    head_buf = first + rest
    n = head_buf[0]
    if head_len > 1:
        n |= head_buf[1] << 8
    if head_len > 2:
        n |= head_buf[2] << 16
    if head_len > 3:
        n |= head_buf[3] << 24
    payload_len = n >> 2
    if payload_len <= 0 or payload_len > 10_000_000:
        raise ValueError(f"implausible payload length {payload_len}")
    return _recv_exact(sock, payload_len)


def _recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError(f"hbbs closed connection after {len(buf)}/{n} bytes")
        buf += chunk
    return bytes(buf)


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PresenceResult:
    online_ids: frozenset[str]
    queried_ids: tuple[str, ...]

    def is_online(self, peer_id: str) -> bool:
        return peer_id in self.online_ids

    def as_dict(self) -> Dict[str, bool]:
        return {pid: (pid in self.online_ids) for pid in self.queried_ids}


def query_presence(
    host: str,
    port: int,
    peer_ids: Iterable[str],
    requester_id: str = "rdac",
    timeout_s: float = 5.0,
) -> PresenceResult:
    """Ask hbbs which peers in *peer_ids* are currently online.

    * host/port — hbbs NAT-test port (usually main_port - 1, default 21115)
    * peer_ids — RustDesk IDs as strings (e.g. "1139346258")
    * requester_id — arbitrary ID to send as OnlineRequest.id; hbbs doesn't care
    """
    peers_list: List[str] = [pid for pid in peer_ids if pid]
    if not peers_list:
        return PresenceResult(frozenset(), ())

    payload = _encode_rendezvous_with_online_request(requester_id, peers_list)
    frame = _frame_encode(payload)

    log.debug(
        "querying hbbs presence host=%s port=%s n_peers=%d",
        host,
        port,
        len(peers_list),
    )

    with socket.create_connection((host, port), timeout=timeout_s) as sock:
        sock.settimeout(timeout_s)
        sock.sendall(frame)
        response_payload = _frame_decode_from_socket(sock, timeout_s)

    states = _parse_online_response_states(response_payload)
    if states is None:
        raise RuntimeError("hbbs response did not contain online_response")

    online = set()
    for i, pid in enumerate(peers_list):
        byte_idx = i // 8
        bit_idx = 7 - (i % 8)
        if byte_idx < len(states) and (states[byte_idx] & (1 << bit_idx)):
            online.add(pid)

    log.debug("hbbs presence: %d / %d online", len(online), len(peers_list))
    return PresenceResult(frozenset(online), tuple(peers_list))


# ---------------------------------------------------------------------------
# standalone CLI — run this on the Ubuntu host to verify before wiring
# ---------------------------------------------------------------------------


def _cli() -> int:
    import argparse
    import json

    ap = argparse.ArgumentParser(
        description="Probe hbbs for online status of one or more RustDesk IDs."
    )
    ap.add_argument("--host", default="127.0.0.1", help="hbbs host (default 127.0.0.1)")
    ap.add_argument(
        "--port",
        type=int,
        default=21115,
        help="hbbs NAT-test TCP port (default 21115 = main 21116 - 1)",
    )
    ap.add_argument(
        "--timeout", type=float, default=5.0, help="socket timeout seconds"
    )
    ap.add_argument(
        "--json", action="store_true", help="print machine-readable JSON output"
    )
    ap.add_argument("ids", nargs="+", help="RustDesk peer IDs to probe")
    args = ap.parse_args()

    logging.basicConfig(level=logging.DEBUG, format="%(message)s")

    try:
        result = query_presence(args.host, args.port, args.ids, timeout_s=args.timeout)
    except Exception as exc:  # pragma: no cover
        print(f"ERROR: {exc}")
        return 1

    as_map = result.as_dict()
    if args.json:
        print(json.dumps(as_map, indent=2))
    else:
        for pid, is_on in as_map.items():
            dot = "GREEN" if is_on else "gray "
            print(f"  [{dot}] {pid}")
        print(f"\nsummary: {len(result.online_ids)} / {len(as_map)} online")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
