from __future__ import annotations

import sqlite3
import stat
from pathlib import Path
from typing import Any, cast

import aiosqlite
import pytest
from langgraph.checkpoint.base import empty_checkpoint

from browser_agent.persistence.checkpoint_cipher import (
    CheckpointEncryptionError,
    CheckpointKeyError,
    EncryptedCheckpointSerializer,
    PrivateFileCheckpointKeyStore,
    SystemCheckpointKeyStore,
    encrypted_sqlite_saver,
)


class FixedCheckpointKeyStore:
    def __init__(self, key: bytes) -> None:
        self.key = key
        self.called = False

    def load_or_create(self, database: Path) -> bytes:
        _ = database
        self.called = True
        return self.key


class FakeKeyring:
    class Backend:
        priority = 1

    def __init__(self) -> None:
        self.password: str | None = None

    def get_keyring(self) -> Backend:
        return self.Backend()

    def get_password(self, service_name: str, username: str) -> str | None:
        _ = service_name, username
        return self.password

    def set_password(self, service_name: str, username: str, password: str) -> None:
        _ = service_name, username
        self.password = password


def test_serializer_round_trips_and_rejects_plaintext_values() -> None:
    serializer = EncryptedCheckpointSerializer(b"k" * 32)
    marker = "checkpoint-user-secret-marker-5481"

    serialized = serializer.dumps_typed({"task": marker, "count": 3})
    repeated = serializer.dumps_typed({"task": marker, "count": 3})

    assert marker.encode() not in serialized[1]
    assert serialized[1] != repeated[1]
    assert serializer.loads_typed(serialized) == {"task": marker, "count": 3}
    with pytest.raises(CheckpointEncryptionError, match="plaintext"):
        serializer.loads_typed(("msgpack", b"legacy plaintext"))


def test_serializer_rejects_tampered_data_and_wrong_keys() -> None:
    serializer = EncryptedCheckpointSerializer(b"a" * 32)
    serialized_type, ciphertext = serializer.dumps_typed({"state": "private"})
    tampered = ciphertext[:-1] + bytes([ciphertext[-1] ^ 1])

    with pytest.raises(CheckpointEncryptionError, match="authentication failed"):
        serializer.loads_typed((serialized_type, tampered))
    with pytest.raises(CheckpointEncryptionError, match="authentication failed"):
        EncryptedCheckpointSerializer(b"b" * 32).loads_typed((serialized_type, ciphertext))


@pytest.mark.asyncio
@pytest.mark.parametrize("table", ["checkpoints", "writes"])
async def test_existing_plaintext_rows_are_rejected_before_saver_setup_and_preserved(
    tmp_path: Path,
    table: str,
) -> None:
    database = tmp_path / "legacy.sqlite"
    marker = "legacy-checkpoint-must-remain-untouched"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "CREATE TABLE checkpoints (thread_id TEXT, checkpoint_ns TEXT, "
            "checkpoint_id TEXT, parent_checkpoint_id TEXT, type TEXT, "
            "checkpoint BLOB, metadata BLOB)"
        )
        connection.execute(
            "CREATE TABLE writes (thread_id TEXT, checkpoint_ns TEXT, "
            "checkpoint_id TEXT, task_id TEXT, idx INTEGER, channel TEXT, "
            "type TEXT, value BLOB)"
        )
        if table == "checkpoints":
            connection.execute(
                "INSERT INTO checkpoints VALUES (?, ?, ?, ?, ?, ?, ?)",
                ("old-thread", "", "old-checkpoint", None, "msgpack", marker, b"{}"),
            )
        else:
            connection.execute(
                "INSERT INTO writes VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                ("old-thread", "", "old-checkpoint", "old-task", 0, "result", "msgpack", marker),
            )
    original_bytes = database.read_bytes()
    key_store = FixedCheckpointKeyStore(b"k" * 32)
    yielded = False

    with pytest.raises(CheckpointEncryptionError, match="back up and migrate or remove"):
        async with encrypted_sqlite_saver(database, key_store=key_store):
            yielded = True

    assert not yielded
    assert not key_store.called
    assert database.read_bytes() == original_bytes


@pytest.mark.asyncio
async def test_sqlite_checkpoint_and_pending_writes_are_encrypted(tmp_path: Path) -> None:
    database = tmp_path / "encrypted.sqlite"
    marker = "raw-checkpoint-and-write-secret-8472"
    key = b"z" * 32

    async with encrypted_sqlite_saver(
        database,
        key_store=FixedCheckpointKeyStore(key),
    ) as saver:
        config: Any = {"configurable": {"thread_id": "safe-run-id", "checkpoint_ns": ""}}
        checkpoint = empty_checkpoint()
        checkpoint["channel_values"] = {"task": marker}
        saved_config = await saver.aput(
            config,
            checkpoint,
            {"source": "input", "step": 0},
            {"task": 1},
        )
        await saver.aput_writes(
            saved_config,
            [("private_write", {"result": marker})],
            task_id="task-1",
        )

        restored = await saver.aget_tuple(saved_config)
        assert restored is not None
        assert restored.pending_writes is not None
        assert restored.checkpoint["channel_values"]["task"] == marker
        assert restored.pending_writes[0][2] == {"result": marker}

    raw_database = database.read_bytes()
    assert marker.encode() not in raw_database

    async with aiosqlite.connect(str(database)) as connection:
        checkpoint_rows = cast(
            list[tuple[str, bytes, bytes]],
            list(
                await connection.execute_fetchall(
                    "SELECT type, checkpoint, metadata FROM checkpoints"
                )
            ),
        )
        write_rows = cast(
            list[tuple[str, bytes]],
            list(await connection.execute_fetchall("SELECT type, value FROM writes")),
        )
    assert checkpoint_rows
    assert write_rows
    assert checkpoint_rows[0][0].startswith("browski-checkpoint-v1+")
    assert write_rows[0][0].startswith("browski-checkpoint-v1+")
    assert marker.encode() not in checkpoint_rows[0][2]


