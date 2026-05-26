# 批改字段补充完成

## 概述

已按照要求在 AI 分析管道中补充了以下字段：
- `steps`: 解题步骤数组
- `review_suggestions`: 复习建议列表
- `error_type`: 错因类型
- `grade`: 年级

## 修改的文件

### 1. 数据库模型 (`src/models/grading.py`)

#### `AssignmentAnalysis` 模型
新增字段：
- `grade: str | None` - 年级（如"八年级 上"）

#### `GradingResult` 模型
新增字段：
- `steps: list` - 解题步骤数组，JSONB 类型，格式：`[{title: str, detail: str}, ...]`
- `review_suggestions: list` - 复习建议列表，JSONB 类型
- `error_type: str | None` - 错因类型（如"概念混淆"）
- `grade: str | None` - 年级（如"八年级 上"）

### 2. AI 分析服务 (`src/services/ai_analysis_service.py`)

#### `QuestionAnalysis` 数据类
新增字段：
- `steps: List[Dict[str, str]]` - 解题步骤数组
- `review_suggestions: List[str]` - 复习建议列表
- `error_type: str` - 错因类型

#### 所有 AI Provider 的 system_prompt
已更新所有 Provider（OpenAI, Doubao, DoubaoSeed, MiniMax）的 system prompt，要求 AI 输出新增字段：

```
- steps: 解题步骤数组（[{title: "步骤1", detail: "详细说明"}, ...]）
- review_suggestions: 复习建议列表（数组，如["复习欧姆定律公式", "练习串并联电路"]）
- error_type: 错因类型（如"概念混淆"、"计算错误"、"公式记忆错误"等）
```

#### 解析方法更新
- `_parse_analysis()` - 已更新以解析新字段
- `_dict_to_analysis()` - 已更新以处理缓存中的新字段

### 3. 数据库迁移

创建了新的 Alembic 迁移文件：
- 文件：`alembic/versions/c063c0c8419f_add_steps_review_suggestions_error_type_.py`
- Revision ID: `c063c0c8419f`
- 依赖：`grading_20260525`

迁移内容：
- `assignment_analyses` 表新增 `grade` 字段
- `grading_results` 表新增 `steps`, `review_suggestions`, `error_type`, `grade` 字段

## 字段说明

### `steps` - 解题步骤
- 类型：JSONB 数组
- 格式：`[{title: "步骤1", detail: "详细说明"}, {title: "步骤2", detail: "详细说明"}, ...]`
- 示例：
  ```json
  [
    {"title": "分析题意", "detail": "根据题目条件，电路为串联电路，已知电压和电阻"},
    {"title": "应用欧姆定律", "detail": "I = U / R = 12V / 6Ω = 2A"},
    {"title": "得出结论", "detail": "电路中的电流为 2A"}
  ]
  ```

### `review_suggestions` - 复习建议
- 类型：JSONB 数组
- 格式：字符串数组
- 示例：
  ```json
  ["复习欧姆定律公式 I=U/R", "练习串并联电路的识别", "掌握电路图的分析方法"]
  ```

### `error_type` - 错因类型
- 类型：字符串
- 常见值：
  - "概念混淆"
  - "计算错误"
  - "公式记忆错误"
  - "审题不清"
  - "粗心大意"
  - "知识点遗忘"

### `grade` - 年级
- 类型：字符串
- 格式：如"八年级 上"、"九年级 下"、"高一"
- 说明：在 OCR/AI 分析阶段识别并写入

## 下一步

现在这些字段已经在数据库模型和 AI 分析服务中准备好了。

**请 Claude Code 完成：**
1. 运行数据库迁移：`alembic upgrade head`
2. 更新 `/api/grading/{id}` 的响应 schema，将这些字段暴露给前端
3. 前端即可接收并展示这些数据

## 测试建议

1. 测试 AI 分析是否正确返回新字段
2. 测试数据库写入是否正常
3. 测试 API 响应是否包含新字段
4. 验证前端能否正确展示解题步骤和复习建议

## 注意事项

- 所有新字段都是可选的（nullable=True 或有默认值）
- `steps` 和 `review_suggestions` 默认为空数组 `[]`
- AI 可能不总是返回这些字段，代码已做好容错处理
- 缓存逻辑已更新，支持新字段的缓存和读取
