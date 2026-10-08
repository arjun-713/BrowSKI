"""Authenticated encryption for durable LangGraph SQLite checkpoints."""

from __future__ import annotations

import asyncio
import base64
import os
import secrets
import sqlite3
import stat
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Protocol, cast

import aiosqlite
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from langgraph.checkpoint.serde.base import SerializerProtocol
from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver

_KEY_BYTES = 32
_NONCE_BYTES = 12
_TAG_BYTES = 16
_TYPE_LENGTH_BYTES = 2
_CIPHER_NAME = "aes-256-gcm-v1"
_SERIALIZED_TYPE = f"browski-checkpoint-v1+{_CIPHER_NAME}"
_AUTHENTICATED_DATA = b"browski/langgraph-checkpoint/v1"
_KEYRING_SERVICE = "browski-checkpoint-encryption"
_KEYRING_ACCOUNT = "user-checkpoint-key-v1"
_KEY_FILENAME = "checkpoint-encryption-v1.key"


class CheckpointEncryptionError(RuntimeError):
    """Raised when a checkpoint is plaintext, corrupt, or cannot be decrypted."""


class CheckpointKeyError(RuntimeError):
    """Raised when checkpoint key material cannot be read or stored safely."""


class CheckpointKeyStore(Protocol):
    """Load or create the key used for this user's durable checkpoints."""

    def load_or_create(self, database: Path) -> bytes: ...


class _Keyring(Protocol):
    def get_password(self, service_name: str, username: str) -> object | None: ...

    def set_password(self, service_name: str, username: str, password: str) -> None: ...

    def get_keyring(self) -> object: ...


class EncryptedCheckpointSerializer(SerializerProtocol):
    """Encrypt typed LangGraph values and reject plaintext legacy data."""

    def __init__(self, key: bytes, *, inner: SerializerProtocol | None = None) -> None:
        if len(key) != _KEY_BYTES:
            raise ValueError("checkpoint encryption keys must contain 32 bytes")
        self._cipher = AESGCM(key)
        self._inner = inner or JsonPlusSerializer()

    def dumps_typed(self, obj: Any) -> tuple[str, bytes]:
        inner_type, payload = self._inner.dumps_typed(obj)
        type_bytes = inner_type.encode("utf-8")
        if len(type_bytes) > (2 ** (_TYPE_LENGTH_BYTES * 8) - 1):
            raise CheckpointEncryptionError("checkpoint serializer type is too long")
        envelope = len(type_bytes).to_bytes(_TYPE_LENGTH_BYTES, "big") + type_bytes + payload
        nonce = secrets.token_bytes(_NONCE_BYTES)
        ciphertext = self._cipher.encrypt(nonce, envelope, _AUTHENTICATED_DATA)
        return _SERIALIZED_TYPE, nonce + ciphertext

    def loads_typed(self, data: tuple[str, bytes]) -> Any:
        serialized_type, ciphertext = data
        if serialized_type != _SERIALIZED_TYPE:
            raise CheckpointEncryptionError(
                "plaintext or unsupported legacy checkpoint data is rejected"
            )
        if len(ciphertext) < _NONCE_BYTES + _TAG_BYTES + _TYPE_LENGTH_BYTES:
            raise CheckpointEncryptionError("encrypted checkpoint is truncated")
        nonce = ciphertext[:_NONCE_BYTES]
        try:
            envelope = self._cipher.decrypt(
                nonce,
                ciphertext[_NONCE_BYTES:],
                _AUTHENTICATED_DATA,
            )
        except InvalidTag:
            raise CheckpointEncryptionError(
                "checkpoint authentication failed; key may be unavailable or data corrupt"
            ) from None

        type_length = int.from_bytes(envelope[:_TYPE_LENGTH_BYTES], "big")
        type_end = _TYPE_LENGTH_BYTES + type_length
        if type_length == 0 or type_end > len(envelope):
            raise CheckpointEncryptionError("encrypted checkpoint type header is invalid")
        try:
            inner_type = envelope[_TYPE_LENGTH_BYTES:type_end].decode("utf-8")
        except UnicodeDecodeError:
            raise CheckpointEncryptionError("encrypted checkpoint type header is invalid") from None
        return self._inner.loads_typed((inner_type, envelope[type_end:]))


