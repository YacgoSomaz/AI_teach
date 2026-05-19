"""
AI 缓存服务测试
"""

import pytest
from src.services.ai_cache_service import AICacheService


class TestAICacheService:
    """AI 缓存服务测试"""
    
    def test_generate_cache_key_basic(self):
        """测试：基本缓存 key 生成"""
        service = AICacheService()
        
        key1 = service.generate_cache_key("题目1")
        key2 = service.generate_cache_key("题目1")
        key3 = service.generate_cache_key("题目2")
        
        # 相同输入生成相同 key
        assert key1 == key2
        
        # 不同输入生成不同 key
        assert key1 != key3
        
        # key 应该包含前缀
        assert key1.startswith("ai_analysis:")
    
    def test_generate_cache_key_with_metadata(self):
        """测试：带元数据的缓存 key 生成"""
        service = AICacheService()
        
        # 相同题目，不同学科/年级，生成不同 key
        key1 = service.generate_cache_key("题目1", subject="数学", grade="八年级")
        key2 = service.generate_cache_key("题目1", subject="物理", grade="八年级")
        key3 = service.generate_cache_key("题目1", subject="数学", grade="九年级")
        
        assert key1 != key2
        assert key1 != key3
        assert key2 != key3
    
    def test_generate_cache_key_with_images(self):
        """测试：带图片的缓存 key 生成"""
        service = AICacheService()
        
        # 相同题目，不同图片，生成不同 key
        key1 = service.generate_cache_key("题目1", image_urls=["http://img1.jpg"])
        key2 = service.generate_cache_key("题目1", image_urls=["http://img2.jpg"])
        key3 = service.generate_cache_key("题目1", image_urls=["http://img1.jpg", "http://img2.jpg"])
        
        assert key1 != key2
        assert key1 != key3
        
        # 图片顺序不同，但排序后相同，生成相同 key
        key4 = service.generate_cache_key("题目1", image_urls=["http://img2.jpg", "http://img1.jpg"])
        assert key3 == key4
    
    def test_memory_cache_set_and_get(self):
        """测试：内存缓存的读写"""
        service = AICacheService()
        
        cache_key = service.generate_cache_key("题目1")
        analysis_result = {
            "subject": "数学",
            "knowledge_points": ["一次函数"],
            "difficulty": 3,
        }
        
        # 写入缓存
        success = service.set(cache_key, analysis_result)
        assert success is True
        
        # 读取缓存
        cached = service.get(cache_key)
        assert cached is not None
        assert cached["subject"] == "数学"
        assert cached["knowledge_points"] == ["一次函数"]
    
    def test_cache_miss(self):
        """测试：缓存未命中"""
        service = AICacheService()
        
        cache_key = service.generate_cache_key("不存在的题目")
        cached = service.get(cache_key)
        
        assert cached is None
    
    def test_skip_caching_empty_result(self):
        """测试：不缓存空结果"""
        service = AICacheService()
        
        cache_key = service.generate_cache_key("题目1")
        
        # 空结果
        success = service.set(cache_key, {})
        assert success is False
        
        # 验证未写入
        cached = service.get(cache_key)
        assert cached is None
    
    def test_skip_caching_incomplete_result(self):
        """测试：不缓存不完整的结果"""
        service = AICacheService()
        
        cache_key = service.generate_cache_key("题目1")
        
        # 缺少必需字段
        incomplete_result = {
            "subject": "数学",
            # 缺少 knowledge_points
        }
        
        success = service.set(cache_key, incomplete_result)
        assert success is False
    
    def test_skip_caching_empty_knowledge_points(self):
        """测试：不缓存 knowledge_points 为空的结果"""
        service = AICacheService()
        
        cache_key = service.generate_cache_key("题目1")
        
        # knowledge_points 为空
        result = {
            "subject": "数学",
            "knowledge_points": [],
        }
        
        success = service.set(cache_key, result)
        assert success is False
    
    def test_delete_cache(self):
        """测试：删除缓存"""
        service = AICacheService()
        
        cache_key = service.generate_cache_key("题目1")
        analysis_result = {
            "subject": "数学",
            "knowledge_points": ["一次函数"],
        }
        
        # 写入缓存
        service.set(cache_key, analysis_result)
        assert service.get(cache_key) is not None
        
        # 删除缓存
        success = service.delete(cache_key)
        assert success is True
        
        # 验证已删除
        assert service.get(cache_key) is None
    
    def test_clear_cache(self):
        """测试：清空所有缓存"""
        service = AICacheService()
        
        # 写入多个缓存
        for i in range(3):
            cache_key = service.generate_cache_key(f"题目{i}")
            service.set(cache_key, {
                "subject": "数学",
                "knowledge_points": [f"知识点{i}"],
            })
        
        # 清空缓存
        success = service.clear()
        assert success is True
        
        # 验证所有缓存已清空
        for i in range(3):
            cache_key = service.generate_cache_key(f"题目{i}")
            assert service.get(cache_key) is None
    
    def test_get_stats(self):
        """测试：获取缓存统计信息"""
        service = AICacheService()
        
        # 写入几个缓存
        for i in range(3):
            cache_key = service.generate_cache_key(f"题目{i}")
            service.set(cache_key, {
                "subject": "数学",
                "knowledge_points": [f"知识点{i}"],
            })
        
        stats = service.get_stats()
        
        assert stats["backend"] == "memory"
        assert stats["total_keys"] == 3
        assert stats["ttl"] == 86400  # 默认 24 小时
    
    def test_custom_ttl(self):
        """测试：自定义 TTL"""
        service = AICacheService(ttl=3600)  # 1 小时
        
        stats = service.get_stats()
        assert stats["ttl"] == 3600
    
    def test_custom_key_prefix(self):
        """测试：自定义 key 前缀"""
        service = AICacheService(key_prefix="custom:")
        
        cache_key = service.generate_cache_key("题目1")
        assert cache_key.startswith("custom:")
