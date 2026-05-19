"""
AI 分析服务使用示例

演示如何使用 AI 分析服务分析题目
"""

import os
import sys
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.adapters.ocr import PaddleOCRAdapter
from src.services.ai_analysis_service import AIAnalysisService, OpenAIProvider


def main():
    """主函数"""
    print("=" * 60)
    print("AI 分析服务示例")
    print("=" * 60)
    
    # 1. 创建 OCR Adapter
    paddleocr_token = os.getenv("PADDLEOCR_TOKEN", "9b7fe06ddc38194934d1f8bbaa94f930c3d80d76")
    ocr_adapter = PaddleOCRAdapter(token=paddleocr_token)
    
    # 2. 创建 AI 分析服务
    openai_api_key = os.getenv("OPENAI_API_KEY")
    
    if not openai_api_key:
        print("\n⚠️  请设置 OPENAI_API_KEY 环境变量")
        print("   export OPENAI_API_KEY=your_api_key")
        return
    
    ai_provider = OpenAIProvider(
        api_key=openai_api_key,
        model="gpt-4o-mini",  # 使用成本较低的模型
    )
    
    ai_service = AIAnalysisService(
        provider=ai_provider,
        enable_cache=True,  # 启用缓存
    )
    
    print(f"\n✅ AI 分析服务创建成功")
    print(f"   模型: {ai_provider.model}")
    print(f"   缓存: 已启用")
    
    # 3. 示例：分析题目
    print("\n" + "=" * 60)
    print("示例 1：分析物理题目")
    print("=" * 60)
    
    question_text = """
一个物体浸没在水中，排开水的体积为 0.001 立方米，
求该物体受到的浮力大小。（g=10N/kg，水的密度为 1000kg/m³）
    """.strip()
    
    question_markdown = f"""# 物理题目

{question_text}

**选项：**
A. 5N
B. 10N
C. 15N
D. 20N
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
        print(f"   置信度: {analysis.confidence:.2%}")
        
        print(f"\n📚 知识点:")
        for kp in analysis.knowledge_points:
            print(f"   - {kp}")
        
        print(f"\n🔗 前置知识:")
        for pre in analysis.prerequisites:
            print(f"   - {pre}")
        
        print(f"\n⚠️  可能错因:")
        for cause in analysis.likely_error_causes:
            print(f"   - {cause}")
        
        print(f"\n📝 复习建议:")
        print(f"   优先级: {analysis.review_priority}")
        print(f"   需要复习: {'是' if analysis.need_review else '否'}")
        
    except Exception as e:
        print(f"\n❌ 分析失败: {e}")
    
    # 4. 示例：测试缓存
    print("\n" + "=" * 60)
    print("示例 2：测试缓存功能")
    print("=" * 60)
    
    print(f"\n当前缓存大小: {ai_service.get_cache_size()}")
    
    # 再次分析相同题目（应该使用缓存）
    print("\n再次分析相同题目...")
    try:
        analysis2 = ai_service.analyze_question(
            question_text=question_text,
            question_markdown=question_markdown,
        )
        print(f"✅ 使用缓存，分析成功！")
        print(f"   学科: {analysis2.subject}")
    except Exception as e:
        print(f"❌ 分析失败: {e}")
    
    print(f"\n当前缓存大小: {ai_service.get_cache_size()}")
    
    # 5. 示例：完整流程（OCR + AI 分析）
    print("\n" + "=" * 60)
    print("示例 3：完整流程（OCR + AI 分析）")
    print("=" * 60)
    
    print("\n⚠️  要测试完整流程，请提供作业图片路径")
    print("   修改下面的 image_path 变量")
    
    image_path = None  # 例如: "C:\\path\\to\\homework.jpg"
    
    if image_path and os.path.exists(image_path):
        print(f"\n正在处理: {image_path}")
        
        try:
            # OCR 识别
            print("1. OCR 识别中...")
            ocr_result = ocr_adapter.process_file(image_path, "hw_001")
            print(f"   ✅ OCR 成功，置信度: {ocr_result.confidence:.2%}")
            
            # AI 分析
            print("2. AI 分析中...")
            analysis = ai_service.analyze_question(
                question_text=ocr_result.raw_text,
                question_markdown=ocr_result.markdown,
            )
            print(f"   ✅ 分析成功")
            
            # 输出结果
            print(f"\n📊 完整分析结果:")
            print(f"   学科: {analysis.subject}")
            print(f"   知识点: {', '.join(analysis.knowledge_points)}")
            print(f"   难度: {analysis.difficulty}/5")
            print(f"   复习优先级: {analysis.review_priority}")
            
        except Exception as e:
            print(f"   ❌ 处理失败: {e}")
    else:
        print("   跳过（未提供图片路径）")
    
    print("\n" + "=" * 60)
    print("示例完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
