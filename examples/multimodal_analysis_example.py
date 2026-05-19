"""
多模态 AI 分析示例

演示如何使用豆包或 MiniMax 进行多模态分析（文本 + 图片）
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.adapters.ocr import PaddleOCRAdapter, OCRResult
from src.services.ai_analysis_service import (
    AIAnalysisService,
    DoubaoProvider,
    DoubaoSeedProvider,
    MinimaxProvider,
    OpenAIProvider,
)


def main():
    """主函数"""
    print("=" * 60)
    print("多模态 AI 分析示例")
    print("=" * 60)
    
    # 选择 AI Provider
    print("\n请选择 AI Provider:")
    print("0. 豆包 Seed1.8（火山引擎 Responses API）⭐ 推荐 - 支持多模态")
    print("1. 豆包（字节跳动）- 支持多模态")
    print("2. MiniMax - 支持多模态")
    print("3. OpenAI - 仅文本")
    
    choice = input("\n请输入选择 (0/1/2/3): ").strip()
    
    provider = None
    
    if choice == "0":
        # 豆包 Seed1.8
        api_key = os.getenv("DOUBAO_SEED_API_KEY")
        if not api_key:
            print("\n⚠️  请设置 DOUBAO_SEED_API_KEY 环境变量")
            return

        provider = DoubaoSeedProvider(
            api_key=api_key,
            model=os.getenv("DOUBAO_SEED_MODEL", "ep-20260518173637-nhzdp"),
            base_url=os.getenv("DOUBAO_SEED_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        )
        print(f"\n✅ 使用豆包 Seed1.8 Provider（Responses API）")

    elif choice == "1":
        # 豆包
        api_key = os.getenv("DOUBAO_API_KEY")
        if not api_key:
            print("\n⚠️  请设置 DOUBAO_API_KEY 环境变量")
            return
        
        provider = DoubaoProvider(
            api_key=api_key,
            model=os.getenv("DOUBAO_MODEL", "doubao-pro-32k"),
            base_url=os.getenv("DOUBAO_BASE_URL", "https://ark.cn-beijing.volces.com/api/v3"),
        )
        print(f"\n✅ 使用豆包 Provider")
        
    elif choice == "2":
        # MiniMax
        api_key = os.getenv("MINIMAX_API_KEY")
        group_id = os.getenv("MINIMAX_GROUP_ID")
        
        if not api_key or not group_id:
            print("\n⚠️  请设置 MINIMAX_API_KEY 和 MINIMAX_GROUP_ID 环境变量")
            return
        
        provider = MinimaxProvider(
            api_key=api_key,
            group_id=group_id,
            model=os.getenv("MINIMAX_MODEL", "abab6.5s-chat"),
            base_url=os.getenv("MINIMAX_BASE_URL", "https://api.minimax.chat/v1"),
        )
        print(f"\n✅ 使用 MiniMax Provider")
        
    elif choice == "3":
        # OpenAI
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            print("\n⚠️  请设置 OPENAI_API_KEY 环境变量")
            return
        
        provider = OpenAIProvider(
            api_key=api_key,
            model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        )
        print(f"\n✅ 使用 OpenAI Provider（仅文本）")
    else:
        print("\n❌ 无效选择")
        return
    
    # 创建 AI 分析服务
    ai_service = AIAnalysisService(
        provider=provider,
        enable_cache=True,
    )
    
    # 示例 1：纯文本分析
    print("\n" + "=" * 60)
    print("示例 1：纯文本题目分析")
    print("=" * 60)
    
    question_text = """
如图所示，一个三角形 ABC，其中 AB = 5cm，BC = 12cm，AC = 13cm。
求三角形 ABC 的面积。
    """.strip()
    
    question_markdown = f"""# 数学题目

{question_text}

