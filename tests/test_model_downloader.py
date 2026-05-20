"""
model_downloader 单元测试
覆盖：本地缓存检查、镜像站连通性检测、重试机制、降级策略、用户提示
"""
import os
import sys
import time
import socket
import tempfile
import json
from pathlib import Path
from unittest.mock import patch, MagicMock, PropertyMock
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from seai.core.model_downloader import (
    check_local_model,
    get_local_model_info,
    check_mirror_connectivity,
    find_working_mirror,
    download_with_retry,
    load_embedding_model,
    get_user_guidance,
    HF_MIRRORS,
    DEFAULT_LOCAL_DIR,
    DEFAULT_MODEL_NAME,
)


class TestLocalModelCheck:

    def test_check_local_model_not_exists(self, tmp_path):
        model_dir = tmp_path / "nonexistent_model"
        assert check_local_model(model_dir) is False

    def test_check_local_model_empty_dir(self, tmp_path):
        model_dir = tmp_path / "empty_model"
        model_dir.mkdir()
        assert check_local_model(model_dir) is False

    def test_check_local_model_missing_config(self, tmp_path):
        model_dir = tmp_path / "partial_model"
        model_dir.mkdir()
        (model_dir / "tokenizer_config.json").write_text("{}")
        (model_dir / "model.safetensors").write_bytes(b"\x00" * 100)
        assert check_local_model(model_dir) is False

    def test_check_local_model_missing_weights(self, tmp_path):
        model_dir = tmp_path / "no_weights_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "tokenizer_config.json").write_text("{}")
        assert check_local_model(model_dir) is False

    def test_check_local_model_complete_safetensors(self, tmp_path):
        model_dir = tmp_path / "complete_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text('{"model_type": "bert"}')
        (model_dir / "tokenizer_config.json").write_text("{}")
        (model_dir / "model.safetensors").write_bytes(b"\x00" * 100)
        assert check_local_model(model_dir) is True

    def test_check_local_model_complete_pytorch(self, tmp_path):
        model_dir = tmp_path / "pytorch_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "tokenizer_config.json").write_text("{}")
        (model_dir / "pytorch_model.bin").write_bytes(b"\x00" * 100)
        assert check_local_model(model_dir) is True

    def test_get_local_model_info(self, tmp_path):
        model_dir = tmp_path / "info_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "tokenizer_config.json").write_text("{}")
        (model_dir / "model.safetensors").write_bytes(b"\x00" * 1024 * 1024)

        info = get_local_model_info(model_dir)
        assert info["exists"] is True
        assert info["size_mb"] > 0
        assert len(info["files"]) == 3

    def test_get_local_model_info_not_exists(self, tmp_path):
        info = get_local_model_info(tmp_path / "nonexistent")
        assert info["exists"] is False
        assert info["size_mb"] == 0


class TestMirrorConnectivity:

    def test_check_mirror_connectivity_success(self):
        with patch("seai.core.model_downloader.urlopen") as mock_urlopen:
            mock_resp = MagicMock()
            mock_resp.read.return_value = b"ok"
            mock_urlopen.return_value = mock_resp

            ok, err = check_mirror_connectivity("https://hf-mirror.com")
            assert ok is True
            assert err == ""

    def test_check_mirror_connectivity_timeout(self):
        with patch("seai.core.model_downloader.urlopen") as mock_urlopen:
            mock_urlopen.side_effect = socket.timeout("timed out")

            ok, err = check_mirror_connectivity("https://hf-mirror.com")
            assert ok is False
            assert "超时" in err

    def test_check_mirror_connectivity_unreachable(self):
        with patch("seai.core.model_downloader.urlopen") as mock_urlopen:
            from urllib.error import URLError
            mock_urlopen.side_effect = URLError("no route to host")

            ok, err = check_mirror_connectivity("https://hf-mirror.com")
            assert ok is False
            assert "不可达" in err

    def test_find_working_mirror_first_works(self):
        with patch("seai.core.model_downloader.check_mirror_connectivity") as mock_check:
            mock_check.return_value = (True, "")
            mirror = find_working_mirror(["https://mirror1.com", "https://mirror2.com"])
            assert mirror == "https://mirror1.com"

    def test_find_working_mirror_second_works(self):
        with patch("seai.core.model_downloader.check_mirror_connectivity") as mock_check:
            mock_check.side_effect = [(False, "timeout"), (True, "")]
            mirror = find_working_mirror(["https://mirror1.com", "https://mirror2.com"])
            assert mirror == "https://mirror2.com"

    def test_find_working_mirror_all_fail(self):
        with patch("seai.core.model_downloader.check_mirror_connectivity") as mock_check:
            mock_check.return_value = (False, "timeout")
            mirror = find_working_mirror(["https://mirror1.com", "https://mirror2.com"])
            assert mirror is None


