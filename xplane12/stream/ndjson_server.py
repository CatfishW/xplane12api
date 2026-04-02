from __future__ import annotations

import json
import socket
import threading
from typing import Any


class NdjsonBroadcastServer:
    def __init__(self, host: str, port: int) -> None:
        self._host = host
        self._port = port
        self._server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server.bind((host, port))
        self._server.listen()
        self._clients: list[socket.socket] = []
        self._lock = threading.Lock()
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, name="XPlaneNdjsonAccept", daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                client, _ = self._server.accept()
                client.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                with self._lock:
                    self._clients.append(client)
            except OSError:
                return

    def broadcast(self, payload: dict[str, Any]) -> None:
        encoded = (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        stale: list[socket.socket] = []
        with self._lock:
            for client in self._clients:
                try:
                    client.sendall(encoded)
                except OSError:
                    stale.append(client)
            for client in stale:
                if client in self._clients:
                    self._clients.remove(client)
                try:
                    client.close()
                except OSError:
                    pass

    def close(self) -> None:
        self._running = False
        try:
            self._server.close()
        except OSError:
            pass
        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except OSError:
                    pass
            self._clients.clear()
