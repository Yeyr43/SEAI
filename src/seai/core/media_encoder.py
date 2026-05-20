"""
SEAI 媒体编码器 — 自动检测并编码用户查询中的图片/音频路径
从 SEAgent 提取，单一职责：媒体文件的自动检测与编码
"""
import re
import os as _os
import time
from typing import List, Optional
from loguru import logger


class MediaEncoder:
    """媒体编码器 — 自动编码用户查询中引用的媒体文件路径"""

    IMAGE_EXTS = {'.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp'}
    AUDIO_EXTS = {'.wav', '.mp3', '.ogg', '.flac', '.m4a'}
    MIME_MAP = {
        '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
        '.png': 'image/png', '.gif': 'image/gif',
        '.webp': 'image/webp', '.bmp': 'image/bmp',
    }

    def __init__(self, memory_store=None):
        self.memory_store = memory_store

    def get_media_blocks_for_query(self, query: str) -> list:
        """检查查询是否关联已有媒体记忆，返回 content block 列表"""
        if not self.memory_store:
            return []
        media_keywords = ["图片", "照片", "图像", "音频", "录音", "音乐", "之前发的", "刚才的",
                          "image", "photo", "picture", "audio", "media"]
        if not any(kw in query.lower() for kw in media_keywords):
            return []
        try:
            media_memories = self.memory_store.search_by_type(
                query, ["image_analysis", "audio_analysis"], top_k=3
            )
            blocks = []
            for mem in media_memories:
                media_id = mem.get("media_id") if isinstance(mem, dict) else None
                if not media_id:
                    continue
                media_b64 = self.memory_store.get_media(media_id)
                if media_b64:
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{media_b64}"}
                    })
            return blocks
        except Exception:
            return []

    def auto_encode_media_paths(self, query: str) -> list:
        """自动检测用户查询中的图片/音频文件路径，编码并注入 content block"""
        from se_tool import encode_image_to_base64

        all_exts = self.IMAGE_EXTS | self.AUDIO_EXTS
        ext_group = '|'.join(re.escape(e.lstrip('.')) for e in all_exts)

        quoted_p = re.compile(r'[\'"]([^\'"]+\.(?:' + ext_group + r'))[\'"]', re.IGNORECASE)
        bare_p = re.compile(r'(?:^|\s)([^\s\'"]+\.(?:' + ext_group + r'))(?:\s|$)', re.IGNORECASE)
        drive_p = re.compile(r'([A-Za-z]:[\\/][^\s\'"]*\.(?:' + ext_group + r'))', re.IGNORECASE)

        candidates = []
        for m in quoted_p.finditer(query):
            candidates.append(m.group(1))
        for m in bare_p.finditer(query):
            candidates.append(m.group(1))
        for m in drive_p.finditer(query):
            candidates.append(m.group(1))

        blocks = []
        processed = set()

        for raw_path in candidates:
            path = _os.path.normpath(raw_path.strip('\'"'))
            if path in processed or not _os.path.isfile(path):
                continue
            processed.add(path)

            ext = _os.path.splitext(path)[1].lower()

            if ext in self.IMAGE_EXTS:
                b64 = encode_image_to_base64(path)
                if b64:
                    mime = self.MIME_MAP.get(ext, 'image/jpeg')
                    blocks.append({
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"}
                    })

                    if self.memory_store and hasattr(self.memory_store, 'store_media'):
                        import uuid as _uuid
                        media_id = _uuid.uuid4().hex[:12]
                        self.memory_store.store_media(
                            media_id, "image_analysis", b64,
                            {"tool": "auto_encode", "path": path, "timestamp": time.time()}
                        )
                        if hasattr(self.memory_store, 'add_long_term_memory_with_links'):
                            self.memory_store.add_long_term_memory_with_links(
                                f"[auto_encode] {path} → 自动编码分析",
                                mem_type="image_analysis", storage_mode="original",
                                media_id=media_id
                            )

            elif ext in self.AUDIO_EXTS:
                from se_tool import encode_audio_to_base64
                b64 = encode_audio_to_base64(path)
                if b64 and self.memory_store and hasattr(self.memory_store, 'store_media'):
                    import uuid as _uuid
                    media_id = _uuid.uuid4().hex[:12]
                    self.memory_store.store_media(
                        media_id, "audio_analysis", b64,
                        {"tool": "auto_encode", "path": path, "timestamp": time.time()}
                    )
                    if hasattr(self.memory_store, 'add_long_term_memory_with_links'):
                        self.memory_store.add_long_term_memory_with_links(
                            f"[auto_encode] {path} → 已编码音频并存储",
                            mem_type="audio_analysis", storage_mode="original",
                            media_id=media_id
                        )

        return blocks