class TestDownloadWithRetry:

    def test_download_local_cache_hit(self, tmp_path):
        model_dir = tmp_path / "cached_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "tokenizer_config.json").write_text("{}")
        (model_dir / "model.safetensors").write_bytes(b"\x00" * 100)

        callbacks = []
        success, msg, path = download_with_retry(
            local_dir=model_dir,
            progress_callback=lambda s, m: callbacks.append((s, m)),
        )
        assert success is True
        assert path == model_dir
        assert callbacks[0][0] == "cache_hit"

    def test_download_all_mirrors_fail_no_cache(self, tmp_path):
        model_dir = tmp_path / "no_cache_model"

        with patch("seai.core.model_downloader.find_working_mirror") as mock_find:
            mock_find.return_value = None

            callbacks = []
            success, msg, path = download_with_retry(
                local_dir=model_dir,
                progress_callback=lambda s, m: callbacks.append((s, m)),
            )
            assert success is False
            assert "不可达" in msg
            assert path is None

    def test_download_all_mirrors_fail_with_cache(self, tmp_path):
        model_dir = tmp_path / "fallback_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "tokenizer_config.json").write_text("{}")
        (model_dir / "model.safetensors").write_bytes(b"\x00" * 100)

        with patch("seai.core.model_downloader.find_working_mirror") as mock_find:
            mock_find.return_value = None

            success, msg, path = download_with_retry(local_dir=model_dir)
            assert success is True
            assert path == model_dir

    def test_download_retry_exhausted(self, tmp_path):
        model_dir = tmp_path / "retry_fail_model"

        with patch("seai.core.model_downloader.find_working_mirror") as mock_find:
            mock_find.return_value = "https://hf-mirror.com"

            with patch("seai.core.model_downloader.check_local_model") as mock_check:
                mock_check.return_value = False

                with patch("sentence_transformers.SentenceTransformer") as mock_st:
                    mock_st.side_effect = socket.timeout("timed out")

                    callbacks = []
                    success, msg, path = download_with_retry(
                        local_dir=model_dir,
                        max_retries=3,
                        progress_callback=lambda s, m: callbacks.append((s, m)),
                    )
                    assert success is False
                    assert "重试" in msg
                    assert mock_st.call_count == 3

    def test_download_mirror_switch_on_retry(self, tmp_path):
        model_dir = tmp_path / "switch_model"

        with patch("seai.core.model_downloader.find_working_mirror") as mock_find:
            mock_find.return_value = "https://mirror1.com"

            with patch("seai.core.model_downloader.check_local_model") as mock_check:
                mock_check.return_value = False

                with patch("sentence_transformers.SentenceTransformer") as mock_st:
                    mock_st.side_effect = socket.timeout("timed out")

                    callbacks = []
                    download_with_retry(
                        local_dir=model_dir,
                        mirrors=["https://mirror1.com", "https://mirror2.com"],
                        max_retries=3,
                        progress_callback=lambda s, m: callbacks.append((s, m)),
                    )

                    mirror_switches = [c for c in callbacks if c[0] == "mirror_switch"]
                    assert len(mirror_switches) >= 1

    def test_download_exponential_backoff(self, tmp_path):
        model_dir = tmp_path / "backoff_model"

        with patch("seai.core.model_downloader.find_working_mirror") as mock_find:
            mock_find.return_value = "https://hf-mirror.com"

            with patch("seai.core.model_downloader.check_local_model") as mock_check:
                mock_check.return_value = False

                with patch("sentence_transformers.SentenceTransformer") as mock_st:
                    mock_st.side_effect = socket.timeout("timed out")

                    with patch("seai.core.model_downloader.time.sleep") as mock_sleep:
                        download_with_retry(
                            local_dir=model_dir,
                            max_retries=3,
                        )
                        delays = [call[0][0] for call in mock_sleep.call_args_list]
                        assert delays == [2, 4]


