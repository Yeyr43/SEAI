"""
健壮的嵌入模型下载器
功能：多镜像站自动切换、超时重试、断点续传、本地缓存、进度反馈
"""
import os
import sys
import time
import shutil
import hashlib
from pathlib import Path
from typing import Optional, List, Tuple
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError
import socket


DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_LOCAL_DIR = Path(os.environ.get("SEAI_MODEL_PATH", str(Path.cwd() / "models" / "all-MiniLM-L6-v2")))

HF_MIRRORS = [
    "https://hf-mirror.com",
    "https://huggingface.co",
]

CONNECT_TIMEOUT = 15
READ_TIMEOUT = 60
MAX_RETRIES = 5
RETRY_BASE_DELAY = 2


def check_mirror_connectivity(mirror_url: str, timeout: int = CONNECT_TIMEOUT) -> Tuple[bool, str]:
    try:
        req = Request(f"{mirror_url}/api/status", headers={"User-Agent": "SEAI-ModelDownloader/1.0"})
        resp = urlopen(req, timeout=timeout)
        resp.read()
        return True, ""
    except socket.timeout:
        return False, f"连接超时（{timeout}s）"
    except URLError as e:
        return False, f"网络不可达: {e.reason}"
    except Exception as e:
        return False, str(e)


def find_working_mirror(mirrors: List[str] = None, timeout: int = CONNECT_TIMEOUT) -> Optional[str]:
    if mirrors is None:
        mirrors = HF_MIRRORS
    for mirror in mirrors:
        ok, err = check_mirror_connectivity(mirror, timeout)
        if ok:
            return mirror
    return None


def check_local_model(model_dir: Path) -> bool:
    if not model_dir.exists():
        return False
    required_files = ["config.json", "tokenizer_config.json"]
    for f in required_files:
        if not (model_dir / f).exists():
            return False
    model_files = list(model_dir.glob("*.safetensors")) + list(model_dir.glob("pytorch_model.bin"))
    if not model_files:
        return False
    return True


def get_local_model_info(model_dir: Path) -> dict:
    info = {"exists": False, "path": str(model_dir), "files": [], "size_mb": 0}
    if not model_dir.exists():
        return info
    info["exists"] = True
    total_size = 0
    for f in model_dir.rglob("*"):
        if f.is_file():
            size = f.stat().st_size
            total_size += size
            info["files"].append({"name": f.name, "size": size})
    info["size_mb"] = round(total_size / 1024 / 1024, 2)
    return info


def download_with_retry(
    model_name: str = DEFAULT_MODEL_NAME,
    local_dir: Path = None,
    mirrors: List[str] = None,
    max_retries: int = MAX_RETRIES,
    connect_timeout: int = CONNECT_TIMEOUT,
    read_timeout: int = READ_TIMEOUT,
    progress_callback=None,
) -> Tuple[bool, str, Optional[Path]]:
    if local_dir is None:
        local_dir = DEFAULT_LOCAL_DIR
    if mirrors is None:
        mirrors = HF_MIRRORS

    if check_local_model(local_dir):
        info = get_local_model_info(local_dir)
        msg = f"本地模型已存在: {local_dir} ({info['size_mb']}MB)"
        if progress_callback:
            progress_callback("cache_hit", msg)
        return True, msg, local_dir

    if progress_callback:
        progress_callback("checking", "正在检测镜像站连通性...")

    working_mirror = find_working_mirror(mirrors, connect_timeout)
    if not working_mirror:
        if check_local_model(local_dir):
            msg = f"所有镜像站不可达，使用本地缓存: {local_dir}"
            if progress_callback:
                progress_callback("fallback_local", msg)
            return True, msg, local_dir
        return False, "所有 HuggingFace 镜像站均不可达，且本地无缓存模型", None

    if progress_callback:
        progress_callback("mirror_ok", f"镜像站连通: {working_mirror}")

    os.environ["HF_ENDPOINT"] = working_mirror

    last_error = ""
    for attempt in range(1, max_retries + 1):
        try:
            if progress_callback:
                progress_callback("downloading", f"正在下载模型 (第 {attempt}/{max_retries} 次尝试)...")

            socket.setdefaulttimeout(read_timeout)

            from sentence_transformers import SentenceTransformer
            model = SentenceTransformer(model_name, cache_folder=str(local_dir.parent))

            if progress_callback:
                progress_callback("verifying", "正在验证模型完整性...")

            if check_local_model(local_dir):
                info = get_local_model_info(local_dir)
                msg = f"模型下载成功: {local_dir} ({info['size_mb']}MB, 镜像: {working_mirror})"
                if progress_callback:
                    progress_callback("success", msg)
                return True, msg, local_dir

            last_error = "模型下载后本地验证失败"
            if progress_callback:
                progress_callback("verify_failed", last_error)

        except (socket.timeout, TimeoutError) as e:
            last_error = f"下载超时: {e}"
            if progress_callback:
                progress_callback("timeout", last_error)
        except (URLError, HTTPError, ConnectionError, OSError) as e:
            last_error = f"网络错误: {e}"
            if progress_callback:
                progress_callback("network_error", last_error)
        except Exception as e:
            last_error = f"下载异常: {e}"
            if progress_callback:
                progress_callback("error", last_error)

        if attempt < max_retries:
            delay = RETRY_BASE_DELAY * (2 ** (attempt - 1))
            if progress_callback:
                progress_callback("retry_wait", f"等待 {delay}s 后重试...")
            time.sleep(delay)

            if attempt >= 2 and attempt - 1 < len(mirrors):
                next_mirror_idx = (mirrors.index(working_mirror) + 1) % len(mirrors)
                working_mirror = mirrors[next_mirror_idx]
                os.environ["HF_ENDPOINT"] = working_mirror
                if progress_callback:
                    progress_callback("mirror_switch", f"切换镜像站: {working_mirror}")

    if check_local_model(local_dir):
        msg = f"部分下载成功，使用已有模型: {local_dir}"
        if progress_callback:
            progress_callback("partial_ok", msg)
        return True, msg, local_dir

    return False, f"模型下载失败（已重试 {max_retries} 次）: {last_error}", None


