"""
PaperMind Phase 3 Streamlit 单页应用

提供最小可操作页面，用于：
1. 保存阅读笔记到 Memory V2（支持元数据）
2. 同步笔记到检索索引
3. 查询历史记忆并生成回答（支持标签和时间过滤）
"""

import asyncio
import tempfile
from datetime import date
from pathlib import Path
import streamlit as st
from papermind.app_service import (
    Identity,
    IDENTITIES,
    WriteResult,
    SyncResult,
    AskResult,
    save_note,
    sync_notes,
    ask_memory,
)
from papermind.pdf_extractor import extract_pdf_text, PDFExtractResult
from papermind.translator import create_translator, TranslationResult
from papermind.models import NoteMetadata
from papermind.constants import PREDEFINED_TAGS, NOTE_TYPES, TIME_RANGE_OPTIONS
from papermind.utils.date_utils import calculate_date_range


# Mock LLMClient for ask_memory
class MockLLMClient:
    """Mock LLM 客户端用于演示"""
    async def generate(self, prompt: str) -> str:
        # 实际部署时应替换为真实 LLM 客户端
        return "这是 Mock LLM 生成的回答。请配置真实的 LLM 客户端以获得实际回答。"


# 初始化 session state
if "selected_identity" not in st.session_state:
    st.session_state.selected_identity = 0
if "note_title" not in st.session_state:
    st.session_state.note_title = ""
if "note_conclusion" not in st.session_state:
    st.session_state.note_conclusion = ""
if "note_title_input" not in st.session_state:
    st.session_state.note_title_input = ""
if "note_conclusion_input" not in st.session_state:
    st.session_state.note_conclusion_input = ""
if "pending_save" not in st.session_state:
    st.session_state.pending_save = False
if "write_result" not in st.session_state:
    st.session_state.write_result = None
if "sync_result" not in st.session_state:
    st.session_state.sync_result = None
if "question" not in st.session_state:
    st.session_state.question = ""
if "ask_result" not in st.session_state:
    st.session_state.ask_result = None
if "pdf_extract_result" not in st.session_state:
    st.session_state.pdf_extract_result = None
if "pdf_translated_text" not in st.session_state:
    st.session_state.pdf_translated_text = None
if "show_translation" not in st.session_state:
    st.session_state.show_translation = False

# Phase 3: 元数据相关 session state（仅初始化非 widget 绑定的状态）
if "note_read_date_default" not in st.session_state:
    st.session_state.note_read_date_default = date.today()


# ===== 1. 标题与身份选择 =====
st.title("📚 PaperMind - 论文笔记与记忆管理")

# 身份选择下拉框
identity_labels = [identity.label for identity in IDENTITIES]
selected_index = st.selectbox(
    "选择身份",
    range(len(IDENTITIES)),
    format_func=lambda i: identity_labels[i],
    key="selected_identity",
)

st.divider()


# ===== 2. 笔记输入区 =====
st.subheader("📝 保存阅读笔记")

# PDF 上传功能
st.write("**方式 1: 上传 PDF 论文**")
uploaded_file = st.file_uploader(
    "选择 PDF 文件（<10MB）",
    type=["pdf"],
    help="支持可复制文本的 PDF，暂不支持扫描版和加密 PDF",
)

