"""
前端 HTML/JS 测试

覆盖范围：
1. 文件存在且可读
2. JS 语法合法（node --check + 静态检查）
3. 轮询终态：ai_done 视为成功，ocr_failed/ai_failed/failed/manual_required 视为失败/人工
4. 步骤推导：inferStepsFromStatus 在各状态下的预期结果
5. 学生画像字段：knowledge_points 能被图表读取（非 knowledge_mastery）
6. 报告字段：overall_mastery / strong_count 能被报告页读取
7. DOM 结构完整性
8. API 路径一致性
9. uploads/ 已加入 .gitignore
"""

import os
import re
import subprocess
import tempfile

import pytest

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HTML_PATH    = os.path.join(PROJECT_ROOT, "static", "index.html")
GITIGNORE    = os.path.join(PROJECT_ROOT, ".gitignore")


@pytest.fixture(scope="module")
def html_content():
    with open(HTML_PATH, encoding="utf-8") as f:
        return f.read()


@pytest.fixture(scope="module")
def js_content(html_content):
    match = re.search(r"<script>(.*?)</script>", html_content, re.DOTALL)
    assert match, "未找到 <script> 块"
    return match.group(1)


# ── 1. 文件存在 ──────────────────────────────────────────────────────────────

class TestFileExists:
    def test_html_file_exists(self):
        assert os.path.isfile(HTML_PATH), f"static/index.html 不存在: {HTML_PATH}"

    def test_html_not_empty(self, html_content):
        assert len(html_content) > 1000


# ── 2. JS 语法检查 ────────────────────────────────────────────────────────────

class TestJSSyntax:
    def test_no_empty_catch_parens(self, js_content):
        """catch() 空括号是 SyntaxError，必须用 catch(e) 或 catch"""
        bad = re.findall(r'\bcatch\s*\(\s*\)', js_content)
        assert not bad, f"发现非法 catch() 空括号: {len(bad)} 处"

    def test_no_unclosed_template_literals(self, js_content):
        cleaned = re.sub(r'\\`', '', js_content)
        count = cleaned.count('`')
        assert count % 2 == 0, f"反引号数量为奇数({count})，模板字符串未闭合"

    def test_js_parses_with_node(self, js_content):
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".mjs", delete=False, encoding="utf-8"
            ) as tmp:
                tmp.write(js_content)
                tmp_path = tmp.name
            result = subprocess.run(
                ["node", "--check", tmp_path],
                capture_output=True, text=True, timeout=10,
            )
            assert result.returncode == 0, f"node --check 报错:\n{result.stderr}"
        except FileNotFoundError:
            pytest.skip("node 不在 PATH")
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass


# ── 3. 轮询终态定义 ───────────────────────────────────────────────────────────

