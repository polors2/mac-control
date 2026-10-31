"""Supervise the tiny display-only guard while persistent Display Off is selected."""
import subprocess
import threading


class BrightnessKeeper:
    def __init__(self, binary, factory=None, retry_interval=2):
        self.binary = str(binary)
        self.factory = factory or subprocess.Popen
        self.retry_interval = retry_interval
        self.condition = threading.Condition()
        self.enabled = False
        self.stopped = False
        self.process = None
        self.error = None
        self.thread = threading.Thread(target=self.run, name='display-off-keeper', daemon=True)
        self.thread.start()

    def start_locked(self):
        if self.process is not None and self.process.poll() is None:
            self.error = None
            return
        if self.process is not None and self.process.poll() is not None:
            if self.process.stdin: self.process.stdin.close()
            self.process = None
            self.error = 'The display-off guard exited; retrying.'
        if self.process is None:
            try:
                self.process = self.factory([self.binary, 'hold-off'], stdin=subprocess.PIPE,
                                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except OSError:
                self.error = 'Could not keep the display off. Run the installer to rebuild its helper.'

    def stop_locked(self):
        process, self.process = self.process, None
        if process is None: return
        if process.stdin: process.stdin.close()
        try:
            if process.poll() is None: process.terminate()
            process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            process.kill(); process.wait(timeout=1)

    def set_enabled(self, enabled):
        with self.condition:
            self.enabled = bool(enabled)
            if self.enabled and not self.stopped: self.start_locked()
            else: self.stop_locked()
            if not self.enabled: self.error = None
            self.condition.notify_all()

    def status(self):
        with self.condition:
            return {'enabled': self.enabled,
                    'running': bool(self.process is not None and self.process.poll() is None),
                    'error': self.error}

    def run(self):
        with self.condition:
            while not self.stopped:
                if not self.enabled:
                    self.condition.wait()  # No process or timed checks while display persistence is inactive.
                    continue
                self.start_locked()
                self.condition.wait(timeout=self.retry_interval)

    def close(self):
        with self.condition:
            self.stopped = True; self.enabled = False
            self.stop_locked(); self.condition.notify_all()
        self.thread.join(timeout=3)
