"""Explicit HTTPS origin and mount path for the local Tailscale Serve proxy."""
import ipaddress
import json
from pathlib import Path
import re


class ServeConfig:
    def __init__(self, origin, path_prefix):
        # Deliberately no wildcard host or arbitrary forwarded-origin trust.
        if not isinstance(origin, str) or not re.fullmatch(
                r'https://[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.[a-z0-9-]+\.ts\.net', origin):
            raise ValueError('Tailscale Serve origin must be an exact HTTPS ts.net hostname')
        if not isinstance(path_prefix, str) or not re.fullmatch(r'(?:/[A-Za-z0-9_-]+)+', path_prefix):
            raise ValueError('Tailscale Serve path_prefix must be a path such as /mc')
        self.origin = origin
        self.host = origin.removeprefix('https://')
        self.path_prefix = path_prefix

    def matches(self, address, headers):
        try:
            loopback = ipaddress.ip_address(address).is_loopback
        except ValueError:
            return False
        return (loopback and headers.get('Host') == self.host
                and headers.get('X-Forwarded-Host') == self.host
                and headers.get('X-Forwarded-Proto') == 'https'
                and not headers.get('Tailscale-Funnel-Request'))

    def render_html(self, body):
        prefix = self.path_prefix.encode()
        return (body.replace(b'href="/', b'href="' + prefix + b'/')
                .replace(b'src="/', b'src="' + prefix + b'/')
                .replace(b'name="mac-control-base" content=""',
                         b'name="mac-control-base" content="' + prefix + b'"'))


def load_config(path):
    try:
        with Path(path).open('rb') as file:
            body = file.read(4097)
    except FileNotFoundError:
        return None
    if len(body) > 4096:
        raise ValueError('Tailscale Serve configuration exceeds 4096 bytes')
    data = json.loads(body)
    if not isinstance(data, dict):
        raise ValueError('Tailscale Serve configuration must be a JSON object')
    return ServeConfig(data.get('origin'), data.get('path_prefix'))