class TestPollTerminalStates:
    """
    POLL_SUCCESS / POLL_FAIL / POLL_MANUAL 必须包含正确的状态值。
    这些变量名和值在前端 JS 中以常量形式声明。
    """

    def test_ai_done_in_success_set(self, js_content):
        """ai_done 是后端实际终态，必须在 POLL_SUCCESS 中"""
        assert "'ai_done'" in js_content or '"ai_done"' in js_content, \
            "JS 中未找到 'ai_done' 字符串"
        # 确认它出现在 POLL_SUCCESS 数组附近
        idx = js_content.find('POLL_SUCCESS')
        assert idx != -1, "未找到 POLL_SUCCESS 变量"
        context = js_content[idx:idx+120]
        assert 'ai_done' in context, \
            f"ai_done 未出现在 POLL_SUCCESS 定义内: {context!r}"

    def test_ocr_failed_in_fail_set(self, js_content):
        """ocr_failed 是 OCR 失败终态，必须在 POLL_FAIL 中"""
        idx = js_content.find('POLL_FAIL')
        assert idx != -1, "未找到 POLL_FAIL 变量"
        context = js_content[idx:idx+120]
        assert 'ocr_failed' in context, \
            f"ocr_failed 未出现在 POLL_FAIL 定义内: {context!r}"

    def test_ai_failed_in_fail_set(self, js_content):
        idx = js_content.find('POLL_FAIL')
        assert idx != -1
        context = js_content[idx:idx+120]
        assert 'ai_failed' in context, \
            f"ai_failed 未出现在 POLL_FAIL 定义内: {context!r}"

    def test_manual_required_in_manual_set(self, js_content):
        """manual_required 需要单独处理，不能和 failed 混为一谈"""
        idx = js_content.find('POLL_MANUAL')
        assert idx != -1, "未找到 POLL_MANUAL 变量"
        context = js_content[idx:idx+80]
        assert 'manual_required' in context, \
            f"manual_required 未出现在 POLL_MANUAL 定义内: {context!r}"

    def test_no_only_completed_done_check(self, js_content):
        """
        旧代码只检查 'completed'||'done'，ai_done 会被永远忽略。
        确保 pollStatus 中不再只有这两个终态。
        """
        # 找 pollStatus 函数块
        m = re.search(r'function pollStatus.*?^}', js_content, re.DOTALL | re.MULTILINE)
        if not m:
            # 可能是 arrow function 或 setInterval 写法，找 POLL_SUCCESS 即可
            assert 'POLL_SUCCESS' in js_content, \
                "pollStatus 既没有使用 POLL_SUCCESS 也没有单独检查 ai_done"
        else:
            block = m.group(0)
            # 不应只有 completed/done 而没有 ai_done
            if 'ai_done' not in block and 'POLL_SUCCESS' not in block:
                pytest.fail("pollStatus 未处理 ai_done 终态")

    def test_inferStepsFromStatus_function_exists(self, js_content):
        """步骤推导函数必须存在"""
        assert 'inferStepsFromStatus' in js_content, \
            "未找到 inferStepsFromStatus 函数"

    def test_ai_done_infers_all_steps_done(self, js_content):
        """ai_done 状态下，所有步骤都应推导为 done"""
        assert 'ALL_DONE_STATES' in js_content or "['ai_done']" in js_content or \
               '["ai_done"]' in js_content, \
            "inferStepsFromStatus 未定义 ai_done 的全步骤完成逻辑"

    def test_ocr_run_states_defined(self, js_content):
        """OCR 进行中状态必须被推导为 running"""
        assert 'ocr_queued' in js_content and 'ocr_running' in js_content, \
            "OCR running 状态未在步骤推导中定义"


# ── 4. 字段契约：学生画像 ─────────────────────────────────────────────────────

class TestProfileFieldContract:
    """
    后端 StudentProfileResponse 字段：
      knowledge_points (list)  ← 旧前端误读 knowledge_mastery / mastery
      overall_mastery  (float) ← 旧前端误用 items 计算平均
      weak_count       (int)   ← 旧前端从 WeakPointsResponse 单独请求
    """

    def test_reads_knowledge_points_field(self, js_content):
        """知识点列表使用 knowledge_points（后端实际字段名）"""
        assert 'knowledge_points' in js_content, \
            "JS 中未读取 knowledge_points 字段"

    def test_knowledge_points_before_fallbacks(self, js_content):
        """knowledge_points 应优先于 knowledge_mastery / mastery 读取"""
        idx_kp = js_content.find('knowledge_points')
        idx_km = js_content.find('knowledge_mastery')
        # knowledge_points 应至少出现一次，且在 knowledge_mastery 之前
        assert idx_kp != -1, "未找到 knowledge_points"
        if idx_km != -1:
            assert idx_kp < idx_km, \
                "knowledge_mastery 出现在 knowledge_points 之前，优先级错误"

    def test_reads_overall_mastery_for_stats(self, js_content):
        """首页统计和知识页均应读取 overall_mastery"""
        assert 'overall_mastery' in js_content, \
            "JS 中未读取 overall_mastery 字段"

    def test_reads_weak_count_directly(self, js_content):
        """weak_count 直接从 profile 响应读取"""
        assert 'weak_count' in js_content, \
            "JS 中未读取 weak_count 字段"


# ── 5. 字段契约：学习报告 ─────────────────────────────────────────────────────

