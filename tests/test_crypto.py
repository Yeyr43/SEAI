"""
加密模块单元测试
"""
import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from seai.core.crypto import (
    encrypt_value, decrypt_value, is_encrypted,
    encrypt_sensitive_config, decrypt_sensitive_config,
)


class TestCrypto:
    def test_encrypt_decrypt_roundtrip(self):
        plaintext = "sk-test-api-key-12345"
        encrypted = encrypt_value(plaintext)
        assert encrypted != plaintext
        assert is_encrypted(encrypted)
        decrypted = decrypt_value(encrypted)
        assert decrypted == plaintext

    def test_decrypt_plaintext_passthrough(self):
        plaintext = "not-encrypted-value"
        result = decrypt_value(plaintext)
        assert result == plaintext

    def test_is_encrypted(self):
        assert is_encrypted("enc:abc123")
        assert not is_encrypted("plain-text")
        assert not is_encrypted("")

    def test_encrypt_sensitive_config(self):
        config = {
            "api_key": "secret-key-123",
            "github_token": "ghp_token_456",
            "model": "gpt-4",
            "endpoints": [
                {"name": "ep1", "api_key": "key1"},
                {"name": "ep2", "api_key": "key2"},
            ],
        }
        encrypted = encrypt_sensitive_config(config)
        assert is_encrypted(encrypted["api_key"])
        assert is_encrypted(encrypted["github_token"])
        assert encrypted["model"] == "gpt-4"
        assert is_encrypted(encrypted["endpoints"][0]["api_key"])
        assert is_encrypted(encrypted["endpoints"][1]["api_key"])

    def test_decrypt_sensitive_config(self):
        config = {
            "api_key": "secret-key-123",
            "github_token": "ghp_token_456",
            "model": "gpt-4",
        }
        encrypted = encrypt_sensitive_config(config)
        decrypted = decrypt_sensitive_config(encrypted)
        assert decrypted["api_key"] == "secret-key-123"
        assert decrypted["github_token"] == "ghp_token_456"
        assert decrypted["model"] == "gpt-4"

    def test_empty_string(self):
        encrypted = encrypt_value("")
        assert is_encrypted(encrypted)
        assert decrypt_value(encrypted) == ""

    def test_special_characters(self):
        plaintext = "key!@#$%^&*()_+-=[]{}|;':\",./<>?"
        encrypted = encrypt_value(plaintext)
        assert decrypt_value(encrypted) == plaintext

    def test_unicode_text(self):
        plaintext = "密钥测试🔑中文"
        encrypted = encrypt_value(plaintext)
        assert decrypt_value(encrypted) == plaintext