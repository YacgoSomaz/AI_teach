"""
快速测试 OCR Adapter

这个脚本可以直接运行，测试 PaddleOCR Adapter 是否正常工作
"""

import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

from src.adapters.ocr import PaddleOCRAdapter, OCRException


def main():
    """主函数"""
    print("=" * 60)
    print("PaddleOCR Adapter 快速测试")
    print("=" * 60)
    
    TOKEN = os.getenv("PADDLEOCR_TOKEN")
    if not TOKEN:
        print("请先设置 PADDLEOCR_TOKEN 环境变量")
        return
    
    # 创建 Adapter
    adapter = PaddleOCRAdapter(
        token=TOKEN,
        poll_interval=5,
        timeout=300,
    )
    
    print(f"\n✅ Adapter 创建成功")
    print(f"   Token: {TOKEN[:20]}...")
    print(f"   Model: {adapter.model}")
    print(f"   Max Retries: {adapter.max_retries}")
    print(f"   Poll Interval: {adapter.poll_interval}s")
    print(f"   Timeout: {adapter.timeout}s")
    
    # 测试 URL（你可以替换为实际的图片 URL）
    print("\n" + "=" * 60)
    print("测试说明")
    print("=" * 60)
    print("\n要测试 OCR 功能，请提供一个图片：")
    print("1. 本地文件路径，例如：C:\\path\\to\\homework.jpg")
    print("2. 图片 URL，例如：https://example.com/homework.jpg")
    print("\n修改下面的 file_path 变量，然后运行此脚本。")
    
    # ⚠️ 在这里填入你的测试图片路径或 URL
    file_path = None  # 例如: "C:\\Users\\q2414\\Desktop\\test.jpg"
    
    if file_path is None:
        print("\n⚠️  请先设置 file_path 变量")
        print("   编辑此文件，将 file_path = None 改为实际的图片路径")
        return
    
    print(f"\n正在处理: {file_path}")
    print("请稍候...")
    
    try:
        result = adapter.process_file(
            file_path=file_path,
            file_id="test_001",
        )
        
        print("\n" + "=" * 60)
        print("✅ OCR 成功！")
        print("=" * 60)
        
        print(f"\n📊 基本信息:")
        print(f"   文件 ID: {result.file_id}")
        print(f"   提供商: {result.provider}")
        print(f"   提取页数: {result.extracted_pages}")
        print(f"   置信度: {result.confidence:.2%}")
        print(f"   图片数量: {len(result.images)}")
        
        if result.start_time and result.end_time:
            print(f"   开始时间: {result.start_time}")
            print(f"   结束时间: {result.end_time}")
        
        print(f"\n📝 文本内容 (前 500 字符):")
        print("-" * 60)
        print(result.raw_text[:500])
        if len(result.raw_text) > 500:
            print("...")
        
        print(f"\n📄 Markdown 内容 (前 500 字符):")
        print("-" * 60)
        print(result.markdown[:500])
        if len(result.markdown) > 500:
            print("...")
        
        if result.images:
            print(f"\n🖼️  图片列表:")
            print("-" * 60)
            for img_path, img_url in list(result.images.items())[:5]:
                print(f"   {img_path}: {img_url[:60]}...")
            if len(result.images) > 5:
                print(f"   ... 还有 {len(result.images) - 5} 张图片")
        
        print("\n" + "=" * 60)
        print("测试完成！")
        print("=" * 60)
        
    except OCRException as e:
        print("\n" + "=" * 60)
        print("❌ OCR 失败")
        print("=" * 60)
        print(f"\n错误信息: {e}")
        print("\n可能的原因:")
        print("1. 文件路径不存在")
        print("2. 图片 URL 无法访问")
        print("3. Token 无效或过期")
        print("4. 网络连接问题")
        print("5. PaddleOCR API 服务异常")
    
    except Exception as e:
        print("\n" + "=" * 60)
        print("❌ 未知错误")
        print("=" * 60)
        print(f"\n错误信息: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
