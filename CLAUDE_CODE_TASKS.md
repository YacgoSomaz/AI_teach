# Claude Code 任务清单

## 🎯 总体目标

负责 **API 接口设计**、**报告生成服务** 和 **数据可视化**，让用户能够查询学生画像、生成报告、导出数据。

---

## 📋 任务优先级

### P0 - 高优先级（本周完成）

#### 任务 1：学生画像查询 API

**文件：** `src/api/student.py`

**需要实现的接口：**

```python
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from src.db.session import get_db

router = APIRouter(prefix="/api/students", tags=["student"])

@router.get("/{student_id}/profile")
async def get_student_profile(
    student_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    获取学生画像
    
    返回：
    {
        "student_id": "xxx",
        "total_questions": 100,
        "correct_rate": 0.85,
        "knowledge_points": [
            {
                "name": "二次函数",
                "mastery_level": 0.8,
                "question_count": 15,
                "correct_count": 12
            }
        ],
        "weak_points": ["三角函数", "立体几何"],
        "updated_at": "2025-01-20T10:00:00"
    }
    """
    pass

@router.get("/{student_id}/weak-points")
async def get_weak_points(
    student_id: str,
    limit: int = 5,
    db: AsyncSession = Depends(get_db)
):
    """
    获取学生薄弱知识点（掌握度 < 0.6）
    
    返回：
    {
        "student_id": "xxx",
        "weak_points": [
            {
                "knowledge_point": "三角函数",
                "mastery_level": 0.45,
                "question_count": 10,
                "correct_count": 4,
                "last_practice": "2025-01-15T10:00:00"
            }
        ]
    }
    """
    pass

@router.get("/{student_id}/progress")
async def get_learning_progress(
    student_id: str,
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """
    获取学生学习进度（最近 N 天）
    
    返回：
    {
        "student_id": "xxx",
        "period": "30 days",
        "total_questions": 50,
        "correct_rate": 0.82,
        "daily_stats": [
            {
                "date": "2025-01-20",
                "questions": 5,
                "correct": 4
            }
        ]
    }
    """
    pass
```

**数据库查询提示：**
- 使用 `StudentKnowledgeProfile` 模型
- 使用 `Question` 模型统计题目数量
- 计算掌握度：`correct_count / question_count`

**测试文件：** `tests/api/test_student_api.py`

---

#### 任务 2：复习任务查询 API

**文件：** `src/api/review.py`

**需要实现的接口：**

```python
@router.get("/api/students/{student_id}/review-tasks")
async def get_review_tasks(
    student_id: str,
    date: str = None,  # 格式：YYYY-MM-DD，默认今天
    db: AsyncSession = Depends(get_db)
):
    """
    获取学生今日复习任务
    
    返回：
    {
        "student_id": "xxx",
        "date": "2025-01-20",
        "tasks": [
            {
                "knowledge_point": "三角函数",
                "priority": "high",  # high/medium/low
                "reason": "掌握度低（45%），需要重点复习",
                "recommended_questions": 5,
                "estimated_time": 15  # 分钟
            }
        ],
        "total_time": 45  # 分钟
    }
    """
    pass

@router.post("/api/students/{student_id}/review-tasks/{task_id}/complete")
async def complete_review_task(
    student_id: str,
    task_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    标记复习任务完成
    """
    pass
```

**复习任务生成逻辑：**
1. 查询薄弱知识点（掌握度 < 0.6）
2. 按掌握度排序（越低优先级越高）
3. 考虑最后练习时间（超过 7 天的优先）
4. 生成每日 3-5 个复习任务

---

### P1 - 中优先级（下周完成）

#### 任务 3：报告生成服务

**文件：** `src/services/report_service.py`

**需要实现的服务：**