class PrivateFileCheckpointKeyStore:
    """Store a generated key in an owner-only local file as a fallback."""

    def __init__(self, directory: Path | None = None) -> None:
        self._directory = directory or _default_key_directory()

    def load_or_create(self, database: Path) -> bytes:
        existing = self._read_existing()
        if existing is not None:
            return existing
        if _database_has_saved_data(database):
            raise CheckpointKeyError(
                "checkpoint key is unavailable for a non-empty database; refusing to replace it"
            )
        return self._create()

    def read_existing(self) -> bytes | None:
        return self._read_existing()

    def _read_existing(self) -> bytes | None:
        directory = self._directory
        _ensure_private_directory(directory, create=False)
        path = directory / _KEY_FILENAME
        try:
            info = path.lstat()
        except FileNotFoundError:
            return None
        except OSError:
            raise CheckpointKeyError("checkpoint key file cannot be inspected safely") from None
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
            raise CheckpointKeyError("checkpoint key path must be a regular non-symlink file")
        _require_private_file_mode(info)
        if hasattr(os, "getuid") and info.st_uid != os.getuid():
            raise CheckpointKeyError("checkpoint key file must be owned by the current user")

        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise CheckpointKeyError("safe checkpoint key file reads are unsupported here")
        try:
            file_descriptor = os.open(path, os.O_RDONLY | nofollow)
            try:
                opened_info = os.fstat(file_descriptor)
                if not stat.S_ISREG(opened_info.st_mode):
                    raise CheckpointKeyError("checkpoint key path is not a regular file")
                _require_private_file_mode(opened_info)
                if hasattr(os, "getuid") and opened_info.st_uid != os.getuid():
                    raise CheckpointKeyError(
                        "checkpoint key file must be owned by the current user"
                    )
                key = os.read(file_descriptor, _KEY_BYTES + 1)
            finally:
                os.close(file_descriptor)
        except CheckpointKeyError:
            raise
        except OSError:
            raise CheckpointKeyError("checkpoint key file cannot be read safely") from None
        if len(key) != _KEY_BYTES:
            raise CheckpointKeyError("checkpoint key file has an invalid length")
        return key

    def _create(self) -> bytes:
        directory = self._directory
        _ensure_private_directory(directory, create=True)
        key = secrets.token_bytes(_KEY_BYTES)
        path = directory / _KEY_FILENAME
        nofollow = getattr(os, "O_NOFOLLOW", None)
        if nofollow is None:
            raise CheckpointKeyError("safe checkpoint key file creation is unsupported here")
        try:
            file_descriptor = os.open(
                path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL | nofollow,
                0o600,
            )
        except FileExistsError:
            existing = self._read_existing()
            if existing is None:
                raise CheckpointKeyError("checkpoint key file was created concurrently") from None
            return existing
        except OSError:
            raise CheckpointKeyError("checkpoint key file cannot be created safely") from None

        try:
            remaining = memoryview(key)
            while remaining:
                written = os.write(file_descriptor, remaining)
                if written <= 0:
                    raise OSError("checkpoint key write made no progress")
                remaining = remaining[written:]
            os.fsync(file_descriptor)
        except OSError:
            try:
                os.unlink(path)
            except OSError:
                pass
            raise CheckpointKeyError("checkpoint key file could not be saved safely") from None
        finally:
            os.close(file_descriptor)
        return key


class SystemCheckpointKeyStore:
    """Prefer the OS keyring and fall back to a private local key file."""

    def __init__(
        self,
        *,
        keyring_module: _Keyring | None = None,
        fallback: PrivateFileCheckpointKeyStore | None = None,
    ) -> None:
        self._keyring_module = keyring_module
        self._fallback = fallback or PrivateFileCheckpointKeyStore()

    def load_or_create(self, database: Path) -> bytes:
        keyring = self._load_keyring()
        if keyring is None:
            return self._fallback.load_or_create(database)

        try:
            encoded = keyring.get_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT)
        except Exception:
            return self._fallback.load_or_create(database)

        if encoded is not None:
            key = _decode_key(encoded)
            fallback_key = self._fallback.read_existing() if os.name != "nt" else None
            if fallback_key is not None and not secrets.compare_digest(key, fallback_key):
                raise CheckpointKeyError("OS keyring and fallback checkpoint keys do not match")
            return key

        fallback_key = self._fallback.read_existing() if os.name != "nt" else None
        if fallback_key is not None:
            try:
                keyring.set_password(
                    _KEYRING_SERVICE,
                    _KEYRING_ACCOUNT,
                    _encode_key(fallback_key),
                )
            except Exception:
                pass
            return fallback_key

        if _database_has_saved_data(database):
            raise CheckpointKeyError(
                "checkpoint key is missing for a non-empty database; refusing to replace it"
            )
        key = secrets.token_bytes(_KEY_BYTES)
        try:
            keyring.set_password(_KEYRING_SERVICE, _KEYRING_ACCOUNT, _encode_key(key))
        except Exception:
            return self._fallback.load_or_create(database)
        return key

    def _load_keyring(self) -> _Keyring | None:
        module = self._keyring_module
        if module is None:
            try:
                import keyring as imported_keyring
            except ImportError:
                return None
            module = cast(_Keyring, imported_keyring)
            self._keyring_module = module
        try:
            backend = module.get_keyring()
            priority = getattr(backend, "priority", 0)
            if not isinstance(priority, (int, float)) or priority <= 0:
                return None
            backend_module = type(backend).__module__.casefold()
            backend_name = type(backend).__name__.casefold()
            if "plaintext" in backend_name or backend_module.startswith("keyrings.alt.file"):
                return None
        except Exception:
            return None
        return module


