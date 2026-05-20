#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
SEAI 多模态本地处理引擎
提供图片编码、音频编码、OCR 等本地处理能力
"""
import base64
import io
import logging
from pathlib import Path
from typing import Optional, Tuple

logger = logging.getLogger("seai.se_tool")

try:
    from PIL import Image
    HAS_PIL = True
except ImportError:
    HAS_PIL = False
    logger.warning("Pillow 未安装，图片处理功能受限")

try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

MAX_IMAGE_SIZE = 20 * 1024 * 1024
MAX_IMAGE_DIMENSION = 4096
SUPPORTED_IMAGE_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}
SUPPORTED_AUDIO_FORMATS = {".wav", ".mp3", ".ogg", ".flac", ".m4a"}


def encode_image_to_base64(image_path: str, max_dimension: int = MAX_IMAGE_DIMENSION) -> Optional[str]:
    if not HAS_PIL:
        logger.error("Pillow 未安装，无法处理图片")
        return None

    path = Path(image_path)
    if not path.exists():
        logger.error(f"图片文件不存在: {image_path}")
        return None

    if path.stat().st_size > MAX_IMAGE_SIZE:
        logger.error(f"图片文件过大: {path.stat().st_size} > {MAX_IMAGE_SIZE}")
        return None

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_IMAGE_FORMATS:
        logger.error(f"不支持的图片格式: {suffix}")
        return None

    try:
        img = Image.open(path)
        img = img.convert("RGB")

        w, h = img.size
        if max(w, h) > max_dimension:
            scale = max_dimension / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)

        buffer = io.BytesIO()
        img.save(buffer, format="JPEG", quality=85)
        return base64.b64encode(buffer.getvalue()).decode("utf-8")
    except Exception as e:
        logger.error(f"图片编码失败: {e}")
        return None


def encode_audio_to_base64(audio_path: str) -> Optional[str]:
    path = Path(audio_path)
    if not path.exists():
        logger.error(f"音频文件不存在: {audio_path}")
        return None

    suffix = path.suffix.lower()
    if suffix not in SUPPORTED_AUDIO_FORMATS:
        logger.error(f"不支持的音频格式: {suffix}")
        return None

    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        logger.error(f"音频编码失败: {e}")
        return None


def get_image_info(image_path: str) -> Optional[dict]:
    if not HAS_PIL:
        return None

    path = Path(image_path)
    if not path.exists():
        return None

    try:
        img = Image.open(path)
        return {
            "width": img.width,
            "height": img.height,
            "format": img.format,
            "mode": img.mode,
            "file_size": path.stat().st_size,
        }
    except Exception:
        return None


def resize_image(image_path: str, output_path: str, width: int, height: int) -> bool:
    if not HAS_PIL:
        return False

    try:
        img = Image.open(image_path)
        img = img.resize((width, height), Image.LANCZOS)
        img.save(output_path)
        return True
    except Exception as e:
        logger.error(f"图片缩放失败: {e}")
        return False


def compress_image(image_path: str, output_path: str, quality: int = 75) -> bool:
    if not HAS_PIL:
        return False

    try:
        img = Image.open(image_path)
        img = img.convert("RGB")
        img.save(output_path, "JPEG", quality=quality)
        return True
    except Exception as e:
        logger.error(f"图片压缩失败: {e}")
        return False