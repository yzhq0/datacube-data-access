from __future__ import annotations

from contextlib import contextmanager
from hashlib import sha256
import os
from pathlib import Path
import shutil
from typing import Any, Iterable, Mapping
from uuid import uuid4

from .validation import write_json_atomic


def safe_text(value: Any, secrets: Iterable[str | None]) -> str:
    message = str(value)
    for secret in secrets:
        if secret:
            message = message.replace(str(secret), "<redacted>")
    return message


def redact_known_values(value: Any, secrets: Iterable[str | None]) -> Any:
    known = [str(secret) for secret in secrets if secret]
    if isinstance(value, Mapping):
        return {
            str(key): redact_known_values(item, known)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact_known_values(item, known) for item in value]
    if isinstance(value, tuple):
        return [redact_known_values(item, known) for item in value]
    if isinstance(value, str):
        for secret in known:
            value = value.replace(secret, "<redacted>")
    return value


def write_output(frame: Any, path: Path, output_format: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if output_format == "csv":
        frame.to_csv(path, index=False, encoding="utf-8-sig")
    elif output_format == "json":
        path.write_text(
            frame.to_json(orient="records", force_ascii=False, indent=2),
            encoding="utf-8",
        )
    elif output_format == "parquet":
        frame.to_parquet(path, index=False)
    else:
        raise ValueError(f"unsupported output format: {output_format}")


def stage_output(frame: Any, path: Path, output_format: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    suffix = {"csv": ".csv", "json": ".json", "parquet": ".parquet"}[output_format]
    staged = path.parent / f".{path.name}.{uuid4().hex}.staged{suffix}"
    write_output(frame, staged, output_format)
    with staged.open("rb") as handle:
        os.fsync(handle.fileno())
    return staged


def publish_exploratory(frame: Any, path: Path, output_format: str) -> None:
    staged = stage_output(frame, path, output_format)
    try:
        os.replace(staged, path)
        _fsync_parent(path)
    finally:
        if staged.exists():
            staged.unlink()


def _fsync_parent(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    try:
        descriptor = os.open(str(path.parent), flags)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def _publication_lock_paths(output_path: Path, manifest_path: Path) -> list[Path]:
    candidates = {
        output_path.parent
        / (
            f".{output_path.name}.publish-"
            f"{sha256(str(output_path.resolve()).encode()).hexdigest()[:12]}.lock"
        ),
        manifest_path.parent
        / (
            f".{manifest_path.name}.publish-"
            f"{sha256(str(manifest_path.resolve()).encode()).hexdigest()[:12]}.lock"
        ),
    }
    return sorted(candidates, key=lambda path: str(path.resolve()))


@contextmanager
def publication_lock(output_path: Path, manifest_path: Path):
    lock_paths = _publication_lock_paths(output_path, manifest_path)
    acquired: list[tuple[int, Path]] = []
    try:
        for lock_path in lock_paths:
            lock_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                descriptor = os.open(
                    lock_path,
                    os.O_CREAT | os.O_EXCL | os.O_WRONLY,
                    0o600,
                )
            except FileExistsError as exc:
                raise RuntimeError(
                    f"dataset publication lock already exists: {lock_path}"
                ) from exc
            acquired.append((descriptor, lock_path))
            os.write(descriptor, f"pid={os.getpid()}\n".encode("ascii"))
        yield
    finally:
        for descriptor, lock_path in reversed(acquired):
            try:
                os.close(descriptor)
            finally:
                try:
                    lock_path.unlink()
                except FileNotFoundError:
                    pass


def commit_staged_dataset(
    *,
    staged_output: Path,
    output_path: Path,
    manifest_path: Path,
    final_manifest: Mapping[str, Any],
) -> None:
    with publication_lock(output_path, manifest_path):
        transaction_id = uuid4().hex
        output_backup = output_path.parent / f".{output_path.name}.{transaction_id}.bak"
        manifest_backup = (
            manifest_path.parent / f".{manifest_path.name}.{transaction_id}.bak"
        )
        output_existed = output_path.is_file()
        manifest_existed = manifest_path.is_file()
        output_committed = False
        output_backup_ready = False
        manifest_backup_ready = False
        try:
            if output_existed:
                shutil.copy2(output_path, output_backup)
                output_backup_ready = True
            if manifest_existed:
                manifest_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(manifest_path, manifest_backup)
                manifest_backup_ready = True

            prepared = dict(final_manifest)
            prepared["publication_state"] = "prepared"
            prepared["output_published"] = False
            prepared["publishable"] = False
            complete = dict(final_manifest)
            complete["publication_state"] = "complete"
            write_json_atomic(manifest_path, prepared)
            os.replace(staged_output, output_path)
            _fsync_parent(output_path)
            output_committed = True
            write_json_atomic(manifest_path, complete)
        except BaseException:
            if output_committed:
                if output_existed and output_backup_ready:
                    os.replace(output_backup, output_path)
                    _fsync_parent(output_path)
                elif output_path.exists():
                    output_path.unlink()
                    _fsync_parent(output_path)
            if manifest_existed and manifest_backup_ready:
                os.replace(manifest_backup, manifest_path)
            raise
        finally:
            for temporary in (staged_output, output_backup, manifest_backup):
                try:
                    if temporary.exists():
                        temporary.unlink()
                except OSError:
                    pass


def write_withheld_manifest(
    *,
    output_path: Path,
    manifest_path: Path,
    payload: Mapping[str, Any],
) -> None:
    with publication_lock(output_path, manifest_path):
        write_json_atomic(manifest_path, payload)