class TestReportFieldContract:
    """
    后端 LearningReportResponse 字段：
      overall_mastery  ← 旧前端误用 average_mastery_score
      strong_count     ← 旧前端误用 mastered_knowledge_points
      subjects         ← 新增展示
      top_weak_points  ← 新增展示
    """

    def test_reads_overall_mastery_for_report(self, js_content):
        """报告页使用 overall_mastery（后端实际字段）"""
        # 找 loadReport 函数
        m = re.search(r'function loadReport\b.*?^}', js_content, re.DOTALL | re.MULTILINE)
        block = m.group(0) if m else js_content  # fallback to full JS
        assert 'overall_mastery' in block, \
            "loadReport 未读取 overall_mastery"

    def test_reads_strong_count_for_mastered(self, js_content):
        """报告'已掌握'使用 strong_count"""
        m = re.search(r'function loadReport\b.*?^}', js_content, re.DOTALL | re.MULTILINE)
        block = m.group(0) if m else js_content
        assert 'strong_count' in block, \
            "loadReport 未读取 strong_count"

    def test_reads_subjects_for_breakdown(self, js_content):
        """报告页应展示 subjects 学科分布"""
        assert 'subjects' in js_content, \
            "JS 中未处理 subjects 字段"

    def test_reads_top_weak_points(self, js_content):
        """报告页应展示 top_weak_points 薄弱知识点"""
        assert 'top_weak_points' in js_content, \
            "JS 中未处理 top_weak_points 字段"

    def test_average_mastery_score_as_fallback_only(self, js_content):
        """average_mastery_score 只作为 fallback，优先使用 overall_mastery"""
        idx_om  = js_content.find('overall_mastery')
        idx_ams = js_content.find('average_mastery_score')
        if idx_ams == -1:
            return  # 完全移除旧字段也可以
        assert idx_om < idx_ams, \
            "average_mastery_score 出现在 overall_mastery 之前，优先级错误"


# ── 6. DOM 结构完整性 ─────────────────────────────────────────────────────────

class TestDOMStructure:
    REQUIRED_IDS = [
        "app", "s-home", "s-knowledge", "s-review", "s-mine",
        "upload-modal", "radar-canvas", "heatmap-table",
        "plan-list", "review-summary", "report-card",
        "toast", "upload-btn", "preview-area", "f-camera", "f-gallery",
    ]

    @pytest.mark.parametrize("elem_id", REQUIRED_IDS)
    def test_element_id_present(self, html_content, elem_id):
        assert f'id="{elem_id}"' in html_content, f"缺少元素 id=\"{elem_id}\""

    def test_camera_has_capture_env(self, html_content):
        assert 'capture="environment"' in html_content

    def test_gallery_no_capture(self, html_content):
        m = re.search(r'id="f-gallery"[^>]*>', html_content)
        assert m, "未找到 f-gallery"
        assert 'capture' not in m.group(0)

    def test_has_viewport_meta(self, html_content):
        assert 'name="viewport"' in html_content

    def test_app_not_hidden_inline(self, html_content):
        m = re.search(r'id="app"[^>]*style="([^"]*)"', html_content)
        if m:
            assert 'display:none' not in m.group(1), "#app inline style 设为 none"


# ── 7. 关键 JS 函数定义 ───────────────────────────────────────────────────────

class TestJSFunctions:
    REQUIRED = [
        "setStudent", "changeStudent", "goScreen",
        "openUpload", "closeUpload", "onFile", "doUpload",
        "inferStepsFromStatus", "renderSteps", "pollStatus",
        "loadAll", "loadHome", "loadKnowledge",
        "drawRadar", "drawHeatmap", "extractSubject",
        "loadReview", "loadReport", "doExport",
    ]

    @pytest.mark.parametrize("fn", REQUIRED)
    def test_function_defined(self, js_content, fn):
        pattern = rf'\b(?:async\s+)?function\s+{fn}\s*\('
        assert re.search(pattern, js_content), f"未找到函数定义: {fn}"

    def test_auto_init_domcontentloaded(self, js_content):
        assert 'DOMContentLoaded' in js_content
        assert 'default_student' in js_content


# ── 8. API 路径一致性 ─────────────────────────────────────────────────────────

class TestAPIPathConsistency:
    REQUIRED_PATHS = [
        "/api/upload",
        "/api/assignments/",
        "/api/students/",
        "/api/reports/student/",
        "/api/export/student/",
    ]

    @pytest.mark.parametrize("path", REQUIRED_PATHS)
    def test_path_in_js(self, js_content, path):
        assert path in js_content, f"未找到 API 路径: {path}"

    def test_no_auth_endpoints(self, js_content):
        assert "/api/auth/login" not in js_content
        assert "/api/token" not in js_content


# ── 9. uploads/ 在 .gitignore 中 ─────────────────────────────────────────────