if uploaded_file is not None:
    # 检查文件大小（10MB 限制）
    file_size_mb = len(uploaded_file.getvalue()) / (1024 * 1024)

    if file_size_mb > 10:
        st.error(f"文件过大（{file_size_mb:.1f}MB），请上传小于 10MB 的 PDF")
    else:
        with st.spinner("正在提取 PDF 文本..."):
            # 保存到临时文件
            with tempfile.NamedTemporaryFile(delete=False, suffix=".pdf") as tmp_file:
                tmp_file.write(uploaded_file.getvalue())
                tmp_path = Path(tmp_file.name)

            try:
                # 提取 PDF 文本
                result = asyncio.run(extract_pdf_text(tmp_path))
                st.session_state.pdf_extract_result = result

                # 清理临时文件
                tmp_path.unlink()

                if result.success:
                    st.success("✓ PDF 文本提取成功")

                    # 自动填充标题（但不覆盖用户已输入的内容）
                    if result.title and not st.session_state.note_title:
                        st.session_state.note_title = result.title

                    # 展示完整提取内容
                    if result.text:
                        st.write("**📄 提取的完整内容**")

                        # 显示当前查看的是原文还是译文
                        if st.session_state.show_translation and st.session_state.pdf_translated_text:
                            display_text = st.session_state.pdf_translated_text
                            st.info("当前显示：中文翻译")
                        else:
                            display_text = result.text
                            st.info("当前显示：原文")

                        # 使用可滚动的text_area展示完整内容（不使用key，避免状态冲突）
                        st.text_area(
                            "提取内容",
                            value=display_text,
                            height=300,
                            help="可滚动查看完整内容",
                            disabled=True,
                        )

                        # 操作按钮
                        col_btn1, col_btn2, col_btn3 = st.columns(3)

                        with col_btn1:
                            if st.button("📋 应用到编辑区", type="primary"):
                                # 应用当前显示的文本（原文或译文）到正确的 session_state key
                                st.session_state.note_conclusion_input = display_text
                                st.session_state.note_conclusion = display_text
                                st.rerun()

                        with col_btn2:
                            if st.button("🌐 翻译为中文"):
                                try:
                                    with st.spinner("正在翻译..."):
                                        # 创建翻译器（使用真实API）
                                        translator = create_translator(use_mock=False)

                                        # 翻译文本（限制长度避免API超时）
                                        text_to_translate = result.text[:5000] if len(result.text) > 5000 else result.text
                                        translation_result = asyncio.run(
                                            translator.translate(
                                                text=text_to_translate,
                                                target_lang="zh",
                                                source_lang="auto",
                                            )
                                        )

                                        if translation_result.success:
                                            st.session_state.pdf_translated_text = translation_result.translated_text
                                            st.session_state.show_translation = True
                                            st.success("✓ 翻译完成")
                                            st.rerun()
                                        else:
                                            st.error(f"✗ 翻译失败：{translation_result.error_message}")
                                except Exception as e:
                                    st.error(f"✗ 翻译过程出错：{str(e)}")

                        with col_btn3:
                            if st.session_state.show_translation:
                                if st.button("📄 显示原文"):
                                    st.session_state.show_translation = False
                                    st.rerun()
                else:
                    # 显示错误信息
                    st.error(f"✗ {result.error_message}")

                    # 根据错误码给出具体建议
                    if result.error_code == "encrypted":
                        st.info("💡 建议：请使用解密工具移除 PDF 密码后重试")
                    elif result.error_code == "scanned":
                        st.info("💡 建议：扫描版 PDF 需要 OCR 识别，请手动输入内容")
                    elif result.error_code == "empty":
                        st.info("💡 建议：PDF 可能是图片格式，请手动输入内容")

            except Exception as e:
                st.error(f"PDF 处理失败：{str(e)}")
                # 确保清理临时文件
                if tmp_path.exists():
                    tmp_path.unlink()

st.write("**方式 2: 手动输入**")

# 如果有PDF提取的内容，显示提示
if st.session_state.pdf_extract_result and st.session_state.pdf_extract_result.success:
    st.info("💡 提示：点击上方「📋 应用到编辑区」后，内容会自动填充到下方输入框")

note_title = st.text_input(
    "论文标题 *",
    key="note_title_input",
    placeholder="例如：Attention Is All You Need",
)

note_conclusion = st.text_area(
    "阅读结论 *（可编辑提取的内容或手动输入）",
    key="note_conclusion_input",
    height=200,
    help="内容会显示在这里，您可以直接编辑",
    placeholder="输入您的阅读笔记...",
)

# Phase 3: 元数据输入表单
st.write("**📋 元数据信息**")

col_meta1, col_meta2 = st.columns(2)

with col_meta1:
    note_author = st.text_input(
        "论文作者（选填）",
        key="note_author",
        placeholder="例如：Vaswani et al.",
    )

with col_meta2:
    note_year = st.text_input(
        "发表年份/会议（选填）",
        key="note_year",
        placeholder="例如：2017 或 NeurIPS 2017",
    )

col_meta3, col_meta4 = st.columns(2)

with col_meta3:
    note_read_date = st.date_input(
        "阅读日期 *",
        value=date.today(),
        key="note_read_date",
        help="默认为今天，可修改为实际阅读日期",
    )

with col_meta4:
    note_type = st.selectbox(
        "笔记类型 *",
        options=NOTE_TYPES,
        key="note_type",
    )

note_tags = st.multiselect(
    "标签 * (至少选择 1 个)",
    options=PREDEFINED_TAGS,
    key="note_tags",
    help="选择与笔记相关的标签",
)

# 同步输入到 session state（用于保存功能）
st.session_state.note_title = st.session_state.note_title_input
st.session_state.note_conclusion = st.session_state.note_conclusion_input

