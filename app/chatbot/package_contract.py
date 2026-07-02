from __future__ import annotations

import ast
import hashlib
import json
import re
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath


BOT_KEY_RE = re.compile(r"^[a-z][a-z0-9]*(?:_[a-z0-9]+)*$")
FOLDER_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$")
REQUIRED_FILES = {"bot-package.json", "bot.py", "bot.md"}


@dataclass(frozen=True)
class PackageFile:
    path: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True)
class PackageValidationResult:
    """설치 가능한 봇 zip 패키지 검증 결과다."""

    manifest: dict
    sha256: str
    size_bytes: int
    files: list[PackageFile]
    data: bytes


def validate_package_bytes(data: bytes, max_bytes: int) -> PackageValidationResult:
    """봇 zip 계약을 검증한다.

    사용자 봇 코드는 실행하지 않고, 경로 탈출/UTF-8/manifest/Python syntax/sha256만
    검사한다.
    """

    size_bytes = len(data)
    if size_bytes > max(max_bytes, 1):
        raise ValueError("package too large")
    package_sha256 = hashlib.sha256(data).hexdigest()
    try:
        with zipfile.ZipFile(BytesIO(data)) as zf:
            infos = [info for info in zf.infolist() if not info.is_dir()]
            if not infos:
                raise ValueError("package is empty")
            names = [info.filename for info in infos]
            _validate_paths(names)
            missing = REQUIRED_FILES - set(names)
            if missing:
                raise ValueError(f"required file missing: {sorted(missing)[0]}")
            manifest = _read_json(zf, "bot-package.json")
            bot_py = _read_text(zf, "bot.py")
            _read_text(zf, "bot.md")
            ast.parse(bot_py, filename="bot.py")
            _validate_manifest(manifest, set(names))
            files = [
                PackageFile(
                    path=info.filename,
                    size_bytes=int(info.file_size),
                    sha256=hashlib.sha256(zf.read(info.filename)).hexdigest(),
                )
                for info in infos
            ]
    except zipfile.BadZipFile as exc:
        raise ValueError("package must be a zip file") from exc
    except SyntaxError as exc:
        raise ValueError(f"bot.py syntax error: {exc.msg}") from exc
    return PackageValidationResult(
        manifest=manifest,
        sha256=package_sha256,
        size_bytes=size_bytes,
        files=files,
        data=data,
    )


def manifest_for_export(
    *,
    bot_key: str,
    folder_name: str,
    name: str,
    version: str,
    description: str,
) -> dict:
    """로컬 봇 export용 bot-package.json 내용을 만든다."""

    return {
        "schemaVersion": 1,
        "botKey": bot_key,
        "folderName": folder_name,
        "name": name,
        "version": version,
        "description": description,
        "minRuntimeApi": "1.0",
        "files": ["bot-package.json", "bot.py", "bot.md"],
    }


def is_higher_semver(candidate: str, current: str | None) -> bool:
    if current is None:
        _parse_semver(candidate)
        return True
    return _parse_semver(candidate) > _parse_semver(current)


def _parse_semver(version: str) -> tuple[int, int, int]:
    if not SEMVER_RE.match(version):
        raise ValueError("version must be semver")
    major, minor, patch = version.split(".", 2)
    patch = re.split(r"[-+]", patch, maxsplit=1)[0]
    return int(major), int(minor), int(patch)


def _validate_paths(names: list[str]) -> None:
    for name in names:
        normalized = PurePosixPath(name)
        if name.startswith("/") or "\\" in name or any(part in ("", ".", "..") for part in normalized.parts):
            raise ValueError("package path escapes root")


def _read_text(zf: zipfile.ZipFile, name: str) -> str:
    try:
        return zf.read(name).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"{name} must be UTF-8") from exc


def _read_json(zf: zipfile.ZipFile, name: str) -> dict:
    try:
        value = json.loads(_read_text(zf, name))
    except json.JSONDecodeError as exc:
        raise ValueError(f"{name} must be valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    return value


def _validate_manifest(manifest: dict, actual_files: set[str]) -> None:
    required = ("schemaVersion", "botKey", "folderName", "name", "version", "description", "minRuntimeApi", "files")
    for key in required:
        if key not in manifest:
            raise ValueError(f"manifest field missing: {key}")
    if manifest["schemaVersion"] != 1:
        raise ValueError("unsupported schemaVersion")
    if not BOT_KEY_RE.match(str(manifest["botKey"])):
        raise ValueError("botKey must be snake_case")
    if not FOLDER_RE.match(str(manifest["folderName"])):
        raise ValueError("folderName must be kebab-case")
    _parse_semver(str(manifest["version"]))
    files = manifest["files"]
    if not isinstance(files, list) or not all(isinstance(item, str) for item in files):
        raise ValueError("manifest files must be string array")
    declared = set(files)
    if not REQUIRED_FILES.issubset(declared):
        raise ValueError("manifest files must include required files")
    if not declared.issubset(actual_files):
        raise ValueError("manifest files include missing path")
