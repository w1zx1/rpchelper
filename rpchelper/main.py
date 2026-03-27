#!/usr/bin/env python3
from __future__ import annotations

import ctypes
import json
import os
import signal
import socket
import struct
import sys
import time
from dataclasses import dataclass
from typing import Optional


DEFAULT_DETAILS = "Using desktop"
DEFAULT_STATE = "No active window"
X11_SUCCESS = 0
X11_ANY_PROPERTY_TYPE = 0
HARDCODED_CLIENT_ID = "1486712000472944671"
HARDCODED_INTERVAL = 2.0
HARDCODED_MAX_TEXT_LEN = 128


@dataclass(frozen=True)
class WindowInfo:
    wm_class: str
    title: str
    process_name: str

    def equals(self, other: Optional["WindowInfo"]) -> bool:
        if other is None:
            return False
        return (
            self.wm_class == other.wm_class
            and self.title == other.title
            and self.process_name == other.process_name
        )


class X11ActiveWindow:
    def __init__(self) -> None:
        if not os.getenv("DISPLAY"):
            raise RuntimeError("DISPLAY is not set. X11 session is required.")

        try:
            self.libx11 = ctypes.CDLL("libX11.so.6")
        except OSError as exc:
            raise RuntimeError("libX11 not found. Install X11 runtime libraries.") from exc

        self.DisplayPtr = ctypes.c_void_p
        self.Window = ctypes.c_ulong
        self.Atom = ctypes.c_ulong

        self.libx11.XOpenDisplay.argtypes = [ctypes.c_char_p]
        self.libx11.XOpenDisplay.restype = self.DisplayPtr

        self.libx11.XDefaultScreen.argtypes = [self.DisplayPtr]
        self.libx11.XDefaultScreen.restype = ctypes.c_int

        self.libx11.XRootWindow.argtypes = [self.DisplayPtr, ctypes.c_int]
        self.libx11.XRootWindow.restype = self.Window

        self.libx11.XInternAtom.argtypes = [self.DisplayPtr, ctypes.c_char_p, ctypes.c_bool]
        self.libx11.XInternAtom.restype = self.Atom

        self.libx11.XGetWindowProperty.argtypes = [
            self.DisplayPtr,
            self.Window,
            self.Atom,
            ctypes.c_long,
            ctypes.c_long,
            ctypes.c_bool,
            self.Atom,
            ctypes.POINTER(self.Atom),
            ctypes.POINTER(ctypes.c_int),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(ctypes.POINTER(ctypes.c_ubyte)),
        ]
        self.libx11.XGetWindowProperty.restype = ctypes.c_int

        self.libx11.XFree.argtypes = [ctypes.c_void_p]
        self.libx11.XFree.restype = ctypes.c_int

        self.libx11.XCloseDisplay.argtypes = [self.DisplayPtr]
        self.libx11.XCloseDisplay.restype = ctypes.c_int

        self.display = self.libx11.XOpenDisplay(None)
        if not self.display:
            raise RuntimeError("Cannot open X11 display. Is X server available?")

        screen = self.libx11.XDefaultScreen(self.display)
        self.root = self.libx11.XRootWindow(self.display, screen)

    def close(self) -> None:
        if self.display:
            self.libx11.XCloseDisplay(self.display)
            self.display = None

    def _atom(self, name: str) -> int:
        return int(self.libx11.XInternAtom(self.display, name.encode("utf-8"), False))

    def _get_property(self, window: int, prop: str, prop_type: Optional[str], max_longs: int = 1024) -> bytes:
        atom_prop = self._atom(prop)
        atom_type = self._atom(prop_type) if prop_type else X11_ANY_PROPERTY_TYPE

        actual_type = self.Atom()
        actual_format = ctypes.c_int()
        nitems = ctypes.c_ulong()
        bytes_after = ctypes.c_ulong()
        prop_return = ctypes.POINTER(ctypes.c_ubyte)()

        status = self.libx11.XGetWindowProperty(
            self.display,
            self.Window(window),
            self.Atom(atom_prop),
            0,
            max_longs,
            False,
            self.Atom(atom_type),
            ctypes.byref(actual_type),
            ctypes.byref(actual_format),
            ctypes.byref(nitems),
            ctypes.byref(bytes_after),
            ctypes.byref(prop_return),
        )
        if status != X11_SUCCESS:
            return b""

        try:
            if not prop_return:
                return b""
            if actual_format.value <= 0:
                return b""
            byte_count = int(nitems.value) * (actual_format.value // 8)
            if byte_count <= 0:
                return b""
            return ctypes.string_at(prop_return, byte_count)
        finally:
            if prop_return:
                self.libx11.XFree(prop_return)

    def _active_window_id(self) -> int:
        raw = self._get_property(self.root, "_NET_ACTIVE_WINDOW", "WINDOW", max_longs=1)
        if len(raw) < 4:
            return 0
        return int.from_bytes(raw[:4], byteorder=sys.byteorder, signed=False)

    @staticmethod
    def _decode_null_terminated(raw: bytes) -> str:
        if not raw:
            return ""
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="replace").strip()

    @staticmethod
    def _parse_wm_class(raw: bytes) -> str:
        if not raw:
            return ""
        parts = [p.decode("utf-8", errors="replace").strip() for p in raw.split(b"\x00") if p]
        if not parts:
            return ""
        return parts[-1]

    @staticmethod
    def _pid_to_name(pid: int) -> str:
        if pid <= 0:
            return ""
        path = f"/proc/{pid}/comm"
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return f.read().strip()
        except OSError:
            return ""

    def get_active_window_info(self) -> WindowInfo:
        wid = self._active_window_id()
        if wid <= 0:
            return WindowInfo("", "", "")

        wm_class_raw = self._get_property(wid, "WM_CLASS", "STRING")
        title_raw = self._get_property(wid, "_NET_WM_NAME", "UTF8_STRING")
        if not title_raw:
            title_raw = self._get_property(wid, "WM_NAME", "STRING")
        pid_raw = self._get_property(wid, "_NET_WM_PID", "CARDINAL", max_longs=1)

        pid = int.from_bytes(pid_raw[:4], byteorder=sys.byteorder, signed=False) if len(pid_raw) >= 4 else 0
        return WindowInfo(
            wm_class=self._parse_wm_class(wm_class_raw),
            title=self._decode_null_terminated(title_raw),
            process_name=self._pid_to_name(pid),
        )