class TestUserGuidance:

    def test_get_user_guidance_contains_solutions(self):
        guidance = get_user_guidance("网络超时")
        assert "方案一" in guidance
        assert "方案二" in guidance
        assert "方案三" in guidance
        assert "网络连接" in guidance
        assert "手动下载" in guidance
        assert "环境变量" in guidance

    def test_get_user_guidance_contains_error(self):
        guidance = get_user_guidance("Connection refused")
        assert "Connection refused" in guidance

    def test_get_user_guidance_contains_model_path(self, tmp_path):
        guidance = get_user_guidance("test error", tmp_path / "models")
        assert "models" in guidance


class TestLoadEmbeddingModel:

    def test_load_from_local_cache(self, tmp_path):
        model_dir = tmp_path / "local_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "tokenizer_config.json").write_text("{}")
        (model_dir / "model.safetensors").write_bytes(b"\x00" * 100)

        with patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction") as mock_stef:
            mock_stef.return_value = MagicMock()
            result = load_embedding_model(local_dir=model_dir)
            mock_stef.assert_called_once_with(model_name=str(model_dir))
            assert result is not None

    def test_load_fallback_to_default(self, tmp_path):
        model_dir = tmp_path / "fallback_model"

        with patch("seai.core.model_downloader.download_with_retry") as mock_download:
            mock_download.return_value = (False, "all mirrors failed", None)

            with patch("chromadb.utils.embedding_functions.DefaultEmbeddingFunction") as mock_default:
                mock_default.return_value = MagicMock()
                result = load_embedding_model(local_dir=model_dir)
                assert result is not None


class TestNetworkEnvironmentSimulation:

    def test_normal_network(self, tmp_path):
        model_dir = tmp_path / "normal_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "tokenizer_config.json").write_text("{}")
        (model_dir / "model.safetensors").write_bytes(b"\x00" * 100)

        success, msg, path = download_with_retry(local_dir=model_dir)
        assert success is True
        assert "本地模型已存在" in msg

    def test_weak_network_with_retry_success(self, tmp_path):
        model_dir = tmp_path / "weak_network_model"

        with patch("seai.core.model_downloader.find_working_mirror") as mock_find:
            mock_find.return_value = "https://hf-mirror.com"

            with patch("seai.core.model_downloader.check_local_model") as mock_check:
                mock_check.side_effect = [False, False, True]

                with patch("sentence_transformers.SentenceTransformer") as mock_st:
                    mock_st.side_effect = [
                        socket.timeout("slow"),
                        socket.timeout("slow"),
                        MagicMock(),
                    ]

                    success, msg, path = download_with_retry(
                        local_dir=model_dir,
                        max_retries=3,
                    )
                    assert success is True

    def test_network_interrupted_all_fail(self, tmp_path):
        model_dir = tmp_path / "interrupted_model"

        with patch("seai.core.model_downloader.find_working_mirror") as mock_find:
            mock_find.return_value = None

            success, msg, path = download_with_retry(local_dir=model_dir)
            assert success is False
            assert "不可达" in msg

    def test_partial_download_recovery(self, tmp_path):
        model_dir = tmp_path / "partial_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text("{}")
        (model_dir / "tokenizer_config.json").write_text("{}")
        (model_dir / "model.safetensors").write_bytes(b"\x00" * 100)

        with patch("seai.core.model_downloader.find_working_mirror") as mock_find:
            mock_find.return_value = "https://hf-mirror.com"

            with patch("seai.core.model_downloader.check_local_model") as mock_check:
                mock_check.side_effect = [False, True]

                with patch("sentence_transformers.SentenceTransformer") as mock_st:
                    mock_st.side_effect = [
                        socket.timeout("timed out"),
                        socket.timeout("timed out"),
                        socket.timeout("timed out"),
                        socket.timeout("timed out"),
                        MagicMock(),
                    ]

                    success, msg, path = download_with_retry(
                        local_dir=model_dir,
                        max_retries=5,
                    )
                    assert success is True


