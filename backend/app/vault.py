"""Encrypted secret vault for provider credentials.

Secrets are sealed with AES-256-GCM. The master key comes from the server environment
(AI_FACTORY_VAULT_KEY, urlsafe base64 of 32 bytes) and never touches the database. Each
ciphertext is bound to its owner and credential id through associated data, so a row copied
to another user or credential fails to decrypt. The browser only ever sees `vault://<id>`.
"""

from __future__ import annotations

import base64
import hashlib
import os
import re
import secrets
import sqlite3

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_ENV = "AI_FACTORY_VAULT_KEY"
KEY_VERSION = 1
REF_PREFIX = "vault://"


class VaultError(RuntimeError):
    pass


def generate_key() -> str:
    return base64.urlsafe_b64encode(AESGCM.generate_key(bit_length=256)).decode()


def _master_key() -> bytes:
    raw = os.environ.get(KEY_ENV, "").strip()
    if not raw:
        raise VaultError(f"{KEY_ENV} is not configured")
    try:
        key = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except ValueError as exc:
        raise VaultError(f"{KEY_ENV} is not valid base64") from exc
    if len(key) != 32:
        raise VaultError(f"{KEY_ENV} must decode to 32 bytes")
    return key


def configured() -> bool:
    try:
        _master_key()
    except VaultError:
        return False
    return True


def _aad(user_id: str, credential_id: str) -> bytes:
    return f"ai-factory:{user_id}:{credential_id}".encode()


def fingerprint(secret: str) -> str:
    """Short non-reversible identifier so the UI can tell keys apart without seeing them."""
    return hashlib.sha256(secret.encode()).hexdigest()[:8]


def store(conn: sqlite3.Connection, user_id: str, secret: str) -> str:
    if not secret:
        raise VaultError("empty secret")
    credential_id = "cred_" + secrets.token_urlsafe(12)
    nonce = os.urandom(12)
    ciphertext = AESGCM(_master_key()).encrypt(nonce, secret.encode(), _aad(user_id, credential_id))
    conn.execute(
        "INSERT INTO encrypted_credentials(id, user_id, key_version, nonce, ciphertext, fingerprint) VALUES (?,?,?,?,?,?)",
        (credential_id, user_id, KEY_VERSION, nonce, ciphertext, fingerprint(secret)),
    )
    return credential_id


def reveal(conn: sqlite3.Connection, user_id: str, credential_id: str) -> str:
    """Decrypts a credential for server-side adapter use only. Never return this to a client."""
    row = conn.execute(
        "SELECT nonce, ciphertext FROM encrypted_credentials WHERE id = ? AND user_id = ?",
        (credential_id, user_id),
    ).fetchone()
    if row is None:
        raise VaultError("credential not found")
    try:
        plain = AESGCM(_master_key()).decrypt(row["nonce"], row["ciphertext"], _aad(user_id, credential_id))
    except Exception as exc:  # InvalidTag and friends: never leak detail
        raise VaultError("credential could not be decrypted") from exc
    return plain.decode()


def delete(conn: sqlite3.Connection, user_id: str, credential_id: str) -> None:
    conn.execute("DELETE FROM encrypted_credentials WHERE id = ? AND user_id = ?", (credential_id, user_id))


def reference(credential_id: str | None) -> str | None:
    return REF_PREFIX + credential_id if credential_id else None


# Patterns keep their labelled prefix (group 1) and replace only the secret value.
_LABELLED_SECRETS = [
    re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}"),
    re.compile(r"(?i)((?:api[_-]?key|x-goog-api-key|authorization|token)[\"'=:\s]+)[A-Za-z0-9._\-]{8,}"),
]
# Well-known provider key shapes that can appear without a label.
_BARE_SECRETS = re.compile(r"\b(?:sk|gsk|csk|AIza|hf|ghp|gho|github_pat)[_\-A-Za-z0-9]{12,}")


def redact(text: str, *known_secrets: str) -> str:
    """Removes secrets from text before it is logged or returned in an error."""
    out = str(text)
    for secret in known_secrets:
        if secret:
            out = out.replace(secret, "[REDACTED]")
    for pattern in _LABELLED_SECRETS:
        out = pattern.sub(lambda m: m.group(1) + "[REDACTED]", out)
    return _BARE_SECRETS.sub("[REDACTED]", out)