class DiscordIPC:
    def __init__(self, client_id: str) -> None:
        self.client_id = client_id
        self.sock: Optional[socket.socket] = None

    @staticmethod
    def _ipc_candidates() -> list[str]:
        env_path = os.getenv("DISCORD_IPC_PATH")
        if env_path:
            return [env_path]

        candidates: list[str] = []
        runtime_dir = os.getenv("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
        for i in range(10):
            candidates.append(os.path.join(runtime_dir, f"discord-ipc-{i}"))
            candidates.append(os.path.join("/tmp", f"discord-ipc-{i}"))
        return candidates

    def connect(self) -> None:
        last_error: Optional[Exception] = None
        for path in self._ipc_candidates():
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(path)
                self.sock = s
                self._handshake()
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if self.sock:
                    self.sock.close()
                    self.sock = None

        raise RuntimeError(
            f"Could not connect to Discord IPC socket. Is Discord running? Last error: {last_error}"
        )

    def close(self) -> None:
        if self.sock:
            self.sock.close()
            self.sock = None

    def _send_frame(self, op: int, payload: dict) -> None:
        if not self.sock:
            raise RuntimeError("Discord IPC socket is not connected")
        data = json.dumps(payload, separators=(",", ":")).encode("utf-8")
        header = struct.pack("<ii", op, len(data))
        self.sock.sendall(header + data)

    def _recv_exact(self, size: int) -> bytes:
        if not self.sock:
            raise RuntimeError("Discord IPC socket is not connected")
        out = b""
        while len(out) < size:
            chunk = self.sock.recv(size - len(out))
            if not chunk:
                raise RuntimeError("Discord IPC socket closed")
            out += chunk
        return out

    def _recv_frame(self) -> tuple[int, dict]:
        header = self._recv_exact(8)
        op, size = struct.unpack("<ii", header)
        payload_raw = self._recv_exact(size)
        payload = json.loads(payload_raw.decode("utf-8"))
        return op, payload

    def _request(self, cmd: str, args: dict) -> dict:
        nonce = str(time.time_ns())
        payload = {"cmd": cmd, "args": args, "nonce": nonce}
        self._send_frame(1, payload)
        _, response = self._recv_frame()
        if response.get("evt") == "ERROR":
            data = response.get("data") or {}
            code = data.get("code")
            message = data.get("message")
            raise RuntimeError(f"Discord RPC error {code}: {message}")
        return response

    def _handshake(self) -> None:
        self._send_frame(0, {"v": 1, "client_id": self.client_id})
        _, response = self._recv_frame()
        if response.get("cmd") != "DISPATCH":
            raise RuntimeError(f"Unexpected Discord handshake response: {response}")

    def update_activity(self, activity: dict) -> None:
        args = {"pid": os.getpid(), "activity": activity}
        self._request("SET_ACTIVITY", args)

    def clear_activity(self) -> None:
        args = {"pid": os.getpid(), "activity": None}
        self._request("SET_ACTIVITY", args)


def to_presence_fields(info: WindowInfo, max_len: int) -> tuple[str, str]:
    def _truncate_with_ellipsis(value: str, limit: int) -> str:
        if len(value) <= limit:
            return value
        if limit <= 3:
            return "." * limit
        return value[: limit - 3] + "..."

    raw_name = info.process_name or info.wm_class or "Unknown app"
    app_name = raw_name[:1].upper() + raw_name[1:] if raw_name else "Unknown app"
    title = info.title or "No title"
    details = _truncate_with_ellipsis(f"😛 In {app_name}", max_len)
    state = _truncate_with_ellipsis(title, max_len)
    return details, state


def connect_rpc(client_id: str, retries: int = 8, delay: float = 2.5) -> DiscordIPC:
    last_error: Optional[Exception] = None
    for _ in range(retries):
        try:
            rpc = DiscordIPC(client_id)
            rpc.connect()
            return rpc
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            time.sleep(delay)
    raise RuntimeError(f"Failed to connect to Discord RPC: {last_error}")


def run_loop(
    client_id: str,
    interval: float,
    max_text_len: int,
) -> None:
    x11 = X11ActiveWindow()
    rpc = connect_rpc(client_id)
    started_at = int(time.time())
    last_info: Optional[WindowInfo] = None

    print("RPCHelper started. Press Ctrl+C to stop.")
    try:
        while True:
            info = x11.get_active_window_info()
            if not info.equals(last_info):
                details, state = to_presence_fields(info, max_text_len)
                activity = {
                    "details": details or DEFAULT_DETAILS,
                    "state": state or DEFAULT_STATE,
                    "timestamps": {"start": started_at},
                }

                try:
                    rpc.update_activity(activity)
                    last_info = info
                    print(
                        f"Updated RPC: details={activity['details']!r} "
                        f"state={activity['state']!r}"
                    )
                except Exception as exc:  # noqa: BLE001
                    print(f"RPC update failed: {exc}. Reconnecting...")
                    rpc.close()
                    rpc = connect_rpc(client_id)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\nStopping RPCHelper...")
    finally:
        try:
            rpc.clear_activity()
        except Exception:  # noqa: BLE001
            pass
        rpc.close()
        x11.close()


def _handle_sigterm(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def main() -> int:
    signal.signal(signal.SIGTERM, _handle_sigterm)
    if not HARDCODED_CLIENT_ID:
        print(
            "Error: missing Discord Client ID. "
            "Set HARDCODED_CLIENT_ID in rpchelper/main.py.",
            file=sys.stderr,
        )
        return 2

    try:
        run_loop(
            client_id=HARDCODED_CLIENT_ID,
            interval=max(0.3, HARDCODED_INTERVAL),
            max_text_len=max(16, HARDCODED_MAX_TEXT_LEN),
        )
        return 0
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
