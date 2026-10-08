"""Manage only the subprocess group created by this object."""

import os
import signal
import subprocess
import time


class OwnedProcess:
    def __init__(self, command):
        self.command = command
        self.process = None

    def start(self):
        if self.process is not None:
            raise RuntimeError('Stop the existing process group before restarting')
        self.process = subprocess.Popen(self.command, start_new_session=True)

    def stop(self):
        process = self.process
        if process is None:
            return
        for sig, timeout in ((signal.SIGINT, 6.0), (signal.SIGTERM, 2.0), (signal.SIGKILL, 2.0)):
            try:
                os.killpg(process.pid, sig)
            except ProcessLookupError:
                process.poll()
                self.process = None
                return
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                process.poll()  # Reap the direct child while descendants exit.
                try:
                    os.killpg(process.pid, 0)
                except ProcessLookupError:
                    self.process = None
                    return
                time.sleep(0.05)
        raise RuntimeError('Owned process group did not terminate; refusing duplicate launch')