```python
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

@dataclass
class StudentReport:
    """学生报告"""
    student_id: str
    period: str  # "week" / "month"
    start_date: datetime
    end_date: datetime
    
    # 统计数据
    total_questions: int
    correct_rate: float
    improvement: float  # 相比上期提升
    
    # 知识点分析
    strong_points: list[str]
    weak_points: list[str]
    
    # 学习建议
    suggestions: list[str]

class ReportService:
    async def generate_student_report(
        self,
        student_id: str,
        period: Literal["week", "month"] = "week"
    ) -> StudentReport:
        """生成学生报告"""
        pass
    
    async def generate_parent_report(
        self,
        student_id: str,
        period: Literal["week", "month"] = "week"
    ) -> dict:
        """
        生成家长报告（更简洁，重点关注进步和问题）
        """
        pass
    
    async def export_report_pdf(
        self,
        report: StudentReport,
        output_path: str
    ) -> str:
        """导出 PDF 报告（可选，使用 reportlab 或 weasyprint）"""
        pass
```

**报告 API：**

```python
# src/api/report.py
@router.get("/api/reports/student/{student_id}")
async def get_student_report(
    student_id: str,
    period: str = "week",  # week/month
    format: str = "json",  # json/pdf
    db: AsyncSession = Depends(get_db)
):
    """获取学生报告"""
    pass

@router.get("/api/reports/parent/{student_id}")
async def get_parent_report(
    student_id: str,
    period: str = "week",
    db: AsyncSession = Depends(get_db)
):
    """获取家长报告"""
    pass
```

---

#### 任务 4：数据导出功能

**文件：** `src/api/export.py`

**需要实现的接口：**

```python
@router.get("/api/export/student/{student_id}/questions")
async def export_questions(
    student_id: str,
    format: str = "json",  # json/csv/excel
    filter_type: str = "all",  # all/wrong/correct
    db: AsyncSession = Depends(get_db)
):
    """
    导出学生题目记录
    
    支持格式：
    - JSON
    - CSV
    - Excel (使用 openpyxl)
    """
    pass

@router.get("/api/export/student/{student_id}/knowledge-points")
async def export_knowledge_points(
    student_id: str,
    format: str = "json",
    db: AsyncSession = Depends(get_db)
):
    """导出学生知识点掌握情况"""
    pass
```

**导出格式示例：**

CSV 格式：
```csv
题目ID,题目内容,知识点,难度,是否正确,提交时间
q001,"求解方程 x^2 + 2x + 1 = 0","二次方程",medium,true,2025-01-20 10:00:00
```

Excel 格式：
- Sheet1: 题目列表
- Sheet2: 知识点统计
- Sheet3: 学习进度图表

---

### P2 - 低优先级（可选）

#### 任务 5：数据可视化 API

**文件：** `src/api/visualization.py`

**需要实现的接口：**

```python
@router.get("/api/visualization/student/{student_id}/radar")
async def get_radar_chart_data(
    student_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    获取雷达图数据（知识点掌握度）
    
    返回：
    {
        "labels": ["代数", "几何", "函数", "概率", "统计"],
        "values": [0.85, 0.65, 0.75, 0.90, 0.70]
    }
    """
    pass

@router.get("/api/visualization/student/{student_id}/heatmap")
async def get_heatmap_data(
    student_id: str,
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """
    获取热力图数据（每日练习情况）
    
    返回：
    {
        "dates": ["2025-01-01", "2025-01-02", ...],
        "values": [5, 3, 0, 8, ...]  # 每日题目数量
    }
    """
    pass

@router.get("/api/visualization/student/{student_id}/progress-line")
async def get_progress_line_data(
    student_id: str,
    days: int = 30,
    db: AsyncSession = Depends(get_db)
):
    """
    获取折线图数据（正确率趋势）
    
    返回：
    {
        "dates": ["2025-01-01", "2025-01-02", ...],
        "correct_rates": [0.80, 0.85, 0.82, ...]
    }
    """
    pass
```

---

## 🛠️ 技术栈和工具

### 必需依赖

```bash
# 已安装
fastapi==0.109.0
sqlalchemy==2.0.49
pydantic==2.5.3

# 需要添加（报告生成）
reportlab==4.0.7  # PDF 生成
openpyxl==3.1.2   # Excel 导出
pandas==2.1.4     # 数据处理
```

### 可选依赖（可视化）

```bash
matplotlib==3.8.2  # 图表生成
plotly==5.18.0     # 交互式图表
```

---

## 📝 开发规范