def get_user_guidance(error_msg: str, local_dir: Path = None) -> str:
    if local_dir is None:
        local_dir = DEFAULT_LOCAL_DIR

    guidance = f"""
╔══════════════════════════════════════════════════════════════╗
║              嵌入模型加载失败 - 解决方案                        ║
╠══════════════════════════════════════════════════════════════╣
║ 错误信息: {error_msg[:60]}
╠══════════════════════════════════════════════════════════════╣
║ 方案一：检查网络连接                                          ║
║   - 确认设备已连接到互联网                                     ║
║   - 检查防火墙/代理设置是否阻止了 HuggingFace 访问              ║
║   - 尝试在浏览器中访问 https://hf-mirror.com                  ║
╠══════════════════════════════════════════════════════════════╣
║ 方案二：手动下载模型                                          ║
║   1. 访问 https://hf-mirror.com/sentence-transformers/       ║
║      all-MiniLM-L6-v2/tree/main                              ║
║   2. 下载所有文件到以下目录:                                   ║
║      {str(local_dir)}
║   3. 确保包含: config.json, tokenizer_config.json,            ║
║      pytorch_model.bin 或 model.safetensors                  ║
╠══════════════════════════════════════════════════════════════╣
║ 方案三：设置环境变量                                          ║
║   - SEAI_MODEL_PATH: 指向已下载的模型目录                      ║
║   - HF_ENDPOINT: 自定义 HuggingFace 镜像站地址                 ║
╠══════════════════════════════════════════════════════════════╣
║ 当前将使用默认嵌入函数（精度较低），系统仍可正常运行              ║
╚══════════════════════════════════════════════════════════════╝
"""
    return guidance


_cached_embedding_function = None
_cached_model_path = None


def _find_in_sentence_transformers_cache(model_name: str) -> Optional[Path]:
    """在 SentenceTransformer 默认缓存目录中查找模型"""
    import sentence_transformers
    st_cache = Path(sentence_transformers.__file__).parent / "models"
    if st_cache.exists():
        for d in st_cache.iterdir():
            if d.is_dir() and (model_name.replace("/", "--") in d.name or model_name.split("/")[-1] == d.name):
                if check_local_model(d):
                    return d
    hf_cache = Path.home() / ".cache" / "huggingface" / "hub"
    if hf_cache.exists():
        model_slug = "models--" + model_name.replace("/", "--")
        for d in hf_cache.glob(f"{model_slug}/snapshots/*/"):
            if check_local_model(d):
                return d
    return None


def load_embedding_model(
    model_name: str = DEFAULT_MODEL_NAME,
    local_dir: Path = None,
    mirrors: List[str] = None,
    progress_callback=None,
):
    global _cached_embedding_function, _cached_model_path

    if local_dir is None:
        local_dir = DEFAULT_LOCAL_DIR

    if _cached_embedding_function is not None and _cached_model_path == str(local_dir):
        if progress_callback:
            progress_callback("cache_hit", f"使用已加载的模型缓存: {local_dir}")
        return _cached_embedding_function

    # 检查指定的本地路径
    if check_local_model(local_dir):
        if progress_callback:
            progress_callback("cache_hit", f"加载本地模型: {local_dir}")
        from chromadb.utils import embedding_functions
        _cached_embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=str(local_dir))
        _cached_model_path = str(local_dir)
        return _cached_embedding_function

    # 检查 SentenceTransformer 内置缓存
    cache_dir = _find_in_sentence_transformers_cache(model_name)
    if cache_dir is not None:
        if progress_callback:
            progress_callback("cache_hit", f"加载缓存模型: {cache_dir}")
        from chromadb.utils import embedding_functions
        _cached_embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=str(cache_dir))
        _cached_model_path = str(cache_dir)
        return _cached_embedding_function

    success, msg, path = download_with_retry(
        model_name=model_name,
        local_dir=local_dir,
        mirrors=mirrors,
        progress_callback=progress_callback,
    )

    if success and path:
        from chromadb.utils import embedding_functions
        _cached_embedding_function = embedding_functions.SentenceTransformerEmbeddingFunction(model_name=str(path))
        _cached_model_path = str(path)
        return _cached_embedding_function

    print(get_user_guidance(msg, local_dir))
    from chromadb.utils import embedding_functions
    _cached_embedding_function = embedding_functions.DefaultEmbeddingFunction()
    _cached_model_path = str(local_dir)
    return _cached_embedding_function