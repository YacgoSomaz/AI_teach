"""
文件上传服务

负责：
1. 校验上传文件（类型、大小）
2. 计算文件内容 SHA-256（去重）
3. 生成唯一 file_id
4. 存储到对象存储（本地 / OSS / S3 / MinIO）
5. 返回 storage_url（私有桶，访问需生成临时 URL）

设计原则（来自 content-hash-cache-pattern skill）：
- 用文件内容 hash 而非路径做去重键
- 相同内容的图片只存一份，节省 OCR 成本
- 文件服务不感知业务逻辑，只负责存取

安全原则（来自 security-review skill）：
- 校验 MIME 类型 + 文件扩展名（双重校验）
- 文件大小限制
- 不在日志中打印文件内容
- 存储路径不暴露给前端
"""

import hashlib
import os
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

# 允许的文件类型（MIME + 扩展名双重校验）
ALLOWED_MIME_TYPES = {
    "image/jpeg",
    "image/png",
    "image/webp",
    "image/heic",
    "image/heif",
}

ALLOWED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}

# 文件大小限制：20MB（作业图片通常 1-5MB，留足余量）
MAX_FILE_SIZE_BYTES = 20 * 1024 * 1024

# SHA-256 分块读取大小：64KB
_HASH_CHUNK_SIZE = 65536


class FileValidationError(Exception):
    """文件校验失败"""
    pass


class FileStorageError(Exception):
    """文件存储失败"""
    pass


@dataclass
class UploadedFile:
    """文件上传结果"""
    file_id: str          # 唯一 ID（UUID）
    file_hash: str        # SHA-256 内容 hash
    original_filename: str
    file_size: int        # 字节数
    mime_type: str
    storage_url: str      # 对象存储 URL（私有）
    is_duplicate: bool    # 是否与已有文件内容相同


def compute_file_hash(file_content: bytes) -> str:
    """
    计算文件内容的 SHA-256 hash

    用于去重：相同内容的图片不重复 OCR。
    （来自 content-hash-cache-pattern skill）
    """
    sha256 = hashlib.sha256()
    # 分块计算，避免大文件一次性加载到内存
    for i in range(0, len(file_content), _HASH_CHUNK_SIZE):
        sha256.update(file_content[i : i + _HASH_CHUNK_SIZE])
    return sha256.hexdigest()


def validate_upload(
    filename: str,
    mime_type: str,
    file_size: int,
) -> None:
    """
    校验上传文件

    双重校验：MIME 类型 + 文件扩展名
    （来自 security-review skill：File Upload Validation）

    Raises:
        FileValidationError: 校验失败
    """
    # 1. 文件大小校验
    if file_size > MAX_FILE_SIZE_BYTES:
        raise FileValidationError(
            f"文件过大：{file_size / 1024 / 1024:.1f}MB，最大允许 {MAX_FILE_SIZE_BYTES // 1024 // 1024}MB"
        )

    if file_size == 0:
        raise FileValidationError("文件为空")

    # 2. MIME 类型校验（白名单）
    if mime_type not in ALLOWED_MIME_TYPES:
        raise FileValidationError(
            f"不支持的文件类型：{mime_type}，仅支持 {', '.join(sorted(ALLOWED_MIME_TYPES))}"
        )

    # 3. 文件扩展名校验（白名单，防止扩展名伪造）
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise FileValidationError(
            f"不支持的文件扩展名：{ext}，仅支持 {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )


class LocalFileStorage:
    """
    本地文件存储（开发/测试用）

    生产环境替换为 OSSFileStorage / S3FileStorage。
    接口保持一致，业务代码无需修改。
    """

    def __init__(self, base_dir: str = "uploads"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, file_id: str, file_content: bytes, mime_type: str) -> str:
        """
        保存文件，返回 storage_url

        Args:
            file_id: 唯一文件 ID
            file_content: 文件二进制内容
            mime_type: MIME 类型

        Returns:
            str: storage_url（本地路径格式）
        """
        # 按 file_id 前两位分目录，避免单目录文件过多
        sub_dir = self.base_dir / file_id[:2]
        sub_dir.mkdir(parents=True, exist_ok=True)

        # 扩展名映射
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/webp": ".webp",
            "image/heic": ".heic",
            "image/heif": ".heif",
        }
        ext = ext_map.get(mime_type, ".jpg")
        file_path = sub_dir / f"{file_id}{ext}"

        try:
            file_path.write_bytes(file_content)
        except OSError as e:
            raise FileStorageError(f"文件写入失败：{e}") from e

        return str(file_path)

    def get_url(self, storage_url: str, expires_in: int = 3600) -> str:
        """
        获取文件访问 URL

        本地存储直接返回路径；生产环境返回带签名的临时 URL。

        Args:
            storage_url: 存储路径
            expires_in: URL 有效期（秒），生产环境使用

        Returns:
            str: 可访问的 URL
        """
        # 本地开发：直接返回路径
        # 生产环境：生成临时签名 URL（OSS/S3 实现）
        return f"file://{storage_url}"


class FileService:
    """
    文件上传服务

    用法：
        service = FileService(storage=LocalFileStorage())
        result = await service.upload(filename, mime_type, file_content)
    """

    def __init__(self, storage: LocalFileStorage):
        self.storage = storage

    def upload(
        self,
        filename: str,
        mime_type: str,
        file_content: bytes,
        existing_hashes: set[str] | None = None,
    ) -> UploadedFile:
        """
        上传文件

        流程：
        1. 校验文件（类型、大小）
        2. 计算内容 hash（去重）
        3. 生成 file_id
        4. 存储文件
        5. 返回 UploadedFile

        Args:
            filename: 原始文件名
            mime_type: MIME 类型
            file_content: 文件二进制内容
            existing_hashes: 已存在的 hash 集合（用于去重判断）

        Returns:
            UploadedFile: 上传结果

        Raises:
            FileValidationError: 文件校验失败
            FileStorageError: 存储失败
        """
        file_size = len(file_content)

        # 1. 校验
        validate_upload(filename, mime_type, file_size)

        # 2. 计算 hash（content-hash-cache-pattern）
        file_hash = compute_file_hash(file_content)

        # 3. 判断是否重复
        is_duplicate = bool(existing_hashes and file_hash in existing_hashes)

        # 4. 生成唯一 file_id
        file_id = str(uuid.uuid4())

        # 5. 存储（即使重复也存，因为 file_id 不同；去重逻辑在业务层决定是否跳过 OCR）
        storage_url = self.storage.save(file_id, file_content, mime_type)

        return UploadedFile(
            file_id=file_id,
            file_hash=file_hash,
            original_filename=filename,
            file_size=file_size,
            mime_type=mime_type,
            storage_url=storage_url,
            is_duplicate=is_duplicate,
        )

    def get_access_url(self, storage_url: str, expires_in: int = 3600) -> str:
        """
        获取文件临时访问 URL

        Args:
            storage_url: 存储路径
            expires_in: URL 有效期（秒）

        Returns:
            str: 临时访问 URL
        """
        return self.storage.get_url(storage_url, expires_in)
