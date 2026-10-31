"""Password hashes and revocable remembered sessions, stored only on this Mac."""
from contextlib import contextmanager
import hashlib
import hmac
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time

REMEMBER_SECONDS = 30 * 24 * 60 * 60
SESSION_SECONDS = 24 * 60 * 60
PASSWORD_ITERATIONS = 600_000


class AuthStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        descriptor = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        self.path.chmod(0o600)
        with self.connection() as db:
            db.execute('CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)')
            db.execute('CREATE TABLE IF NOT EXISTS sessions (token_hash TEXT PRIMARY KEY, expires REAL NOT NULL, remembered INTEGER NOT NULL)')

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def configured(self):
        with self.connection() as db:
            return db.execute("SELECT 1 FROM settings WHERE key = 'password'").fetchone() is not None

    @staticmethod
    def validate_password(password):
        if not isinstance(password, str) or not password or len(password) > 1024:
            raise ValueError('Enter a password between 1 and 1024 characters.')

    def set_password(self, password, first_time=False):
        self.validate_password(password)
        salt = secrets.token_bytes(32)
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, PASSWORD_ITERATIONS)
        record = json.dumps({'salt': salt.hex(), 'digest': digest.hex(), 'iterations': PASSWORD_ITERATIONS})
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if first_time and db.execute("SELECT 1 FROM settings WHERE key = 'password'").fetchone():
                raise ValueError('A password is already set. Sign in with your password.')
            db.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('password', ?)", (record,))
            db.execute('DELETE FROM sessions')

    def verify_password(self, password):
        try:
            self.validate_password(password)
        except ValueError:
            return False
        with self.connection() as db:
            row = db.execute("SELECT value FROM settings WHERE key = 'password'").fetchone()
        if not row:
            return False
        record = json.loads(row[0])
        digest = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), bytes.fromhex(record['salt']), record['iterations'])
        return hmac.compare_digest(digest, bytes.fromhex(record['digest']))

    def new_session(self, remember):
        token = secrets.token_urlsafe(32)
        now = time.time()
        expiry = now + (REMEMBER_SECONDS if remember else SESSION_SECONDS)
        with self.connection() as db:
            db.execute('DELETE FROM sessions WHERE expires <= ?', (now,))
            db.execute('INSERT INTO sessions (token_hash, expires, remembered) VALUES (?, ?, ?)',
                       (self.token_hash(token), expiry, int(remember)))
        return token

    @staticmethod
    def token_hash(token):
        return hashlib.sha256(token.encode('utf-8')).hexdigest()

    def valid_session(self, token):
        if not isinstance(token, str) or not 20 <= len(token) <= 100:
            return False
        with self.connection() as db:
            row = db.execute('SELECT expires FROM sessions WHERE token_hash = ?', (self.token_hash(token),)).fetchone()
        return bool(row and row[0] > time.time())

    def delete_session(self, token):
        if token:
            with self.connection() as db:
                db.execute('DELETE FROM sessions WHERE token_hash = ?', (self.token_hash(token),))
