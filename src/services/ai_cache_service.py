"""
AI 分析缓存服务

负责缓存 AI 分析结果，降低重复调用大模型的成本。

设计原则：
1. 缓存 key 基于稳定输入（SHA-256）
2. 支持 Redis 和内存缓存
3. 缓存失败不影响主流程（降级）
4. 不缓存异常结果和空结果
5. 支持 TTL（默认 24 小时）
"""

import json
import hashlib
import logging
from typing import Optional, Dict, Any, List
from dataclasses import asdict

try:
    import redis
    REDIS_AVAILABLE = True
except ImportError:
    REDIS_AVAILABLE = False

logger = logging.getLogger(__name__)


class AICacheService:
    """
    AI 分析缓存服务
    
    支持 Redis 和内存缓存两种模式。
    缓存失败时自动降级，不影响主流程。
    """
    
    def __init__(
        self,
        redis_url: Optional[str] = None,
        ttl: int = 86400,  # 24 小时
        key_prefix: str = "ai_analysis:",
    ):
        """
        初始化缓存服务
        
        Args:
            redis_url: Redis 连接 URL（如 redis://localhost:6379/0）
            ttl: 缓存过期时间（秒），默认 24 小时
            key_prefix: 缓存 key 前缀
        """
        self.ttl = ttl
        self.key_prefix = key_prefix
        self.redis_client: Optional[Any] = None
        self._memory_cache: Dict[str, str] = {}
        
        # 尝试连接 Redis
        if redis_url and REDIS_AVAILABLE:
            try:
                self.redis_client = redis.from_url(
                    redis_url,
                    decode_responses=True,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                )
                # 测试连接
                self.redis_client.ping()
                logger.info(f"Redis cache initialized: {redis_url}")
            except Exception as e:
                logger.warning(f"Failed to connect to Redis, falling back to memory cache: {e}")
                self.redis_client = None
        else:
            if redis_url and not REDIS_AVAILABLE:
                logger.warning("Redis URL provided but redis package not installed, using memory cache")
            logger.info("Using in-memory cache")
    
    def generate_cache_key(
        self,
        question_text: str,
        subject: Optional[str] = None,
        grade: Optional[str] = None,
        image_urls: Optional[List[str]] = None,
    ) -> str:
        """
        生成缓存 key
        
        基于稳定输入生成 SHA-256 hash：
        - question_text: 题目文本
        - subject: 学科
        - grade: 年级
        - image_urls: 图片 URL 列表（排序后）
        
        Args:
            question_text: 题目文本
            subject: 学科
            grade: 年级
            image_urls: 图片 URL 列表
        
        Returns:
            str: 缓存 key（带前缀）
        """
        # 构建稳定的输入字符串
        parts = [question_text]
        
        if subject:
            parts.append(f"subject:{subject}")
        
        if grade:
            parts.append(f"grade:{grade}")
        
        if image_urls:
            # 排序确保顺序一致
            sorted_urls = sorted(image_urls)
            parts.append(f"images:{','.join(sorted_urls)}")
        
        # 生成 SHA-256 hash
        input_str = "|".join(parts)
        hash_value = hashlib.sha256(input_str.encode('utf-8')).hexdigest()
        
        return f"{self.key_prefix}{hash_value}"
    
    def get(self, cache_key: str) -> Optional[Dict[str, Any]]:
        """
        从缓存获取分析结果
        
        Args:
            cache_key: 缓存 key
        
        Returns:
            Optional[Dict]: 分析结果，未命中返回 None
        """
        try:
            if self.redis_client:
                # 从 Redis 获取
                value = self.redis_client.get(cache_key)
                if value:
                    logger.debug(f"Cache hit (Redis): {cache_key}")
                    return json.loads(value)
            else:
                # 从内存缓存获取
                value = self._memory_cache.get(cache_key)
                if value:
                    logger.debug(f"Cache hit (memory): {cache_key}")
                    return json.loads(value)
            
            logger.debug(f"Cache miss: {cache_key}")
            return None
        
        except Exception as e:
            # 缓存读取失败不影响主流程
            logger.warning(f"Cache get failed for {cache_key}: {e}")
            return None
    
    def set(
        self,
        cache_key: str,
        analysis_result: Dict[str, Any],
        ttl: Optional[int] = None,
    ) -> bool:
        """
        写入缓存
        
        Args:
            cache_key: 缓存 key
            analysis_result: 分析结果
            ttl: 过期时间（秒），None 使用默认值
        
        Returns:
            bool: 是否写入成功
        """
        # 验证结果不为空
        if not analysis_result:
            logger.debug(f"Skip caching empty result for {cache_key}")
            return False
        
        # 验证必需字段存在
        required_fields = ['subject', 'knowledge_points']
        if not all(field in analysis_result for field in required_fields):
            logger.debug(f"Skip caching incomplete result for {cache_key}")
            return False
        
        # 验证 knowledge_points 不为空
        if not analysis_result.get('knowledge_points'):
            logger.debug(f"Skip caching result with empty knowledge_points for {cache_key}")
            return False
        
        try:
            value = json.dumps(analysis_result, ensure_ascii=False)
            cache_ttl = ttl if ttl is not None else self.ttl
            
            if self.redis_client:
                # 写入 Redis
                self.redis_client.setex(cache_key, cache_ttl, value)
                logger.debug(f"Cached to Redis: {cache_key} (TTL: {cache_ttl}s)")
            else:
                # 写入内存缓存（注意：内存缓存不支持 TTL）
                self._memory_cache[cache_key] = value
                logger.debug(f"Cached to memory: {cache_key}")
            
            return True
        
        except Exception as e:
            # 缓存写入失败不影响主流程
            logger.warning(f"Cache set failed for {cache_key}: {e}")
            return False
    
    def delete(self, cache_key: str) -> bool:
        """
        删除缓存
        
        Args:
            cache_key: 缓存 key
        
        Returns:
            bool: 是否删除成功
        """
        try:
            if self.redis_client:
                self.redis_client.delete(cache_key)
            else:
                self._memory_cache.pop(cache_key, None)
            
            logger.debug(f"Cache deleted: {cache_key}")
            return True
        
        except Exception as e:
            logger.warning(f"Cache delete failed for {cache_key}: {e}")
            return False
    
    def clear(self) -> bool:
        """
        清空所有缓存
        
        Returns:
            bool: 是否清空成功
        """
        try:
            if self.redis_client:
                # 删除所有匹配前缀的 key
                pattern = f"{self.key_prefix}*"
                keys = self.redis_client.keys(pattern)
                if keys:
                    self.redis_client.delete(*keys)
                logger.info(f"Cleared {len(keys)} keys from Redis")
            else:
                self._memory_cache.clear()
                logger.info("Cleared memory cache")
            
            return True
        
        except Exception as e:
            logger.warning(f"Cache clear failed: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
        """
        获取缓存统计信息
        
        Returns:
            Dict: 统计信息
        """
        try:
            if self.redis_client:
                pattern = f"{self.key_prefix}*"
                keys = self.redis_client.keys(pattern)
                return {
                    "backend": "redis",
                    "total_keys": len(keys),
                    "ttl": self.ttl,
                }
            else:
                return {
                    "backend": "memory",
                    "total_keys": len(self._memory_cache),
                    "ttl": self.ttl,
                }
        
        except Exception as e:
            logger.warning(f"Failed to get cache stats: {e}")
            return {
                "backend": "unknown",
                "error": str(e),
            }
