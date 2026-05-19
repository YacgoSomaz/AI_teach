# API 文档

所有接口均需携带 `X-Student-Id` Header 做身份校验。路径中的 `{student_id}` 必须与 Header 值一致，否则返回 404。

---

## 学生画像

### GET /api/students/{student_id}/profile

获取学生知识点掌握全貌。

**Response 200**
```json
{
  "student_id": "stu_001",
  "total_knowledge_points": 10,
  "overall_mastery": 0.65,
  "weak_count": 3,
  "knowledge_points": [
    {
      "knowledge_point_id": "uuid",
      "knowledge_point_name": "三角函数",
      "subject": "数学",
      "grade": "八年级",
      "mastery_score": 0.3,
      "review_priority": "high"
    }
  ]
}
```

---

### GET /api/students/{student_id}/weak-points

分页查询掌握度薄弱的知识点（mastery_score < 0.6）。

**Query Parameters**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| page | int | 1 | 页码 |
| page_size | int | 20 | 每页数量（最大 100）|

**Response 200**
```json
{
  "student_id": "stu_001",
  "total": 3,
  "page": 1,
  "page_size": 10,
  "items": [
    {
      "knowledge_point_id": "uuid",
      "knowledge_point_name": "三角函数",
      "subject": "数学",
      "mastery_score": 0.2,
      "appear_count": 5,
      "error_count": 4
    }
  ]
}
```

---

### GET /api/students/{student_id}/progress

获取学生各优先级知识点数量分布。

**Response 200**
```json
{
  "student_id": "stu_001",
  "total_knowledge_points": 10,
  "weak_count": 3,
  "medium_count": 4,
  "strong_count": 3,
  "priority_high_count": 2,
  "priority_medium_count": 5,
  "priority_low_count": 3
}
```

---

## 复习任务

### GET /api/students/{student_id}/review-tasks

获取今日复习任务列表。

**Query Parameters**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| max_tasks | int | 5 | 最多返回任务数（1-20）|

**Response 200**
```json
{
  "student_id": "stu_001",
  "date": "2026-05-19",
  "tasks": [
    {
      "knowledge_point_id": "uuid",
      "knowledge_point_name": "三角函数",
      "subject": "数学",
      "grade": "八年级",
      "mastery_score": 0.2,
      "priority": "high",
      "reason": "掌握度低，需重点复习",
      "recommended_count": 5,
      "estimated_minutes": 25
    }
  ],
  "total_minutes": 25
}
```

---

## 学习报告

### GET /api/reports/student/{student_id}

获取完整学生报告（含内部分级数据）。

**Query Parameters**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| top_n | int | 5 | 薄弱/优秀知识点返回数量（1-20）|

**Response 200**
```json
{
  "student_id": "stu_001",
  "generated_at": "2026-05-19T10:00:00",
  "total_knowledge_points": 10,
  "overall_mastery": 0.6,
  "weak_count": 3,
  "medium_count": 4,
  "strong_count": 3,
  "subjects": [
    {
      "subject": "数学",
      "total": 6,
      "weak_count": 2,
      "medium_count": 3,
      "strong_count": 1,
      "average_mastery": 0.55,
      "average_error_rate": 0.35
    }
  ],
  "top_weak_points": [...],
  "top_strong_points": [...]
}
```

---

### GET /api/reports/parent/{student_id}

获取家长视角报告（隐藏内部分级细节，薄弱点只展示名称和掌握度）。

**Query Parameters**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| top_n | int | 3 | 薄弱知识点返回数量（1-10）|

**Response 200**
```json
{
  "student_id": "stu_001",
  "generated_at": "2026-05-19T10:00:00",
  "total_knowledge_points": 10,
  "overall_mastery": 0.6,
  "weak_count": 3,
  "subjects": [
    {
      "subject": "数学",
      "total": 6,
      "average_mastery": 0.55
    }
  ],
  "top_weak_points": [
    {
      "knowledge_point_name": "三角函数",
      "subject": "数学",
      "grade": "八年级",
      "mastery_score": 0.2,
      "mastery_level": "weak",
      "review_priority": "high"
    }
  ]
}
```

---

## 数据导出

### GET /api/export/student/{student_id}/knowledge-points

导出知识点掌握数据。

**Query Parameters**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| format | string | json | 导出格式：`json` / `csv` / `excel` |

返回对应格式的文件下载（Content-Disposition: attachment）。

---

### GET /api/export/student/{student_id}/questions

导出题目记录。

**Query Parameters**

| 参数 | 类型 | 默认 | 说明 |
|------|------|------|------|
| format | string | json | 导出格式：`json` / `csv` / `excel` |

**JSON Response 200**
```json
{
  "student_id": "stu_001",
  "exported_at": "2026-05-19T10:00:00",
  "total": 25,
  "questions": [
    {
      "question_id": "uuid",
      "raw_text": "解方程 x+1=0",
      "subject": "数学",
      "grade": "八年级",
      "question_type": "填空题",
      "difficulty": 2,
      "review_priority": "high",
      "need_review": "True"
    }
  ]
}
```

---

## 可视化数据

### GET /api/visualization/student/{student_id}/radar

按学科聚合平均掌握度，用于雷达图。

**Response 200**
```json
{ "labels": ["数学", "物理", "生物"], "values": [0.65, 0.72, 0.58] }
```

---

### GET /api/visualization/student/{student_id}/heatmap

按日期统计复习次数，用于热力图。

**Response 200**
```json
{ "dates": ["2026-05-01", "2026-05-10"], "counts": [3, 5] }
```

---

### GET /api/visualization/student/{student_id}/progress-line

按日期聚合平均掌握度，用于折线图。

**Response 200**
```json
{ "dates": ["2026-05-01", "2026-05-10"], "mastery_scores": [0.45, 0.60] }
```

---

## 错误码

| HTTP 状态码 | 说明 |
|------------|------|
| 404 | 学生 ID 与 Header 不匹配（IDOR 防护），或资源不存在 |
| 422 | 请求参数校验失败（如 format 传了不支持的值）|
| 500 | 服务端内部错误 |
