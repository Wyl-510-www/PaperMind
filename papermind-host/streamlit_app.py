"""
PaperMind Phase 2 Streamlit 单页应用

提供最小可操作页面，用于：
1. 保存阅读笔记到 Memory V2
2. 同步笔记到检索索引
3. 查询历史记忆并生成回答
"""

import asyncio
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

note_title = st.text_input(
    "论文标题",
    value=st.session_state.note_title,
    key="note_title_input",
)

note_conclusion = st.text_area(
    "阅读结论",
    value=st.session_state.note_conclusion,
    key="note_conclusion_input",
    height=150,
)

# 同步输入到 session state
st.session_state.note_title = note_title
st.session_state.note_conclusion = note_conclusion

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
                # 获取当前身份
                current_identity = IDENTITIES[st.session_state.selected_identity]

                # 调用 save_note
                result = asyncio.run(
                    save_note(
                        identity=current_identity,
                        title=st.session_state.note_title,
                        conclusion=st.session_state.note_conclusion,
                        confirmed=True,
                    )
                )

                # 保存结果并重置 pending_save
                st.session_state.write_result = result
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
)

st.session_state.question = question

if st.button("🔍 查询记忆"):
    try:
        # 获取当前身份
        current_identity = IDENTITIES[st.session_state.selected_identity]

        # 创建 LLM 客户端
        llm_client = MockLLMClient()

        # 调用 ask_memory
        result = asyncio.run(
            ask_memory(
                identity=current_identity,
                question=st.session_state.question,
                llm_client=llm_client,
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
    st.success("✓ 已清除会话数据")
