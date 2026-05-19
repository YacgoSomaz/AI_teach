# Phase 2 架构重构计划

## 🎯 目标

将架构评分从 ⭐⭐⭐ (3/5) 提升到 ⭐⭐⭐⭐ (4/5)

**核心改进**：
1. 事件驱动架构 - 完全解耦任务链
2. 接口抽象 - 易于测试和替换
3. 重试策略优化 - 指数退避

---

## 📋 Phase 2 任务清单

### 1. 事件驱动架构（核心）

#### 1.1 创建事件系统
- [ ] `src/events/__init__.py` - 事件模块初始化
- [ ] `src/events/base.py` - 事件基类
- [ ] `src/events/types.py` - 事件类型定义
- [ ] `src/events/bus.py` - 事件总线（基于 Celery）

#### 1.2 定义事件
- [ ] `OCRCompletedEvent` - OCR 完成事件
- [ ] `AIAnalysisCompletedEvent` - AI 分析完成事件
- [ ] `QuestionCreatedEvent` - 题目创建事件

#### 1.3 改造任务为事件监听器
- [ ] 修改 `ocr_tasks.py` - 发布事件而非直接调用
- [ ] 修改 `ai_tasks.py` - 监听事件而非被直接调用
- [ ] 新增事件处理器注册机制

### 2. 接口抽象

#### 2.1 定义 Provider 接口
- [ ] `src/providers/__init__.py` - Provider 模块
- [ ] `src/providers/ocr.py` - OCR Provider 接口
- [ ] `src/providers/ai.py` - AI Provider 接口

#### 2.2 实现具体 Provider
- [ ] `PaddleOCRProvider` 实现 `OCRProvider` 接口
- [ ] `DoubaoSeedProvider` 实现 `AIProvider` 接口

#### 2.3 依赖注入
- [ ] 任务通过接口而非具体类依赖 Provider
- [ ] 配置中指定使用哪个 Provider

### 3. 重试策略优化

- [ ] 指数退避算法
- [ ] 最大重试次数配置
- [ ] 重试间隔配置

---

## 🏗️ 架构设计

### 当前架构（Phase 1）

```
OCR 任务 --直接调用--> AI 任务 --直接调用--> Profile 任务
```

**问题**：
- 硬编码调用链
- 任务之间紧耦合
- 难以扩展

### 目标架构（Phase 2）

```
OCR 任务 --发布事件--> 事件总线 --分发--> AI 任务监听器
                                    └--> 其他监听器（可扩展）

AI 任务 --发布事件--> 事件总线 --分发--> Profile 任务监听器
                                   └--> 其他监听器（可扩展）
```

**优点**：
- ✅ 完全解耦：任务不知道彼此存在
- ✅ 易于扩展：新增监听器无需修改现有代码
- ✅ 容错性强：某个监听器失败不影响其他监听器
- ✅ 可测试：可以独立测试每个监听器

---

## 📐 事件驱动设计

### 事件定义

```python
# src/events/types.py

class OCRCompletedEvent(BaseEvent):
    """OCR 完成事件"""
    assignment_id: str
    ocr_task_id: str
    confidence: float
    markdown: str
    images: dict

class AIAnalysisCompletedEvent(BaseEvent):
    """AI 分析完成事件"""
    assignment_id: str
    questions: list[dict]
    
class QuestionCreatedEvent(BaseEvent):
    """题目创建事件"""
    question_id: str
    student_id: str
    knowledge_points: list[str]
```

### 事件总线

```python
# src/events/bus.py

class EventBus:
    """事件总线（基于 Celery）"""
    
    def publish(self, event: BaseEvent):
        """发布事件"""
        # 查找所有监听该事件的处理器
        # 异步调用处理器
        
    def subscribe(self, event_type: Type[BaseEvent], handler: Callable):
        """订阅事件"""
        # 注册事件处理器
```

### 事件处理器

```python
# src/tasks/ai_tasks.py

@event_bus.subscribe(OCRCompletedEvent)
async def handle_ocr_completed(event: OCRCompletedEvent):
    """处理 OCR 完成事件"""
    # 触发 AI 分析
    await process_ai_analysis(event.assignment_id)
```

---

## 🔌 接口抽象设计

### OCR Provider 接口

```python
# src/providers/ocr.py

class OCRProvider(ABC):
    """OCR Provider 接口"""
    
    @abstractmethod
    async def process_file(self, file_path: str, file_id: str) -> OCRResult:
        """处理文件，返回 OCR 结果"""
        pass
    
    @abstractmethod
    async def check_status(self, job_id: str) -> OCRStatus:
        """检查任务状态"""
        pass
```

### AI Provider 接口

```python
# src/providers/ai.py

class AIProvider(ABC):
    """AI Provider 接口"""
    
    @abstractmethod
    async def analyze(self, prompt: str, images: list[str] = None) -> str:
        """分析内容，返回结果"""
        pass
```

### 依赖注入

```python
# src/tasks/ocr_tasks.py

async def _process_ocr_async(task, assignment_id: str):
    # 从配置获取 Provider
    ocr_provider = get_ocr_provider()  # 返回 OCRProvider 接口
    
    # 使用接口而非具体类
    ocr_result = await ocr_provider.process_file(file_path, file_id)
```

---

## 🔄 重试策略

### 指数退避

```python
# 当前：固定间隔重试
raise task.retry(exc=e, countdown=60)  # 总是 60 秒

# 改进：指数退避
retry_count = task.request.retries
countdown = min(60 * (2 ** retry_count), 3600)  # 60s, 120s, 240s, ..., 最多 1 小时
raise task.retry(exc=e, countdown=countdown)
```

---

## 📊 预期效果

### 改进前（Phase 1）

- 架构评分：⭐⭐⭐ (3/5)
- 任务链：硬编码调用
- 扩展性：需要修改现有代码
- 测试性：难以 mock

### 改进后（Phase 2）

- 架构评分：⭐⭐⭐⭐ (4/5)
- 任务链：事件驱动，完全解耦
- 扩展性：新增监听器无需修改现有代码
- 测试性：可以独立测试每个组件

---

## 🚀 实施步骤

### Step 1：创建事件系统（1-2 小时）
1. 创建事件基类和类型定义
2. 实现事件总线（基于 Celery）
3. 编写事件系统测试

### Step 2：改造任务为事件驱动（2-3 小时）
1. 修改 OCR 任务发布事件
2. 修改 AI 任务监听事件
3. 修改 Profile 任务监听事件
4. 测试事件流转

### Step 3：接口抽象（1-2 小时）
1. 定义 Provider 接口
2. 改造现有 Provider 实现接口
3. 实现依赖注入
4. 编写接口测试

### Step 4：重试策略优化（30 分钟）
1. 实现指数退避算法
2. 配置最大重试次数
3. 测试重试逻辑

### Step 5：集成测试（1 小时）
1. 端到端测试
2. 性能测试
3. 文档更新

**总计时间**：约 6-9 小时

---

## ✅ 验收标准

Phase 2 完成后应达到：

- [ ] 事件系统正常工作
- [ ] 任务通过事件通信，无直接调用
- [ ] Provider 接口定义清晰
- [ ] 所有 Provider 实现接口
- [ ] 依赖注入正常工作
- [ ] 指数退避重试正常工作
- [ ] 所有测试通过
- [ ] 架构评分达到 4/5

---

## 📝 注意事项

1. **向后兼容**：Phase 2 改造不应破坏现有功能
2. **渐进式改造**：先实现事件系统，再逐步迁移任务
3. **充分测试**：每个步骤完成后都要测试
4. **文档更新**：及时更新架构文档

---

让我们开始吧！🚀
