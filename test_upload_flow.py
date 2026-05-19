"""
快速测试：文件上传流程

验证：
1. 文件校验（类型、大小）
2. Hash 计算和去重
3. 数据库写入
4. API 响应格式

不依赖真实数据库，使用内存 SQLite。
"""

import asyncio
import io
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.db.session import get_db
from src.main import create_app
from src.models.base import Base


# 测试用内存数据库
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="function")
async def test_db():
    """创建测试数据库"""
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async_session = sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with async_session() as session:
        yield session

    await engine.dispose()


@pytest.fixture(scope="function")
async def client(test_db):
    """创建测试客户端"""
    app = create_app()

    async def override_get_db():
        yield test_db

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as test_client:
        yield test_client


@pytest.mark.asyncio
async def test_upload_valid_image(client):
    """测试：上传有效图片"""
    # 创建一个假图片（1x1 PNG）
    fake_image = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01"
        b"\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde"
    )

    files = {"file": ("test.png", io.BytesIO(fake_image), "image/png")}

    response = await client.post("/api/upload", files=files)

    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    assert "assignment_id" in data
    assert data["status"] == "uploaded"
    assert data["is_duplicate"] is False


@pytest.mark.asyncio
async def test_upload_duplicate_image(client):
    """测试：上传重复图片（hash 相同）"""
    fake_image = b"\x89PNG\r\n\x1a\n" + b"x" * 100

    files = {"file": ("test.png", io.BytesIO(fake_image), "image/png")}

    # 第一次上传
    response1 = await client.post("/api/upload", files=files)
    assert response1.status_code == 200
    data1 = response1.json()
    assert data1["is_duplicate"] is False

    # 第二次上传（相同内容）
    files2 = {"file": ("test2.png", io.BytesIO(fake_image), "image/png")}
    response2 = await client.post("/api/upload", files=files2)
    assert response2.status_code == 200
    data2 = response2.json()
    assert data2["is_duplicate"] is True  # 检测到重复


@pytest.mark.asyncio
async def test_upload_invalid_file_type(client):
    """测试：上传不支持的文件类型"""
    fake_pdf = b"%PDF-1.4"

    files = {"file": ("test.pdf", io.BytesIO(fake_pdf), "application/pdf")}

    response = await client.post("/api/upload", files=files)

    assert response.status_code == 400
    assert "不支持的文件类型" in response.json()["detail"]


@pytest.mark.asyncio
async def test_get_assignment_status(client):
    """测试：查询作业状态"""
    # 先上传
    fake_image = b"\x89PNG\r\n\x1a\n" + b"y" * 50
    files = {"file": ("test.png", io.BytesIO(fake_image), "image/png")}
    upload_response = await client.post("/api/upload", files=files)
    assignment_id = upload_response.json()["assignment_id"]

    # 查询状态
    status_response = await client.get(f"/api/assignments/{assignment_id}")
    assert status_response.status_code == 200
    data = status_response.json()
    assert data["assignment_id"] == assignment_id
    assert data["status"] == "uploaded"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