@asynccontextmanager
async def encrypted_sqlite_saver(
    database: str | Path,
    *,
    key_store: CheckpointKeyStore | None = None,
) -> AsyncGenerator[AsyncSqliteSaver, None]:
    """Open an AsyncSqliteSaver whose state and pending writes are encrypted."""
    path = Path(database)
    await asyncio.to_thread(_preflight_existing_database, path)
    store = key_store or SystemCheckpointKeyStore()
    key = await asyncio.to_thread(store.load_or_create, path)
    serde = EncryptedCheckpointSerializer(key)
    async with aiosqlite.connect(str(database)) as connection:
        yield AsyncSqliteSaver(connection, serde=serde)


def _preflight_existing_database(database: Path) -> None:
    """Reject plaintext or unknown LangGraph rows before key or saver setup."""
    try:
        if not database.is_file() or database.stat().st_size == 0:
            return
        database_uri = f"{database.resolve().as_uri()}?mode=ro"
        with sqlite3.connect(database_uri, uri=True) as connection:
            existing_tables = {
                row[0]
                for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
            }
            for table in ("checkpoints", "writes"):
                if table not in existing_tables:
                    continue
                columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
                if "type" not in columns:
                    raise CheckpointEncryptionError(_legacy_database_message())
                unsupported = connection.execute(
                    f"SELECT 1 FROM {table} WHERE type IS NULL OR type != ? LIMIT 1",
                    (_SERIALIZED_TYPE,),
                ).fetchone()
                if unsupported is not None:
                    raise CheckpointEncryptionError(_legacy_database_message())
    except CheckpointEncryptionError:
        raise
    except (OSError, sqlite3.Error, ValueError):
        raise CheckpointEncryptionError(
            "checkpoint database cannot be inspected safely; back it up and migrate or remove it"
        ) from None


def _legacy_database_message() -> str:
    return (
        "plaintext or unsupported checkpoint data is rejected; "
        "back up and migrate or remove the database"
    )


def _default_key_directory() -> Path:
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA")
        if not base:
            raise CheckpointKeyError("local application data directory is unavailable")
        return Path(base) / "BROWSKI" / "keys"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "BROWSKI" / "keys"
    base = os.environ.get("XDG_DATA_HOME")
    return (Path(base) if base else Path.home() / ".local" / "share") / "browski" / "keys"


def _ensure_private_directory(path: Path, *, create: bool) -> None:
    if os.name == "nt":
        raise CheckpointKeyError(
            "private file key fallback requires a supported owner-only filesystem"
        )
    absolute = path.absolute()
    for component in (absolute, *absolute.parents):
        try:
            info = component.lstat()
        except FileNotFoundError:
            continue
        except OSError:
            raise CheckpointKeyError(
                "checkpoint key directory cannot be inspected safely"
            ) from None
        if stat.S_ISLNK(info.st_mode):
            raise CheckpointKeyError("checkpoint key directory must not contain symlinks")
    if create:
        try:
            path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except OSError:
            raise CheckpointKeyError("private checkpoint key directory cannot be created") from None
    try:
        info = path.lstat()
    except OSError:
        if not create and not path.exists():
            return
        raise CheckpointKeyError("checkpoint key directory cannot be inspected safely") from None
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
        raise CheckpointKeyError("checkpoint key path must be a regular directory")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise CheckpointKeyError("checkpoint key directory must be owned by the current user")
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise CheckpointKeyError("checkpoint key directory permissions must be 0700 or stricter")


def _require_private_file_mode(info: os.stat_result) -> None:
    if stat.S_IMODE(info.st_mode) & 0o077:
        raise CheckpointKeyError("checkpoint key file permissions must be 0600 or stricter")


def _database_has_saved_data(database: Path) -> bool:
    for path in (
        database,
        Path(f"{database}-wal"),
        Path(f"{database}-shm"),
        Path(f"{database}-journal"),
    ):
        try:
            if path.stat().st_size > 0:
                return True
        except FileNotFoundError:
            continue
        except OSError:
            raise CheckpointKeyError(
                "checkpoint database state cannot be inspected safely"
            ) from None
    return False


def _encode_key(key: bytes) -> str:
    if len(key) != _KEY_BYTES:
        raise CheckpointKeyError("checkpoint key has an invalid length")
    return base64.urlsafe_b64encode(key).decode("ascii")


def _decode_key(value: object) -> bytes:
    if not isinstance(value, str):
        raise CheckpointKeyError("OS keyring checkpoint key has an invalid type")
    try:
        key = base64.b64decode(value.encode("ascii"), altchars=b"-_", validate=True)
    except (ValueError, UnicodeEncodeError):
        raise CheckpointKeyError("OS keyring checkpoint key is invalid") from None
    if len(key) != _KEY_BYTES:
        raise CheckpointKeyError("OS keyring checkpoint key has an invalid length")
    return key
