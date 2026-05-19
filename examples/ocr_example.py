"""
OCR Adapter 使用示例

演示如何使用 PaddleOCR Adapter 处理作业图片
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.adapters.ocr import PaddleOCRAdapter, OCRException


def main():
    """主函数"""
    # 从环境变量读取 Token
    token = os.getenv("PADDLEOCR_TOKEN", "9b7fe06ddc38194934d1f8bbaa94f930c3d80d76")
    
    # 创建 Adapter
    adapter = PaddleOCRAdapter(
        token=token,
        poll_interval=5,  # 每 5 秒轮询一次
        timeout=300,  # 5 分钟超时
    )
    
    # 示例 1：处理本地文件
    print("=" * 60)
    print("示例 1：处理本地文件")
    print("=" * 60)
    
    local_file_path = "path/to/homework.jpg"  # 替换为实际路径
    
    if os.path.exists(local_file_path):
        try:
            result = adapter.process_file(
                file_path=local_file_path,
                file_id="homework_001",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_chart_recognition=False,
            )
            
            print(f"✅ OCR 成功！")
            print(f"文件 ID: {result.file_id}")
            print(f"提取页数: {result.extracted_pages}")
            print(f"置信度: {result.confidence:.2%}")
            print(f"图片数量: {len(result.images)}")
            print(f"\n--- Markdown 内容 ---")
            print(result.markdown[:500])  # 只显示前 500 字符
            print(f"\n--- 纯文本内容 ---")
            print(result.raw_text[:500])  # 只显示前 500 字符
            
        except OCRException as e:
            print(f"❌ OCR 失败: {e}")
    else:
        print(f"⚠️  文件不存在: {local_file_path}")
    
    # 示例 2：处理 URL
    print("\n" + "=" * 60)
    print("示例 2：处理 URL")
    print("=" * 60)
    
    image_url = "https://example.com/homework.jpg"  # 替换为实际 URL
    
    try:
        result = adapter.process_file(
            file_path=image_url,
            file_id="homework_002",
        )
        
        print(f"✅ OCR 成功！")
        print(f"文件 ID: {result.file_id}")
        print(f"提取页数: {result.extracted_pages}")
        print(f"置信度: {result.confidence:.2%}")
        
    except OCRException as e:
        print(f"❌ OCR 失败: {e}")
    
    # 示例 3：批量处理
    print("\n" + "=" * 60)
    print("示例 3：批量处理多个文件")
    print("=" * 60)
    
    file_list = [
        ("homework_001.jpg", "file_001"),
        ("homework_002.jpg", "file_002"),
        ("homework_003.jpg", "file_003"),
    ]
    
    results = []
    for file_path, file_id in file_list:
        if os.path.exists(file_path):
            try:
                result = adapter.process_file(file_path, file_id)
                results.append(result)
                print(f"✅ {file_id}: 成功 (置信度: {result.confidence:.2%})")
            except OCRException as e:
                print(f"❌ {file_id}: 失败 - {e}")
        else:
            print(f"⚠️  {file_id}: 文件不存在")
    
    print(f"\n总计: {len(results)}/{len(file_list)} 个文件处理成功")


if __name__ == "__main__":
    main()
