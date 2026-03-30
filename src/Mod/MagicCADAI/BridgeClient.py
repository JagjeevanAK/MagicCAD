# SPDX-License-Identifier: LGPL-2.1-or-later

import json
import os
import socket
import sys
import time
import urllib.error
import urllib.request

import FreeCAD
from freecad.utils import get_python_exe

import QtCompat


QtCore = QtCompat.QtCore
Signal = QtCompat.Signal


class EventStreamThread(QtCore.QThread):
    eventReceived = Signal(dict)
    streamError = Signal(str, str)
    streamFinished = Signal(str)

    def __init__(self, base_url, run_id, parent=None):
        super(EventStreamThread, self).__init__(parent)
        self._base_url = base_url.rstrip("/")
        self._run_id = run_id

    def run(self):
        request = urllib.request.Request(
            "{0}/v1/runs/{1}/events".format(self._base_url, self._run_id),
            headers={"Accept": "text/event-stream"},
        )
        event_name = None
        data_lines = []
        try:
            with urllib.request.urlopen(request) as response:
                for raw_line in response:
                    line = raw_line.decode("utf-8", "replace").rstrip("\r\n")
                    if not line:
                        if data_lines:
                            payload = self._decode_event_payload(event_name, data_lines)
                            self.eventReceived.emit(payload)
                            event_name = None
                            data_lines = []
                        continue
                    if line.startswith(":"):
                        continue
                    if line.startswith("event:"):
                        event_name = line[6:].strip()
                    elif line.startswith("data:"):
                        data_lines.append(line[5:].lstrip())
        except Exception as exc:
            self.streamError.emit(self._run_id, str(exc))
        finally:
            self.streamFinished.emit(self._run_id)

    def _decode_event_payload(self, event_name, data_lines):
        text = "\n".join(data_lines).strip()
        if not text:
            return {"event": event_name or "message"}
        try:
            payload = json.loads(text)
        except Exception:
            payload = {"event": event_name or "message", "text": text}
        if isinstance(payload, dict):
            payload.setdefault("event", event_name or payload.get("event") or "message")
            return payload
        return {"event": event_name or "message", "payload": payload}


class SidecarBridgeClient(QtCore.QObject):
    statusChanged = Signal(str)
    eventReceived = Signal(dict)
    bridgeError = Signal(str, str)

    def __init__(self, parent=None):
        super(SidecarBridgeClient, self).__init__(parent)
        self._host = "127.0.0.1"
        self._port = None
        self._process = None
        self._event_threads = {}

    @property
    def base_url(self):
        if self._port is None:
            return ""
        return "http://{0}:{1}".format(self._host, self._port)

    def ensure_started(self, timeout_ms=6000):
        if self._port is not None and self.is_healthy():
            return True

        if self._process is None or self._process.state() == QtCore.QProcess.NotRunning:
            self._launch_sidecar()

        deadline = time.time() + float(timeout_ms) / 1000.0
        while time.time() < deadline:
            if self.is_healthy():
                self.statusChanged.emit("Sidecar ready on {0}".format(self.base_url))
                return True
            QtCompat.process_events()
            time.sleep(0.1)
        self.bridgeError.emit("startup", "MagicCAD AI sidecar did not become healthy in time")
        return False

    def is_healthy(self):
        if self._port is None:
            return False
        try:
            response = self._request("GET", "/health", timeout=1.0)
        except Exception:
            return False
        return response.get("ok", False)

    def start_run(self, payload):
        if not self.ensure_started():
            return None
        try:
            response = self._request("POST", "/v1/runs", payload)
            run_id = response.get("run_id", "")
            if run_id:
                self._start_event_stream(run_id)
            return response
        except Exception as exc:
            self.bridgeError.emit("start_run", str(exc))
            return None

    def submit_tool_results(self, run_id, payload):
        try:
            response = self._request("POST", "/v1/runs/{0}/tool-results".format(run_id), payload)
            self._ensure_event_stream(run_id)
            return response
        except Exception as exc:
            self.bridgeError.emit("tool_results", str(exc))
            return {"ok": False, "error": str(exc)}

    def resume_run(self, run_id, decision, payload=None):
        body = {"decision": decision, "payload": payload or {}}
        try:
            response = self._request("POST", "/v1/runs/{0}/resume".format(run_id), body)
            self._ensure_event_stream(run_id)
            return response
        except Exception as exc:
            self.bridgeError.emit("resume_run", str(exc))
            return {"ok": False, "error": str(exc)}

    def shutdown(self):
        for thread in list(self._event_threads.values()):
            thread.wait(500)
        self._event_threads = {}
        if self._process is not None:
            if self._process.state() != QtCore.QProcess.NotRunning:
                self._process.terminate()
                self._process.waitForFinished(1000)
            self._process = None

    def _launch_sidecar(self):
        self._port = self._pick_free_port()
        python_exe = get_python_exe() or sys.executable or "python3"
        module_dir = os.path.dirname(__file__)
        sidecar_path = os.path.join(module_dir, "SidecarServer.py")
        data_dir = os.path.join(FreeCAD.getUserAppDataDir(), "MagicCADAI")
        if not os.path.isdir(data_dir):
            os.makedirs(data_dir)
        database_path = os.path.join(data_dir, "runs.sqlite3")

        self._process = QtCore.QProcess(self)
        self._process.readyReadStandardOutput.connect(self._drain_stdout)
        self._process.readyReadStandardError.connect(self._drain_stderr)
        args = [
            "-X",
            "utf8",
            "-E",
            sidecar_path,
            "--host",
            self._host,
            "--port",
            str(self._port),
            "--database",
            database_path,
        ]
        self.statusChanged.emit("Starting MagicCAD AI sidecar...")
        self._process.start(python_exe, args)

    def _pick_free_port(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind((self._host, 0))
            return probe.getsockname()[1]

    def _request(self, method, path, payload=None, timeout=5.0):
        if self._port is None:
            raise RuntimeError("Sidecar port is not initialized")
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            body = json.dumps(payload).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.base_url + path,
            data=body,
            headers=headers,
            method=method,
        )
        with urllib.request.urlopen(request, timeout=timeout) as response:
            text = response.read().decode("utf-8", "replace").strip()
        if not text:
            return {}
        return json.loads(text)

    def _start_event_stream(self, run_id):
        existing = self._event_threads.pop(run_id, None)
        if existing is not None:
            existing.wait(100)
        thread = EventStreamThread(self.base_url, run_id, self)
        thread.eventReceived.connect(self.eventReceived.emit)
        thread.streamError.connect(self.bridgeError.emit)
        thread.streamFinished.connect(self._cleanup_thread)
        self._event_threads[run_id] = thread
        thread.start()

    def _ensure_event_stream(self, run_id):
        thread = self._event_threads.get(run_id)
        if thread is None or thread.isFinished():
            self._start_event_stream(run_id)

    def _cleanup_thread(self, run_id):
        thread = self._event_threads.pop(run_id, None)
        if thread is not None:
            thread.deleteLater()

    def _drain_stdout(self):
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardOutput()).decode("utf-8", "replace").strip()
        if data:
            FreeCAD.Console.PrintLog("MagicCADAI sidecar: {0}\n".format(data))

    def _drain_stderr(self):
        if self._process is None:
            return
        data = bytes(self._process.readAllStandardError()).decode("utf-8", "replace").strip()
        if data:
            FreeCAD.Console.PrintWarning("MagicCADAI sidecar: {0}\n".format(data))
