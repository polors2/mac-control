"""Private atomic settings files and bounded, viewer-independent startup restore."""
import json
import os
from pathlib import Path
import threading


def read_settings(path):
    if path is None: return {}
    try:
        value = json.loads(Path(path).read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError): return {}


def write_settings(path, value):
    if path is None: return
    path = Path(path)
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    temporary = path.with_suffix('.tmp')
    descriptor = os.open(temporary, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, 'w') as file:
        json.dump(value, file)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temporary, path)


class StartupRestore:
    def __init__(self, tasks, attempts=12, interval=5):
        self.tasks = dict(tasks)
        self.attempts, self.interval = attempts, interval
        self.stopped = threading.Event()
        self.thread = threading.Thread(target=self.run, name='restore-settings', daemon=True)

    def start(self): self.thread.start()

    def run(self):
        pending = dict(self.tasks)
        for attempt in range(self.attempts):
            for name, restore in list(pending.items()):
                if self.stopped.is_set(): return
                try:
                    restore()
                    del pending[name]
                except (RuntimeError, ValueError, OSError) as error:
                    print(f'Startup restore ({name}): {error}', flush=True)
            if not pending or attempt + 1 == self.attempts: return
            if self.stopped.wait(self.interval): return

    def close(self):
        self.stopped.set()
        if self.thread.is_alive(): self.thread.join(timeout=3)