def test_file_key_is_owner_only_and_stable_across_store_instances(tmp_path: Path) -> None:
    database = tmp_path / "checkpoints.sqlite"
    key_directory = tmp_path / "private-keys"
    first = PrivateFileCheckpointKeyStore(key_directory)

    key = first.load_or_create(database)
    second_key = PrivateFileCheckpointKeyStore(key_directory).load_or_create(database)

    key_file = key_directory / "checkpoint-encryption-v1.key"
    assert key == second_key
    assert len(key) == 32
    assert stat.S_IMODE(key_directory.stat().st_mode) == 0o700
    assert stat.S_IMODE(key_file.stat().st_mode) == 0o600


def test_file_key_store_rejects_symlinks_and_unsafe_permissions(tmp_path: Path) -> None:
    database = tmp_path / "checkpoints.sqlite"
    safe_directory = tmp_path / "safe"
    safe_directory.mkdir(mode=0o700)
    symlink_directory = tmp_path / "linked"
    symlink_directory.symlink_to(safe_directory, target_is_directory=True)

    with pytest.raises(CheckpointKeyError, match="symlinks"):
        PrivateFileCheckpointKeyStore(symlink_directory).load_or_create(database)

    unsafe_directory = tmp_path / "unsafe"
    unsafe_directory.mkdir(mode=0o700)
    unsafe_directory.chmod(0o755)
    with pytest.raises(CheckpointKeyError, match="permissions"):
        PrivateFileCheckpointKeyStore(unsafe_directory).load_or_create(database)

    file_directory = tmp_path / "private-file-directory"
    file_directory.mkdir(mode=0o700)
    target_key = tmp_path / "outside-key"
    target_key.write_bytes(b"x" * 32)
    target_key.chmod(0o600)
    (file_directory / "checkpoint-encryption-v1.key").symlink_to(target_key)
    with pytest.raises(CheckpointKeyError, match="non-symlink"):
        PrivateFileCheckpointKeyStore(file_directory).load_or_create(database)


def test_missing_key_does_not_replace_key_for_nonempty_database(tmp_path: Path) -> None:
    database = tmp_path / "checkpoints.sqlite"
    database.write_bytes(b"existing encrypted database")
    key_store = PrivateFileCheckpointKeyStore(tmp_path / "keys")

    with pytest.raises(CheckpointKeyError, match="non-empty database"):
        key_store.load_or_create(database)

    assert not (tmp_path / "keys" / "checkpoint-encryption-v1.key").exists()


def test_missing_key_does_not_ignore_nonempty_wal_sidecar(tmp_path: Path) -> None:
    database = tmp_path / "checkpoints.sqlite"
    Path(f"{database}-wal").write_bytes(b"existing uncheckpointed state")
    key_store = PrivateFileCheckpointKeyStore(tmp_path / "keys")

    with pytest.raises(CheckpointKeyError, match="non-empty database"):
        key_store.load_or_create(database)

    assert not (tmp_path / "keys" / "checkpoint-encryption-v1.key").exists()


def test_keyring_key_is_preferred_and_shared_across_store_instances(tmp_path: Path) -> None:
    database = tmp_path / "checkpoints.sqlite"
    keyring = FakeKeyring()
    fallback = PrivateFileCheckpointKeyStore(tmp_path / "fallback")
    first = SystemCheckpointKeyStore(keyring_module=keyring, fallback=fallback)

    key = first.load_or_create(database)
    second_key = SystemCheckpointKeyStore(
        keyring_module=keyring,
        fallback=PrivateFileCheckpointKeyStore(tmp_path / "fallback"),
    ).load_or_create(database)

    assert key == second_key
    assert keyring.password is not None
    assert not (tmp_path / "fallback" / "checkpoint-encryption-v1.key").exists()


def test_keyring_and_fallback_key_mismatch_fails_closed(tmp_path: Path) -> None:
    import base64

    database = tmp_path / "checkpoints.sqlite"
    keyring = FakeKeyring()
    keyring.password = base64.urlsafe_b64encode(b"a" * 32).decode("ascii")
    fallback = PrivateFileCheckpointKeyStore(tmp_path / "fallback")
    fallback.load_or_create(database)

    with pytest.raises(CheckpointKeyError, match="do not match"):
        SystemCheckpointKeyStore(keyring_module=keyring, fallback=fallback).load_or_create(database)
