"""简单内存缓存，用于加速 RAG 检索"""

import hashlib
import time
from typing import Optional, Any


class SimpleCache:
    """基于字典的简单内存缓存，带 TTL 过期"""
    
    def __init__(self, ttl_seconds: int = 3600):
        self._cache: dict[str, tuple[Any, float]] = {}
        self.ttl = ttl_seconds
    
    def _make_key(self, *args) -> str:
        """根据参数生成缓存键"""
        key_str = "|".join(str(arg) for arg in args)
        return hashlib.md5(key_str.encode()).hexdigest()
    
    def get(self, *args) -> Optional[Any]:
        """获取缓存值"""
        key = self._make_key(*args)
        if key in self._cache:
            value, timestamp = self._cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                # 过期删除
                del self._cache[key]
        return None
    
    def set(self, *args, value: Any) -> None:
        """设置缓存值"""
        key = self._make_key(*args)
        self._cache[key] = (value, time.time())
    
    def clear(self) -> None:
        """清空缓存"""
        self._cache.clear()
    
    def cleanup_expired(self) -> int:
        """清理过期条目，返回清理数量"""
        now = time.time()
        expired_keys = [
            k for k, (_, ts) in self._cache.items()
            if now - ts >= self.ttl
        ]
        for k in expired_keys:
            del self._cache[k]
        return len(expired_keys)


# 全局缓存实例
rag_cache = SimpleCache(ttl_seconds=7200)  # 2小时过期