class TestGitignore:
    def test_gitignore_exists(self):
        assert os.path.isfile(GITIGNORE), ".gitignore 不存在"

    def test_uploads_ignored(self):
        with open(GITIGNORE, encoding="utf-8") as f:
            content = f.read()
        # 匹配 uploads/ 或 uploads 独立行
        lines = [l.strip() for l in content.splitlines()]
        assert any(
            l in ('uploads/', 'uploads', '/uploads/', '/uploads')
            for l in lines
        ), f".gitignore 中未找到 uploads/ 规则，当前内容:\n{content}"

    def test_env_ignored(self):
        with open(GITIGNORE, encoding="utf-8") as f:
            content = f.read()
        assert '.env' in content, ".gitignore 未忽略 .env 文件"


# ── 10. OCR 结果展示 ──────────────────────────────────────────────────────────

class TestOCRResultDisplay:
    """
    确认前端正确读取和展示 OCR 结果：
    1. 优先使用 ocr_markdown 而非 ocr_text
    2. 读取 ocr_images 字段（OCR 切出的图片块）
    3. 不再请求废弃的 /ocr-result 接口
    4. showOcrResult 函数使用 innerHTML 渲染 markdown
    """

    def test_reads_ocr_markdown_field(self, js_content):
        """前端应读取 ocr_markdown 字段"""
        assert 'ocr_markdown' in js_content, \
            "JS 中未读取 ocr_markdown 字段"

    def test_ocr_markdown_before_ocr_text(self, js_content):
        """ocr_markdown 应优先于 ocr_text 使用"""
        idx_md = js_content.find('ocr_markdown')
        idx_txt = js_content.find('ocr_text')
        assert idx_md != -1, "未找到 ocr_markdown"
        # 如果两者都存在，markdown 应该在前面或在同一个 || 表达式中优先
        if idx_txt != -1:
            # 检查是否在 || 表达式中：ocr_markdown || ocr_text
            context = js_content[max(0, idx_md-50):min(len(js_content), idx_txt+50)]
            assert '||' in context or idx_md < idx_txt, \
                "ocr_text 出现在 ocr_markdown 之前，优先级错误"

    def test_reads_ocr_images_field(self, js_content):
        """前端应读取 ocr_images 字段（OCR 切出的图片块）"""
        assert 'ocr_images' in js_content, \
            "JS 中未读取 ocr_images 字段"

    def test_no_deprecated_ocr_result_endpoint(self, js_content):
        """不应再请求废弃的 /ocr-result 接口"""
        assert '/ocr-result' not in js_content, \
            "JS 中仍在使用废弃的 /ocr-result 接口"

    def test_show_ocr_result_function_exists(self, js_content):
        """应该有 showOcrResult 函数用于展示 OCR 结果"""
        assert 'showOcrResult' in js_content, \
            "未找到 showOcrResult 函数"

    def test_show_ocr_result_uses_innerHTML(self, js_content):
        """showOcrResult 应使用 innerHTML 而非 textContent 以支持 markdown 渲染"""
        # 查找 showOcrResult 函数
        m = re.search(r'function showOcrResult.*?^}', js_content, re.DOTALL | re.MULTILINE)
        if not m:
            pytest.skip("未找到 showOcrResult 函数定义")
        block = m.group(0)
        # 应该使用 innerHTML
        assert 'innerHTML' in block, \
            "showOcrResult 未使用 innerHTML 渲染 markdown"
        # 不应该只用 textContent（除了 confidence 等辅助字段）
        # 检查 ocrEl 相关的赋值
        if 'ocrEl' in block:
            # 应该有 innerHTML 赋值
            assert 'ocrEl.innerHTML' in block or 'ocrEl).innerHTML' in block, \
                "showOcrResult 未对 ocrEl 使用 innerHTML"

    def test_markdown_rendering_preserves_structure(self, js_content):
        """Markdown 渲染应保留结构（换行、图片、LaTeX）"""
        if 'showOcrResult' not in js_content:
            pytest.skip("未实现 showOcrResult")
        # 查找 showOcrResult 函数
        m = re.search(r'function showOcrResult.*?^}', js_content, re.DOTALL | re.MULTILINE)
        if not m:
            pytest.skip("未找到 showOcrResult 函数定义")
        block = m.group(0)
        # 应该处理换行
        assert r'\n' in block or 'replace' in block, \
            "showOcrResult 未处理换行"
        # 应该处理图片
        assert 'img' in block.lower() or '!\\[' in block, \
            "showOcrResult 未处理 Markdown 图片"