**提示：** 这是一个直角三角形。
"""
    
    try:
        analysis = ai_service.analyze_question(
            question_text=question_text,
            question_markdown=question_markdown,
        )
        
        print(f"\n✅ 分析成功！")
        print(f"\n📊 分析结果:")
        print(f"   学科: {analysis.subject}")
        print(f"   年级: {analysis.grade}")
        print(f"   题型: {analysis.question_type}")
        print(f"   难度: {analysis.difficulty}/5")
        
        print(f"\n📚 知识点:")
        for kp in analysis.knowledge_points:
            print(f"   - {kp}")
        
    except Exception as e:
        print(f"\n❌ 分析失败: {e}")
    
    # 示例 2：多模态分析（文本 + 图片）
    if choice in ["0", "1", "2"]:  # 豆包 Seed1.8、豆包、MiniMax 都支持多模态
        print("\n" + "=" * 60)
        print("示例 2：多模态分析（文本 + 图片）")
        print("=" * 60)
        
        # 模拟 OCR 结果中的图片
        image_urls = [
            "https://example.com/triangle.jpg",  # 替换为实际图片 URL
        ]
        
        question_with_image = """
如图所示，求三角形的面积。
        """.strip()
        
        try:
            analysis = ai_service.analyze_question(
                question_text=question_with_image,
                question_markdown=f"# 题目\n\n{question_with_image}",
                image_urls=image_urls,
            )
            
            print(f"\n✅ 多模态分析成功！")
            print(f"\n📊 分析结果:")
            print(f"   学科: {analysis.subject}")
            print(f"   知识点: {', '.join(analysis.knowledge_points)}")
            print(f"   难度: {analysis.difficulty}/5")
            
        except Exception as e:
            print(f"\n❌ 分析失败: {e}")
    
    # 示例 3：完整流程（OCR + AI 分析）
    print("\n" + "=" * 60)
    print("示例 3：完整流程（OCR + AI 多模态分析）")
    print("=" * 60)
    
    print("\n⚠️  要测试完整流程，请提供作业图片路径")
    image_path = input("请输入图片路径（或按回车跳过）: ").strip()
    
    if image_path and os.path.exists(image_path):
        try:
            # 1. OCR 识别
            print("\n1. OCR 识别中...")
            paddleocr_token = os.getenv("PADDLEOCR_TOKEN", "9b7fe06ddc38194934d1f8bbaa94f930c3d80d76")
            ocr_adapter = PaddleOCRAdapter(token=paddleocr_token)
            
            ocr_result = ocr_adapter.process_file(image_path, "hw_001")
            print(f"   ✅ OCR 成功，置信度: {ocr_result.confidence:.2%}")
            print(f"   提取到 {len(ocr_result.images)} 张图片")
            
            # 2. AI 分析（包含图片）
            print("\n2. AI 多模态分析中...")
            
            # 提取图片 URL
            image_urls = list(ocr_result.images.values()) if ocr_result.images else None
            
            analysis = ai_service.analyze_question(
                question_text=ocr_result.raw_text,
                question_markdown=ocr_result.markdown,
                image_urls=image_urls,
            )
            print(f"   ✅ 分析成功")
            
            # 3. 输出结果
            print(f"\n📊 完整分析结果:")
            print(f"   学科: {analysis.subject}")
            print(f"   年级: {analysis.grade}")
            print(f"   题型: {analysis.question_type}")
            print(f"   知识点: {', '.join(analysis.knowledge_points)}")
            print(f"   难度: {analysis.difficulty}/5")
            print(f"   复习优先级: {analysis.review_priority}")
            print(f"   置信度: {analysis.confidence:.2%}")
            
            if analysis.likely_error_causes:
                print(f"\n⚠️  可能错因:")
                for cause in analysis.likely_error_causes:
                    print(f"   - {cause}")
            
        except Exception as e:
            print(f"\n❌ 处理失败: {e}")
            import traceback
            traceback.print_exc()
    else:
        print("   跳过（未提供图片路径）")
    
    print("\n" + "=" * 60)
    print("示例完成！")
    print("=" * 60)
    
    print("\n💡 提示:")
    print("   - 豆包和 MiniMax 支持多模态分析（文本 + 图片）")
    print("   - 对于包含几何图形、图表的题目，多模态分析更准确")
    print("   - OCR 识别的图片会自动传递给 AI 进行分析")


if __name__ == "__main__":
    main()