col1, col2 = st.columns([1, 1])

with col1:
    if st.button("💾 保存笔记"):
        # 第一次点击设置 pending_save
        st.session_state.pending_save = True

with col2:
    # 仅在 pending_save 为 True 时显示确认按钮
    if st.session_state.pending_save:
        if st.button("✅ 确认保存"):
            try:
                # Phase 3: 验证必填字段
                if not st.session_state.note_title or not st.session_state.note_title.strip():
                    st.error("❌ 请输入论文标题")
                    st.session_state.pending_save = False
                elif not st.session_state.note_conclusion or not st.session_state.note_conclusion.strip():
                    st.error("❌ 请输入阅读结论")
                    st.session_state.pending_save = False
                elif not st.session_state.note_tags:
                    st.error("❌ 请至少选择 1 个标签")
                    st.session_state.pending_save = False
                else:
                    # 获取当前身份
                    current_identity = IDENTITIES[st.session_state.selected_identity]

                    # Phase 3: 构造元数据对象
                    metadata = NoteMetadata(
                        title=st.session_state.note_title.strip(),
                        author=st.session_state.note_author.strip() if st.session_state.note_author else None,
                        year=st.session_state.note_year.strip() if st.session_state.note_year else None,
                        read_date=st.session_state.note_read_date,
                        tags=st.session_state.note_tags,
                        note_type=st.session_state.note_type,
                    )

                    # 调用 save_note（带元数据）
                    result = asyncio.run(
                        save_note(
                            identity=current_identity,
                            title=st.session_state.note_title,
                            conclusion=st.session_state.note_conclusion,
                            confirmed=True,
                            metadata=metadata,
                        )
                    )

                    # 保存结果并重置 pending_save
                    st.session_state.write_result = result
                    st.session_state.pending_save = False

            except ValueError as e:
                st.error(f"❌ 元数据验证失败: {str(e)}")
                st.session_state.pending_save = False
            except Exception as e:
                st.error(f"保存失败：{str(e)}")
                st.session_state.pending_save = False

# 显示写入结果
if st.session_state.write_result:
    result = st.session_state.write_result

    # 根据状态使用不同颜色
    if result.status == "saved":
        st.success(f"✓ {result.message}")
    elif result.status == "partial":
        st.warning(f"⚠ {result.message}")
    elif result.status == "skipped":
        st.info(f"ℹ {result.message}")
    elif result.status == "no_memory":
        st.info(f"ℹ {result.message}")
    elif result.status == "failed":
        st.error(f"✗ {result.message}")

    # 显示详细信息
    if result.memory_ids:
        st.write(f"Memory IDs: {', '.join(result.memory_ids)}")

    # 显示 turn_id 前 8 字符
    st.write(f"Turn ID: {result.turn_id[:8]}...")

    if result.error_code:
        st.write(f"错误码: {result.error_code}")

st.divider()


# ===== 3. 同步区 =====
st.subheader("🔄 同步笔记到索引")

if st.button("🔄 同步到检索索引"):
    try:
        # 调用 sync_notes
        result = asyncio.run(sync_notes(batch_size=100))
        st.session_state.sync_result = result

    except Exception as e:
        st.error(f"同步失败：{str(e)}")

# 显示同步结果
if st.session_state.sync_result:
    result = st.session_state.sync_result

    if result.status == "completed":
        st.success(f"✓ 批次已处理 {result.done} 条，失败 {result.failed} 条，死信 {result.dead} 条")
        st.info("⚠️ 批次处理完成，仍需通过查询确认")
    else:
        st.error(f"✗ 同步失败: {result.message}")

st.divider()


# ===== 4. 查询区 =====
st.subheader("💬 查询历史记忆")

question = st.text_input(
    "输入问题",
    value=st.session_state.question,
    key="question_input",
    placeholder="例如：Transformer 的注意力机制如何工作？",
)

st.session_state.question = question

# Phase 3: 高级过滤器（可折叠）
with st.expander("🔧 高级过滤（可选）", expanded=False):
    # 标签过滤
    query_tags = st.multiselect(
        "按标签过滤（多选，匹配任一标签）",
        options=PREDEFINED_TAGS,
        key="query_tags",
        help="留空则不按标签过滤",
    )

    # 时间范围过滤
    query_time_range = st.selectbox(
        "时间范围",
        options=TIME_RANGE_OPTIONS,
        key="query_time_range",
    )

    # 自定义日期范围
    custom_start, custom_end = None, None
    if query_time_range == "自定义":
        col_date1, col_date2 = st.columns(2)
        with col_date1:
            custom_start = st.date_input("起始日期", key="custom_start_date")
        with col_date2:
            custom_end = st.date_input("结束日期", key="custom_end_date")

