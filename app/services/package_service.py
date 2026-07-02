from __future__ import annotations

import json
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path

from app import repository
from app.chatbot.package_contract import (
    PackageValidationResult,
    is_higher_semver,
    manifest_for_export,
    validate_package_bytes,
)
from app.config import get_settings


@dataclass(frozen=True)
class PackageInstallResult:
    """로컬 봇 패키지 설치/업데이트 결과다."""

    ok: bool
    botKey: str
    folderName: str
    version: str
    packageSha256: str
    installedPath: str
    updated: bool
    reloadOk: bool | None = None
    reloadLoaded: int | None = None
    error: str | None = None


class PackageService:
    """로컬 챗봇 패키지 export/install/update를 담당한다."""

    def export_package(self, bot_key: str) -> tuple[bytes, str, str]:
        module = repository.get_chatbot_module(bot_key)
        file_row = repository.get_chatbot_module_file_by_key(bot_key)
        if module is None or file_row is None or file_row["status"] != "loaded":
            raise ValueError("bot not found")
        bot_py = Path(file_row["path"]).resolve()
        bot_dir = bot_py.parent
        bot_md = bot_dir / "bot.md"
        if not bot_py.exists() or not bot_md.exists():
            raise ValueError("bot package files missing")
        manifest = manifest_for_export(
            bot_key=bot_key,
            folder_name=bot_dir.name,
            name=str(module["name"]),
            version=str(module["version"]),
            description="",
        )
        payload = BytesIO()
        with zipfile.ZipFile(payload, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("bot-package.json", json.dumps(manifest, ensure_ascii=False, sort_keys=True))
            zf.write(bot_py, "bot.py")
            zf.write(bot_md, "bot.md")
        data = payload.getvalue()
        validated = validate_package_bytes(data, get_settings().chatbot_max_bot_file_bytes * 4)
        return data, validated.sha256, f"{bot_key}-{manifest['version']}.zip"

    def install_package(
        self,
        data: bytes,
        *,
        marketplace_bot_id: str | None = None,
        marketplace_base_url: str | None = None,
        allow_update: bool = False,
        expected_bot_key: str | None = None,
        reload_callback=None,
    ) -> PackageInstallResult:
        validated = validate_package_bytes(data, get_settings().chatbot_max_bot_file_bytes * 4)
        manifest = validated.manifest
        bot_key = str(manifest["botKey"])
        if expected_bot_key is not None and bot_key != expected_bot_key:
            raise ValueError("package botKey does not match path")
        folder_name = str(manifest["folderName"])
        version = str(manifest["version"])
        bot_root = self._bot_root()
        target = (bot_root / folder_name).resolve()
        if not self._is_relative_to(target, bot_root.resolve()):
            raise ValueError("target path escapes bot directory")

        install_row = repository.get_marketplace_install(bot_key)
        existing_module = repository.get_chatbot_module(bot_key)
        target_exists = target.exists()
        if target_exists or existing_module is not None:
            if install_row is None:
                raise ValueError("local botKey collision")
            if not allow_update:
                raise ValueError("bot already installed")
            if marketplace_bot_id and install_row["marketplace_bot_id"] not in (None, marketplace_bot_id):
                raise ValueError("marketplace bot mismatch")
            if not is_higher_semver(version, install_row["version"]):
                raise ValueError("version must be higher than installed version")

        backup = None
        if target.exists():
            backup = target.with_name(f".{target.name}.backup")
            if backup.exists():
                shutil.rmtree(backup)
            target.rename(backup)
        try:
            self._extract_to_target(validated, target)
            reload_loaded = None
            reload_ok = None
            if reload_callback is not None:
                reload_loaded = int(reload_callback())
                file_row = repository.get_chatbot_module_file_by_key(bot_key)
                reload_ok = bool(file_row is not None and file_row["status"] == "loaded")
                if not reload_ok:
                    raise RuntimeError("bot reload failed")
            repository.upsert_marketplace_install(
                bot_key=bot_key,
                marketplace_bot_id=marketplace_bot_id,
                marketplace_base_url=marketplace_base_url,
                package_sha256=validated.sha256,
                version=version,
                folder_name=folder_name,
            )
            if backup is not None and backup.exists():
                shutil.rmtree(backup)
            return PackageInstallResult(
                ok=True,
                botKey=bot_key,
                folderName=folder_name,
                version=version,
                packageSha256=validated.sha256,
                installedPath=str(target),
                updated=install_row is not None,
                reloadOk=reload_ok,
                reloadLoaded=reload_loaded,
            )
        except Exception:
            if target.exists():
                shutil.rmtree(target)
            if backup is not None and backup.exists():
                backup.rename(target)
                if reload_callback is not None:
                    reload_callback()
            raise

    def _extract_to_target(self, package: PackageValidationResult, target: Path) -> None:
        target.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix="bot-install-", dir=str(target.parent)) as tmp:
            tmp_path = Path(tmp)
            with zipfile.ZipFile(BytesIO(package.data)) as zf:
                zf.extractall(tmp_path)
            (tmp_path / "bot-package.json").unlink(missing_ok=True)
            target_tmp = target.with_name(f".{target.name}.new")
            if target_tmp.exists():
                shutil.rmtree(target_tmp)
            shutil.move(str(tmp_path), str(target_tmp))
            target_tmp.rename(target)

    def _bot_root(self) -> Path:
        path = Path(get_settings().chatbot_bot_dir)
        if path.exists():
            return path
        if str(path) == "app/bots":
            return Path(__file__).resolve().parents[1] / "bots"
        return path

    @staticmethod
    def _is_relative_to(path: Path, base: Path) -> bool:
        try:
            path.relative_to(base)
            return True
        except ValueError:
            return False
