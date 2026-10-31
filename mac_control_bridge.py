"""Copy alongside Mac Control server.py. Read-only, fixed loopback upstream.

Mac Control must require its existing session before calling snapshot(). The
browser never receives the notifier administrator credential.
"""
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen, ProxyHandler, build_opener


def snapshot():
    config = Path(__file__).resolve().parent / ".runtime" / "notifier-bridge.json"
    try:
        settings = json.loads(config.read_text())
        state = Path(settings["state_dir"]).expanduser()
        token = (state / "admin-token").read_text().strip()
        port = int(settings.get("port", 8876))
        if not 1024 <= port <= 65535:
            raise ValueError("Invalid port")
        request = Request("http://127.0.0.1:%d/v1/snapshot" % port,
                          headers={"Authorization": "Bearer " + token})
        # Never send the credential through environment-configured HTTP proxies.
        with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
            body = response.read(2*1024*1024+1)
            if len(body) > 2*1024*1024:
                raise ValueError("Snapshot too large")
            data = json.loads(body)
        return {"available": True, "transfers": data["transfers"], "file_activity": data["file_activity"], "finder_progress": data.get("finder_progress", {}), "push": data["push"]}
    except (OSError, ValueError, KeyError):
        return {"available": False, "reason": "notifier_unavailable", "transfers": [], "file_activity": {"items": []}}
