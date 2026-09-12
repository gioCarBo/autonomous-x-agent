"""Minimal RFC6455 WebSocket client for CDP, stdlib only.

No external deps: the Pi runs this with system python3. Supports the subset
of the protocol DevTools needs: client->server text frames (masked), server
text frames (unmasked, any length), connection close. No compression, no
fragmented-server-message reassembly beyond continuation frames (DevTools
does not fragment evaluate results in practice, but we handle continuations
anyway to be safe).
"""

import base64
import os
import socket
import struct


class WsError(Exception):
    pass


class WsClient:
    def __init__(self, host: str, port: int, path: str, timeout: float = 30.0):
        self._sock = socket.create_connection((host, port), timeout=timeout)
        self._sock.settimeout(timeout)
        self._key = base64.b64encode(os.urandom(16)).decode()
        req = (
            f"GET {path} HTTP/1.1\r\n"
            f"Host: {host}:{port}\r\n"
            "Upgrade: websocket\r\n"
            "Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: {self._key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        )
        self._sock.sendall(req.encode())
        self._read_handshake_response()
        self._buf = b""

    def _read_exact(self, n: int) -> bytes:
        while len(self._buf) < n:
            chunk = self._sock.recv(65536)
            if not chunk:
                raise WsError("connection closed by peer")
            self._buf += chunk
        out, self._buf = self._buf[:n], self._buf[n:]
        return out

    def _read_handshake_response(self) -> None:
        data = b""
        while b"\r\n\r\n" not in data:
            chunk = self._sock.recv(4096)
            if not chunk:
                raise WsError("closed during handshake")
            data += chunk
        head, _, rest = data.partition(b"\r\n\r\n")
        self._buf = rest
        status = head.split(b"\r\n")[0].decode()
        if " 101 " not in status:
            raise WsError(f"handshake refused: {status}")
        accept = base64.b64encode(
            __import__("hashlib").sha1(
                (self._key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode()
            ).digest()
        ).decode()
        if accept.encode() not in head:
            raise WsError("bad Sec-WebSocket-Accept")

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        mask = os.urandom(4)
        header = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            header += bytes([0x80 | n])
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        masked = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        self._sock.sendall(header + mask + masked)

    def _recv_frame(self) -> tuple[int, bytes]:
        b1, b2 = self._read_exact(2)
        opcode = b1 & 0x0F
        n = b2 & 0x7F
        if n == 126:
            (n,) = struct.unpack(">H", self._read_exact(2))
        elif n == 127:
            (n,) = struct.unpack(">Q", self._read_exact(8))
        if b2 & 0x80:  # server->client frames are never masked
            raise WsError("unexpected masked server frame")
        payload = self._read_exact(n)
        return opcode, payload

    def send_text(self, text: str) -> None:
        self._send_frame(0x1, text.encode())

    def recv_message(self) -> str:
        """Return the next complete text message, skipping control frames.

        DevTools sends unfragmented messages, so every text frame is one
        complete message.
        """
        while True:
            opcode, payload = self._recv_frame()
            if opcode == 0x8:  # close
                self.close()
                raise WsError("server sent close")
            if opcode == 0x1:  # text
                return payload.decode(errors="replace")
            # ping/pong (0x9/0xA) and stray continuation (0x0): skip

    def close(self) -> None:
        try:
            self._send_frame(0x8, b"")
        except OSError:
            pass
        try:
            self._sock.close()
        except OSError:
            pass