class TestProgressCallback:

    def test_progress_callback_stages(self, tmp_path):
        model_dir = tmp_path / "progress_model"

        with patch("seai.core.model_downloader.find_working_mirror") as mock_find:
            mock_find.return_value = "https://hf-mirror.com"

            with patch("seai.core.model_downloader.check_local_model") as mock_check:
                mock_check.return_value = False

                with patch("sentence_transformers.SentenceTransformer") as mock_st:
                    mock_st.side_effect = socket.timeout("timed out")

                    callbacks = []
                    download_with_retry(
                        local_dir=model_dir,
                        max_retries=2,
                        progress_callback=lambda s, m: callbacks.append(s),
                    )

                    assert "checking" in callbacks
                    assert "mirror_ok" in callbacks
                    assert "downloading" in callbacks
                    assert "timeout" in callbacks
                    assert "retry_wait" in callbacks


class TestMemoryEngineIntegration:

    def test_memory_engine_uses_downloader(self, tmp_path):
        model_dir = tmp_path / "integration_model"
        model_dir.mkdir()
        (model_dir / "config.json").write_text('{"model_type": "bert"}')
        (model_dir / "tokenizer_config.json").write_text("{}")
        (model_dir / "model.safetensors").write_bytes(b"\x00" * 100)

        class MockEmbeddingFn:
            def __call__(self, input):
                return [[0.1] * 384] * len(input)
            def name(self):
                return "mock_embedding"

        with patch("seai.core.model_downloader.DEFAULT_LOCAL_DIR", model_dir):
            with patch("chromadb.utils.embedding_functions.SentenceTransformerEmbeddingFunction") as mock_stef:
                mock_stef.return_value = MockEmbeddingFn()
                try:
                    from seai.core.memory_engine import MemoryEngine
                    engine = MemoryEngine(persist_dir=tmp_path / "chroma")
                    assert engine.embed_fn is not None
                    assert engine.collection is not None
                except Exception as e:
                    if "chromadb" in str(e).lower() or "sqlite" in str(e).lower():
                        pytest.skip(f"ChromaDB 环境不可用: {e}")
                    raise

    def test_memory_engine_fallback_default(self, tmp_path):
        model_dir = tmp_path / "nonexistent_model"

        with patch("seai.core.model_downloader.DEFAULT_LOCAL_DIR", model_dir):
            with patch("seai.core.model_downloader.download_with_retry") as mock_download:
                mock_download.return_value = (False, "failed", None)
                try:
                    from seai.core.memory_engine import MemoryEngine
                    engine = MemoryEngine(persist_dir=tmp_path / "chroma_fallback")
                    assert engine.embed_fn is not None
                except Exception as e:
                    if "chromadb" in str(e).lower() or "sqlite" in str(e).lower():
                        pytest.skip(f"ChromaDB 环境不可用: {e}")
                    raise