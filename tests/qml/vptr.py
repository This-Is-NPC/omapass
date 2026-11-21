"""Minimal Wayland client: a zwlr_virtual_pointer_v1 for the QML sandbox's sway.

Usage (inside the sandbox): VPtr().move(x, y); .click(); .close()
"""
import os
import socket
import struct
import time


def _str(s):
    b = s.encode() + b"\0"
    pad = (4 - len(b) % 4) % 4
    return struct.pack("<I", len(b)) + b + b"\0" * pad


class VPtr:
    W, H = 1280, 800

    def __init__(self):
        path = os.path.join(os.environ["XDG_RUNTIME_DIR"], os.environ["WAYLAND_DISPLAY"])
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.s.connect(path)
        self.next_id = 2
        self.buf = b""
        reg = self._new()
        self._send(1, 1, struct.pack("<I", reg))  # get_registry
        globals_ = self._roundtrip(reg)
        name, ver = globals_["zwlr_virtual_pointer_manager_v1"]
        self.mgr = self._new()
        self._send(reg, 0, struct.pack("<I", name) + _str("zwlr_virtual_pointer_manager_v1")
                   + struct.pack("<II", 1, self.mgr))
        self.ptr = self._new()
        self._send(self.mgr, 0, struct.pack("<II", 0, self.ptr))  # seat=null
        self._roundtrip(None)

    def _new(self):
        i = self.next_id
        self.next_id += 1
        return i

    def _send(self, obj, op, payload=b""):
        self.s.sendall(struct.pack("<II", obj, ((8 + len(payload)) << 16) | op) + payload)

    def _roundtrip(self, reg):
        cb = self._new()
        self._send(1, 0, struct.pack("<I", cb))  # sync
        found = {}
        while True:
            while len(self.buf) < 8:
                self.buf += self.s.recv(65536)
            obj, so = struct.unpack_from("<II", self.buf)
            size, op = so >> 16, so & 0xFFFF
            while len(self.buf) < size:
                self.buf += self.s.recv(65536)
            msg, self.buf = self.buf[8:size], self.buf[size:]
            if obj == reg and op == 0:
                name, ln = struct.unpack_from("<II", msg)
                iface = msg[8:8 + ln - 1].decode()
                ver = struct.unpack_from("<I", msg, 8 + ln + (4 - ln % 4) % 4)[0]
                found[iface] = (name, ver)
            elif obj == 1 and op == 0:
                raise RuntimeError("wayland error: %r" % msg)
            elif obj == cb and op == 0:
                return found

    def _t(self):
        return int(time.monotonic() * 1000) & 0xFFFFFFFF

    def move(self, x, y):
        self._send(self.ptr, 1, struct.pack("<IIIII", self._t(), int(x), int(y), self.W, self.H))
        self._send(self.ptr, 4, struct.pack("<I", self._t()))  # frame
        self._roundtrip(None)

    def click(self, button=0x110):
        for state in (1, 0):
            self._send(self.ptr, 2, struct.pack("<III", self._t(), button, state))
            self._send(self.ptr, 4, struct.pack("<I", self._t()))
        self._roundtrip(None)

    def close(self):
        self.s.close()
