"""
快速测试：验证新增的批改字段

测试内容：
1. QuestionAnalysis 数据类包含新字段
2. AI 分析服务能正确解析新字段
3. 数据库模型包含新字段
"""

import sys
from dataclasses import asdict

# 测试 1: QuestionAnalysis 数据类
from src.services.ai_analysis_service import QuestionAnalysis

def test_question_analysis_dataclass():
    """测试 QuestionAnalysis 包含新字段"""
    analysis = QuestionAnalysis(
        subject="物理",
        grade="八年级 上",
        question_type="计算题",
        knowledge_points=["欧姆定律"],
        prerequisites=["电流", "电压", "电阻"],
        difficulty=3,
        likely_error_causes=["公式记忆错误"],
        review_priority="high",
        need_review=True,
        confidence=0.9,
        steps=[
            {"title": "分析题意", "detail": "识别电路类型"},
            {"title": "应用公式", "detail": "I = U / R"}
        ],
        review_suggestions=["复习欧姆定律", "练习串并联电路"],
        error_type="概念混淆"
    )
    
    # 验证字段存在
    assert hasattr(analysis, 'steps')
    assert hasattr(analysis, 'review_suggestions')
    assert hasattr(analysis, 'error_type')
    assert hasattr(analysis, 'grade')
    
    # 验证值正确
    assert analysis.steps == [
        {"title": "分析题意", "detail": "识别电路类型"},
        {"title": "应用公式", "detail": "I = U / R"}
    ]
    assert analysis.review_suggestions == ["复习欧姆定律", "练习串并联电路"]
    assert analysis.error_type == "概念混淆"
    assert analysis.grade == "八年级 上"
    
    print("✓ QuestionAnalysis 数据类测试通过")


# 测试 2: 数据库模型
from src.models.grading import GradingResult, AssignmentAnalysis

def test_grading_models():
    """测试数据库模型包含新字段"""
    # 检查 GradingResult 模型
    grading_result_columns = [col.name for col in GradingResult.__table__.columns]
    assert 'steps' in grading_result_columns
    assert 'review_suggestions' in grading_result_columns
    assert 'error_type' in grading_result_columns
    assert 'grade' in grading_result_columns
    
    # 检查 AssignmentAnalysis 模型
    assignment_analysis_columns = [col.name for col in AssignmentAnalysis.__table__.columns]
    assert 'grade' in assignment_analysis_columns
    
    print("✓ 数据库模型测试通过")


# 测试 3: AI 分析服务解析
from src.services.ai_analysis_service import AIAnalysisService

def test_ai_service_parsing():
    """测试 AI 分析服务能正确解析新字段"""
    # 模拟 AI 返回的原始结果
    raw_result = {
        "subject": "数学",
        "grade": "九年级 下",
        "question_type": "证明题",
        "knowledge_points": ["勾股定理"],
        "prerequisites": ["直角三角形"],
        "difficulty": 4,
        "likely_error_causes": ["证明步骤不完整"],
        "review_priority": "high",
        "need_review": True,
        "confidence": 0.85,
        "steps": [
            {"title": "已知条件", "detail": "直角三角形ABC，∠C=90°"},
            {"title": "求证", "detail": "a² + b² = c²"}
        ],
        "review_suggestions": ["复习勾股定理证明", "练习相似三角形"],
        "error_type": "证明逻辑错误"
    }
    
    # 创建一个 mock provider 来测试解析
    class MockProvider:
        def analyze_question(self, question_text, question_markdown):
            return raw_result
    
    service = AIAnalysisService(provider=MockProvider(), enable_cache=False)
    
    # 测试 _parse_analysis 方法
    analysis = service._parse_analysis(raw_result)
    
    assert analysis.steps == [
        {"title": "已知条件", "detail": "直角三角形ABC，∠C=90°"},
        {"title": "求证", "detail": "a² + b² = c²"}
    ]
    assert analysis.review_suggestions == ["复习勾股定理证明", "练习相似三角形"]
    assert analysis.error_type == "证明逻辑错误"
    assert analysis.grade == "九年级 下"
    
    print("✓ AI 分析服务解析测试通过")


if __name__ == "__main__":
    try:
        test_question_analysis_dataclass()
        test_grading_models()
        test_ai_service_parsing()
        print("\n✅ 所有测试通过！新字段已成功添加。")
    except AssertionError as e:
        print(f"\n❌ 测试失败：{e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ 测试出错：{e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