if st.button("🔍 查询记忆", type="primary"):
    if not st.session_state.question:
        st.warning("⚠️ 请输入查询内容")
    else:
        try:
            # 获取当前身份
            current_identity = IDENTITIES[st.session_state.selected_identity]

            # 创建 LLM 客户端
            llm_client = MockLLMClient()

            # Phase 3: 计算时间范围
            start_date, end_date = None, None
            if st.session_state.query_time_range != "全部时间":
                try:
                    start_date, end_date = calculate_date_range(
                        range_option=st.session_state.query_time_range,
                        custom_start=custom_start if st.session_state.query_time_range == "自定义" else None,
                        custom_end=custom_end if st.session_state.query_time_range == "自定义" else None,
                    )
                except ValueError as e:
                    st.error(f"❌ 日期范围错误: {str(e)}")
                    start_date, end_date = None, None

            # 显示过滤条件（如果有）
            filter_info = []
            if st.session_state.query_tags:
                filter_info.append(f"标签: {', '.join(st.session_state.query_tags)}")
            if start_date and end_date:
                filter_info.append(f"时间: {start_date} ~ {end_date}")

            if filter_info:
                st.info(f"🔎 应用过滤条件：{' | '.join(filter_info)}")

            # Phase 3: 调用带过滤参数的检索
            with st.spinner("正在检索笔记..."):
                result = asyncio.run(
                    ask_memory(
                        identity=current_identity,
                        question=st.session_state.question,
                        llm_client=llm_client,
                        tags=st.session_state.query_tags if st.session_state.query_tags else None,
                        start_date=start_date,
                        end_date=end_date,
                    )
                )

                st.session_state.ask_result = result

        except Exception as e:
            st.error(f"查询失败：{str(e)}")

st.divider()


# ===== 5. 回答与证据展示 =====
st.subheader("💡 回答与证据")

if st.session_state.ask_result:
    result = st.session_state.ask_result

    # 根据状态显示不同内容
    if result.status == "answered":
        st.success("✓ 已生成回答")
        st.write("**回答：**")
        st.write(result.answer)

        if result.evidence:
            st.write("**证据：**")
            for idx, evidence in enumerate(result.evidence, start=1):
                with st.expander(f"证据 {idx} - Memory ID: {evidence.memory_id}"):
                    st.write(f"**内容：** {evidence.content}")
                    st.write(f"**类型：** {evidence.memory_type}")
                    st.write(f"**置信度：** {evidence.confidence:.2f}")
                    if evidence.created_at:
                        st.write(f"**创建时间：** {evidence.created_at}")

    elif result.status == "no_evidence":
        st.info("ℹ️ 未找到相关历史记忆")
        st.write(result.answer)

    elif result.status == "retrieval_failed":
        st.error("✗ 记忆检索失败")
        st.write(result.answer)
        if result.error_code:
            st.write(f"错误码: {result.error_code}")

    elif result.status == "answer_failed":
        st.warning("⚠️ 回答生成失败，但已找到相关记忆")
        st.write(result.answer)
        if result.error_code:
            st.write(f"错误码: {result.error_code}")

        if result.evidence:
            st.write("**已检索到的证据：**")
            for idx, evidence in enumerate(result.evidence, start=1):
                with st.expander(f"证据 {idx} - Memory ID: {evidence.memory_id}"):
                    st.write(f"**内容：** {evidence.content}")
                    st.write(f"**类型：** {evidence.memory_type}")
                    st.write(f"**置信度：** {evidence.confidence:.2f}")
                    if evidence.created_at:
                        st.write(f"**创建时间：** {evidence.created_at}")

st.divider()


# ===== 6. 会话控制 =====
st.subheader("🔄 会话管理")

if st.button("🆕 新建会话"):
    # 清除临时数据，保留 selected_identity
    st.session_state.note_title = ""
    st.session_state.note_conclusion = ""
    st.session_state.question = ""
    st.session_state.pending_save = False
    st.session_state.write_result = None
    st.session_state.sync_result = None
    st.session_state.ask_result = None
    st.session_state.pdf_extract_result = None
    # Phase 3: 清除元数据 widget 状态
    # 注意：widget 绑定的 key 在 Streamlit 中会自动管理
    # 这里只清除存储的结果状态
    st.success("✓ 已清除会话数据")
    st.rerun()
