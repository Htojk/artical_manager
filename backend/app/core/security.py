"""Local credential encryption and masking."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.models.system import Credential


class CredentialDecryptError(AppError):
    code = "credential_decrypt_failed"
    status_code = 500


def _derive_key(secret: str) -> bytes:
    digest = hashlib.sha256(secret.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


class CredentialCipher:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()

    def _key(self) -> bytes:
        if self.settings.secret_key:
            return _derive_key(self.settings.secret_key)
        key_file = self.settings.data_dir / "secret.key"
        if key_file.exists():
            return key_file.read_bytes().strip()
        key_file.parent.mkdir(parents=True, exist_ok=True)
        key = Fernet.generate_key()
        key_file.write_bytes(key)
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
        return key

    def encrypt(self, payload: dict[str, Any]) -> str:
        data = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return Fernet(self._key()).encrypt(data).decode("ascii")

    def decrypt(self, token: str) -> dict[str, Any]:
        try:
            data = Fernet(self._key()).decrypt(token.encode("ascii"))
        except (InvalidToken, ValueError) as exc:
            raise CredentialDecryptError("平台凭据无法解密，请重新保存凭据") from exc
        value = json.loads(data.decode("utf-8"))
        if not isinstance(value, dict):
            raise CredentialDecryptError("平台凭据格式无效")
        return value


class CredentialService:
    def __init__(self, session: Session, cipher: CredentialCipher | None = None) -> None:
        self.session = session
        self.cipher = cipher or CredentialCipher()

    def set(self, platform: str, payload: dict[str, Any]) -> None:
        record = self.session.scalar(select(Credential).where(Credential.platform == platform))
        if platform == "wechat" and record is not None and "cover_media_ids" not in payload:
            previous = self.cipher.decrypt(record.encrypted_payload)
            if payload.get("app_id") == previous.get("app_id") and previous.get("cover_media_ids"):
                payload = {**payload, "cover_media_ids": previous["cover_media_ids"]}
        encrypted = self.cipher.encrypt(payload)
        if record is None:
            record = Credential(platform=platform, encrypted_payload=encrypted)
            self.session.add(record)
        else:
            record.encrypted_payload = encrypted
        self.session.commit()

    def get(self, platform: str) -> dict[str, Any]:
        record = self.session.scalar(select(Credential).where(Credential.platform == platform))
        if record is None:
            return {}
        return self.cipher.decrypt(record.encrypted_payload)

    def masked(self, platform: str) -> dict[str, Any]:
        payload = self.get(platform)
        masked: dict[str, Any] = {}
        for key, value in payload.items():
            if key == "publish_mode" and value in {"draft", "publish"}:
                masked[key] = value
                continue
            if key == "cover_media_ids" and isinstance(value, dict):
                masked[key] = {name: mask_secret(media_id) for name, media_id in value.items()}
                continue
            if isinstance(value, str) and value:
                masked[key] = "***" + value[-4:] if len(value) > 4 else "***"
            else:
                masked[key] = value
        return masked

    def delete(self, platform: str) -> None:
        record = self.session.scalar(select(Credential).where(Credential.platform == platform))
        if record is not None:
            self.session.delete(record)
            self.session.commit()


def mask_secret(value: str | None) -> str:
    if not value:
        return ""
    return "***" + value[-4:] if len(value) > 4 else "***"
