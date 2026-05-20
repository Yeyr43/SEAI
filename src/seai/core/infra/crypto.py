"""
SEAI 加密工具模块
提供敏感配置项的加密存储，使用 Windows DPAPI 或 cryptography Fernet
"""
import os
import sys
import base64
import hashlib
from pathlib import Path
from typing import Optional

_ENCRYPTION_KEY_PATH: Optional[Path] = None
_FERNET: Optional[object] = None


def _get_key_path() -> Path:
    global _ENCRYPTION_KEY_PATH
    if _ENCRYPTION_KEY_PATH is not None:
        return _ENCRYPTION_KEY_PATH
    data_dir = Path(os.environ.get("SEAI_DATA", str(Path.cwd().parent / "data")))
    _ENCRYPTION_KEY_PATH = data_dir / ".seai_key"
    return _ENCRYPTION_KEY_PATH


def _derive_key(master_password: str, salt: bytes = None) -> tuple:
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.backends import default_backend
    if salt is None:
        salt = os.urandom(16)
    kdf = PBKDF2(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480000,
        backend=default_backend(),
    )
    key = base64.urlsafe_b64encode(kdf.derive(master_password.encode()))
    return key, salt


def _decrypt_key_ecb(data: bytes, machine_id: bytes) -> Optional[bytes]:
    """尝试用 ECB 解密旧格式密钥（向后兼容）"""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        cipher = Cipher(algorithms.AES(machine_id), modes.ECB(), backend=default_backend())
        decryptor = cipher.decryptor()
        padded = decryptor.update(data) + decryptor.finalize()
        pad_len = padded[-1]
        return padded[:32]
    except Exception:
        return None


def _encrypt_key_gcm(plain_key: bytes, machine_id: bytes) -> tuple:
    """用 AES-GCM 加密密钥，返回 (nonce, ciphertext)"""
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.backends import default_backend
    nonce = os.urandom(12)
    cipher = Cipher(algorithms.AES(machine_id), modes.GCM(nonce), backend=default_backend())
    encryptor = cipher.encryptor()
    ciphertext = encryptor.update(plain_key) + encryptor.finalize()
    return nonce, ciphertext + encryptor.tag


def _decrypt_key_gcm(data: bytes, nonce: bytes, machine_id: bytes, tag: bytes) -> Optional[bytes]:
    """用 AES-GCM 解密密钥"""
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
        from cryptography.hazmat.backends import default_backend
        cipher = Cipher(algorithms.AES(machine_id), modes.GCM(nonce, tag), backend=default_backend())
        decryptor = cipher.decryptor()
        return decryptor.update(data) + decryptor.finalize()
    except Exception:
        return None


def _get_fernet() -> Optional[object]:
    global _FERNET
    if _FERNET is not None:
        return _FERNET

    key_path = _get_key_path()
    machine_id = hashlib.sha256(
        (os.environ.get("COMPUTERNAME", "") + os.environ.get("USERNAME", "")).encode()
    ).digest()[:16]

    if key_path.exists():
        try:
            data = key_path.read_bytes()
            salt = data[:16]
            rest = data[16:]

            # 检测新格式 (salt + 0x01 + nonce(12) + ciphertext+tag)
            if len(rest) >= 13 and rest[0] == 0x01:
                nonce = rest[1:13]
                ct_with_tag = rest[13:]
                tag = ct_with_tag[-16:]
                ciphertext = ct_with_tag[:-16]
                key = _decrypt_key_gcm(ciphertext, nonce, machine_id, tag)
            else:
                # 旧格式 ECB 降级
                key = _decrypt_key_ecb(rest, machine_id)

            if key:
                from cryptography.fernet import Fernet
                _FERNET = Fernet(base64.urlsafe_b64encode(key))
                return _FERNET
        except Exception:
            pass

    # 生成新密钥（GCM 格式）
    try:
        from cryptography.fernet import Fernet
        key = Fernet.generate_key()
        raw_key = base64.urlsafe_b64decode(key)

        nonce, ct_with_tag = _encrypt_key_gcm(raw_key, machine_id)

        key_path.parent.mkdir(parents=True, exist_ok=True)
        # 格式: salt(16) + 0x01 + nonce(12) + ciphertext(32) + tag(16)
        key_path.write_bytes(os.urandom(16) + b'\x01' + nonce + ct_with_tag)

        _FERNET = Fernet(key)
        return _FERNET
    except ImportError:
        pass
    except Exception:
        pass

    return None


def encrypt_value(plaintext: str) -> str:
    fernet = _get_fernet()
    if fernet is None:
        return _fallback_encrypt(plaintext)
    return "enc:" + fernet.encrypt(plaintext.encode()).decode()


def decrypt_value(ciphertext: str) -> str:
    if not ciphertext.startswith("enc:"):
        return ciphertext
    fernet = _get_fernet()
    if fernet is None:
        return _fallback_decrypt(ciphertext[4:])
    try:
        return fernet.decrypt(ciphertext[4:].encode()).decode()
    except Exception:
        return ciphertext


def _fallback_encrypt(plaintext: str) -> str:
    key = hashlib.sha256(
        (os.environ.get("COMPUTERNAME", "") + os.environ.get("USERNAME", "")).encode()
    ).digest()
    result = bytearray()
    for i, ch in enumerate(plaintext.encode()):
        result.append(ch ^ key[i % len(key)])
    return "enc:" + base64.urlsafe_b64encode(bytes(result)).decode()


def _fallback_decrypt(ciphertext: str) -> str:
    try:
        key = hashlib.sha256(
            (os.environ.get("COMPUTERNAME", "") + os.environ.get("USERNAME", "")).encode()
        ).digest()
        data = base64.urlsafe_b64decode(ciphertext.encode())
        result = bytearray()
        for i, ch in enumerate(data):
            result.append(ch ^ key[i % len(key)])
        return bytes(result).decode()
    except Exception:
        return ciphertext


def is_encrypted(value: str) -> bool:
    return value.startswith("enc:")


def encrypt_sensitive_config(config: dict, sensitive_keys: list = None) -> dict:
    if sensitive_keys is None:
        sensitive_keys = ["api_key", "github_token"]
    result = {}
    for key, value in config.items():
        if key in sensitive_keys and isinstance(value, str) and not is_encrypted(value):
            result[key] = encrypt_value(value)
        elif isinstance(value, dict):
            result[key] = encrypt_sensitive_config(value, sensitive_keys)
        elif isinstance(value, list):
            result[key] = [
                encrypt_sensitive_config(item, sensitive_keys) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result


def decrypt_sensitive_config(config: dict, sensitive_keys: list = None) -> dict:
    if sensitive_keys is None:
        sensitive_keys = ["api_key", "github_token"]
    result = {}
    for key, value in config.items():
        if key in sensitive_keys and isinstance(value, str) and is_encrypted(value):
            result[key] = decrypt_value(value)
        elif isinstance(value, dict):
            result[key] = decrypt_sensitive_config(value, sensitive_keys)
        elif isinstance(value, list):
            result[key] = [
                decrypt_sensitive_config(item, sensitive_keys) if isinstance(item, dict) else item
                for item in value
            ]
        else:
            result[key] = value
    return result