### API 响应格式

**成功响应：**
```json
{
    "success": true,
    "data": { ... },
    "message": "操作成功"
}
```

**错误响应：**
```json
{
    "success": false,
    "error": {
        "code": "STUDENT_NOT_FOUND",
        "message": "学生不存在"
    }
}
```

### 错误码定义

```python
# src/api/errors.py
class ErrorCode:
    STUDENT_NOT_FOUND = "STUDENT_NOT_FOUND"
    INVALID_DATE_FORMAT = "INVALID_DATE_FORMAT"
    REPORT_GENERATION_FAILED = "REPORT_GENERATION_FAILED"
    EXPORT_FAILED = "EXPORT_FAILED"
```

### 分页规范

```python
@router.get("/api/students/{student_id}/questions")
async def get_questions(
    student_id: str,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db)
):
    """
    返回：
    {
        "items": [...],
        "total": 100,
        "page": 1,
        "page_size": 20,
        "total_pages": 5
    }
    """
    pass
```

---

## 🧪 测试要求

### 单元测试

**文件：** `tests/api/test_student_api.py`

```python
import pytest
from httpx import AsyncClient

@pytest.mark.asyncio
async def test_get_student_profile(client: AsyncClient):
    """测试获取学生画像"""
    response = await client.get("/api/students/test_student/profile")
    assert response.status_code == 200
    data = response.json()
    assert "student_id" in data
    assert "knowledge_points" in data

@pytest.mark.asyncio
async def test_get_weak_points(client: AsyncClient):
    """测试获取薄弱知识点"""
    response = await client.get("/api/students/test_student/weak-points")
    assert response.status_code == 200
    data = response.json()
    assert "weak_points" in data
```

### 集成测试

**文件：** `tests/integration/test_report_flow.py`

```python
@pytest.mark.asyncio
async def test_report_generation_flow(client: AsyncClient):
    """测试报告生成完整流程"""
    # 1. 上传作业
    # 2. 等待 OCR 和 AI 分析完成
    # 3. 查询学生画像
    # 4. 生成报告
    # 5. 导出报告
    pass
```

---

## 📚 API 文档

### 使用 FastAPI 自动生成

访问 `http://localhost:8000/docs` 查看 Swagger UI

### 手动编写文档

**文件：** `docs/API.md`

需要包含：
- 接口列表
- 请求参数
- 响应示例
- 错误码说明

---

## 🚀 开发流程

### 1. 创建分支

```bash
git checkout -b feature/claude-student-api
```

### 2. 实现功能

按照任务清单逐个实现

### 3. 编写测试

确保测试覆盖率 > 80%

### 4. 运行测试

```bash
pytest tests/api/ -v
```

### 5. 提交 PR

```bash
git add .
git commit -m "feat: implement student profile API"
git push origin feature/claude-student-api
```

### 6. Code Review

等待 Kiro Review 后合并

---

## 🤝 与 Kiro 的协作接口

### Kiro 提供的服务（你可以直接调用）

```python
# src/services/student_profile_service.py
from src.services.student_profile_service import StudentProfileService

service = StudentProfileService()

# 获取学生画像
profile = await service.get_profile(student_id)

# 获取薄弱知识点
weak_points = await service.get_weak_points(student_id, limit=5)

# 获取学习进度
progress = await service.get_progress(student_id, days=30)
```

### 你需要提供的接口（供前端调用）

所有 `/api/students/*` 和 `/api/reports/*` 接口

---

## 📊 预期成果

### 第一阶段完成后

- ✅ 用户可以查询学生画像
- ✅ 用户可以查询薄弱知识点
- ✅ 用户可以查询学习进度
- ✅ 用户可以查询复习任务

### 第二阶段完成后

- ✅ 用户可以生成学生报告
- ✅ 用户可以生成家长报告
- ✅ 用户可以导出数据（JSON/CSV/Excel）

### 最终目标

**让用户能够清晰地看到学生的学习情况，知道"今天该复习哪里"！** 🎯

---

## 💬 有问题？

- 在 GitHub Issue 中提问
- 或者直接在 PR 中讨论

**祝开发顺利！** 🚀
