"""Domain contracts shared by Memory V2 write and read paths.

所有模块通过这些 Pydantic 模型交换数据。每个模型使用 extra="forbid" 避免意外字段。
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    """基础模型，禁止额外字段"""
    model_config = ConfigDict(extra="forbid")


class MemoryType(str, Enum):
    """记忆类型枚举"""
    SEMANTIC = "semantic"           # 稳定的用户事实、偏好
    EPISODIC = "episodic"           # 有时间边界的事件
    STATE = "state"                 # 短期状态，进 DSM
    TASK = "task"                   # 任务
    RELATIONSHIP = "relationship"   # 关系
    ENTITY_RELATION = "entity_relation"  # 第三方实体关系
    BEHAVIOR_POLICY = "behavior_policy"  # 行为约束策略
    DISCARD = "discard"             # 拒绝写入


class ExtractionLane(str, Enum):
    """抽取 lane 枚举（TypedWriteRouter 用于规划）"""
    SEMANTIC = "semantic"                   # 稳定偏好/长期事实
    EVENT_TASK = "event_task"               # 事件/任务 + 时间范围
    ENTITY_RELATION = "entity_relation"     # 第三方实体关系
    BEHAVIOR_POLICY = "behavior_policy"     # 行为边界/称呼/风格
    UPDATE_DELETE = "update_delete"         # 显式更新/删除/纠正


class Modality(str, Enum):
    """陈述模态枚举"""
    FACT = "fact"           # 事实
    PLAN = "plan"           # 计划
    WISH = "wish"           # 愿望
    HYPOTHESIS = "hypothesis"  # 假设
    JOKE = "joke"           # 玩笑
    QUOTE = "quote"         # 引用
    QUESTION = "question"   # 疑问
    UNCERTAIN = "uncertain"  # 不确定


class Scope(StrictModel):
    """多租户隔离范围"""
    tenant_id: str = Field(min_length=1, max_length=64, description="租户 ID")
    user_id: str = Field(min_length=1, max_length=128, description="用户 ID")
    namespace: str = Field(default="user_memory", max_length=64, description="命名空间")


class SubjectRef(StrictModel):
    """主体引用"""
    kind: str = Field(default="user", description="主体类型：user/person/pet")
    canonical_name: str = Field(min_length=1, max_length=128, description="规范化名称")
    is_current_user: bool = Field(default=False, description="是否是当前用户本人（门控关键字段）")
    entity_id: str | None = Field(default=None, description="实体 ID（如有）")


class TimeCandidate(StrictModel):
    """时间候选（归一化后的时间信息）"""
    original_expression: str | None = Field(default=None, description="原始表达：'明天''下午3点'")
    absolute_start: datetime | None = Field(default=None, description="绝对开始时间（UTC）")
    absolute_end: datetime | None = Field(default=None, description="绝对结束时间（UTC，可选）")
    precision: str = Field(default="unknown", description="精度：unknown/day/minute")
    resolved_by: str = Field(default="none", description="解析方式：none/deterministic/llm")


class MemoryCandidate(StrictModel):
    """记忆候选（LLM 抽取输出 + 代码校验后）"""
    candidate_id: str = Field(description="候选 ID")
    subject: SubjectRef = Field(description="主体引用")
    predicate: str = Field(min_length=1, max_length=128, description="谓词：diet.dislike, behavior.tendency")
    value: Any = Field(description="值：香菜、掀翻桌子")
    normalized_text_zh: str = Field(min_length=1, description="规范化中文文本")
    memory_type: MemoryType = Field(description="记忆类型")
    modality: Modality = Field(description="陈述模态")
    polarity: str = Field(default="positive", description="极性：positive/negative")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度 0-1")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="重要性 0-1")
    durability: str = Field(default="unknown", description="持久性：stable/episodic/temporary/unknown")
    time: TimeCandidate = Field(default_factory=TimeCandidate, description="时间信息")
    source_span: str = Field(min_length=1, description="原文片段（用于交叉校验）")
    explicit_update: bool = Field(default=False, description="显式更新指令")
    explicit_delete: bool = Field(default=False, description="显式删除指令")
    target_hint: str | None = Field(default=None, description="目标提示（如 fact_key 或 event_id）")
    provenance: str | None = Field(default=None, description="来源：confirmed/hypothesis/inferred（Ticket 05）")
    domain: str | None = Field(default=None, description="偏好领域：food/music/activity")
    object_key: str | None = Field(default=None, description="偏好对象：香菜/辣味")
    preference_strength: str | None = Field(default=None, description="偏好强度：favorite/strong/normal/weak")

    # P0-1新增字段
    operation: str | None = Field(default="assert", description="操作类型：assert/update/delete/cancel（P0-1）")
    supersedes: str | None = Field(default=None, description="指向旧truth的ID（P0-1）")
    prior_source_turn: str | None = Field(default=None, description="历史陈述的来源turn（P0-1）")
    rejected: bool = Field(default=False, description="是否被拒绝（P0-1）")
    reject_reason: str | None = Field(default=None, description="拒绝原因（P0-1）")

    # P1-1新增字段
    precision: str | None = Field(default="exact", description="数值精度：exact/approximate/estimated（P1-1）")
    ambiguity_type: str | None = Field(default=None, description="歧义类型：真实不确定/礼貌表达/数值精度（P1-1）")


class DeterministicSignals(StrictModel):
    """确定性信号（从 source_span 检测）"""
    has_hypothesis: bool = Field(default=False, description="包含假设标记：如果/假如/要是")
    has_joke_marker: bool = Field(default=False, description="包含玩笑标记：开玩笑/逗你的")
    has_quote_marker: bool = Field(default=False, description="包含引用标记：小说里/台词是")
    has_temporary_marker: bool = Field(default=False, description="包含临时标记：今天/现在/这次")
    has_persistent_marker: bool = Field(default=False, description="包含持久标记：一直/长期/从不")
    has_cancel_marker: bool = Field(default=False, description="包含取消标记：取消/不去了")
    has_complete_marker: bool = Field(default=False, description="包含完成标记：完成了/做完了")


class LanePlan(StrictModel):
    """Lane 规划结果（TypedWriteRouter 输出）"""
    lanes: list[ExtractionLane] = Field(description="激活的 lane 列表")
    reason_codes: dict[str, str] = Field(default_factory=dict, description="激活原因（lane -> reason）")


class WriteTrace(StrictModel):
    """写入追踪（MemoryWriter 输出）"""
    turn_id: str = Field(description="轮次 ID")
    lanes_activated: list[str] = Field(default_factory=list, description="激活的 lane 名")
    candidates_total: int = Field(default=0, description="总候选数")
    candidates_accepted: int = Field(default=0, description="接受的候选数")
    candidates_rejected: int = Field(default=0, description="拒绝的候选数")
    reason_codes: dict[str, int] = Field(default_factory=dict, description="拒绝原因分布")
    lane_results: dict[str, int] = Field(default_factory=dict, description="各 lane 产出数")
    # P0-2修复：支持混合类型，可存储str（memory_id等）或EntityWriteReceipt对象
    repository_commits: list[str | Any] = Field(default_factory=list, description="落库提交的 ID 列表或回执对象")
    elapsed_ms: float = Field(default=0.0, description="总耗时（毫秒）")
    speech_act: str | None = Field(default=None, description="Speech Act 分类结果（assert/query_existing/explicit_update/explicit_delete/ambiguous）")
    # P0-3修复：保存所有lane的LaneOutcome以提供完整可观测性
    lane_outcomes: list[Any] = Field(default_factory=list, description="各lane的抽取结果（包含成功和失败信息）")


class WriteDecision(StrictModel):
    """写入决策（门控裁决结果）"""
    candidate: MemoryCandidate = Field(description="原始候选")
    accepted: bool = Field(description="是否接受写入")
    route: MemoryType = Field(description="路由目标")
    reason_code: str = Field(description="决策原因代码")
    fact_key: str | None = Field(default=None, description="事实键（用于版本化）")
    object_id: str | None = Field(default=None, description="对象 ID（event_id/entity_id）")
    ttl_seconds: int | None = Field(default=None, description="TTL 秒数（state 类型）")


class WriteResult(StrictModel):
    """写入结果（兼容 mem0 格式）"""
    memory_id: str = Field(description="记忆 ID")
    memory: str = Field(description="记忆文本")
    event: str = Field(description="事件类型：ADD/UPDATE/DELETE")
    metadata: dict[str, Any] = Field(default_factory=dict, description="元数据")


# ─── M1 新增：类型化写入结果 ──────────────────────────────────────────────────

class LaneOutcome(StrictModel):
    """单个 lane 的抽取结果（M1 新增）

    用于区分各种失败原因，便于问题定位和分层优化。
    """
    lane: str = Field(description="lane 名称：semantic/entity_relation/behavior_policy 等")
    status: str = Field(description="状态：success/success_empty/api_error/parse_error/schema_error/source_rejected")
    candidates: list[MemoryCandidate] = Field(default_factory=list, description="候选列表")
    error_code: str | None = Field(default=None, description="错误代码（失败时）")
    error_message: str | None = Field(default=None, description="错误消息（失败时）")


class CommitReceipt(StrictModel):
    """写入提交回执（M1 新增）

    只有真实成功的提交才生成回执，提供完整的溯源信息。
    """
    aggregate_type: str = Field(description="聚合根类型：MemoryRecord/EntityRelation/Event")
    aggregate_id: str = Field(description="聚合根 ID")
    projection_ids: list[str] = Field(default_factory=list, description="投影 ID 列表（memory_id 等）")
    outbox_ids: list[str] = Field(default_factory=list, description="Outbox 事件 ID 列表")
    truth_committed: bool = Field(description="是否已提交到 truth store")
    index_visible: bool | None = Field(default=None, description="索引是否可见（None=异步索引未完成）")


class EntityWriteReceipt(StrictModel):
    """实体写入回执（P0-2 新增）

    完整的实体写入回执，包含所有相关ID以支持Canary和Probe验证。
    """
    entity_id: str = Field(description="实体 ID")
    relation_id: str = Field(description="关系 ID")
    memory_id: str = Field(description="Memory Record ID（用于向量检索）")
    outbox_id: int = Field(description="Outbox 事件 ID（自增主键，用于异步索引）")


class V2WriteResult(StrictModel):
    """V2 写入结果（M1 新增，替代 facade 中的 dict 返回）

    提供完整的类型化写入结果，区分各 lane 的成功/失败状态。
    """
    user_id: str = Field(description="用户 ID")
    turn_id: str = Field(description="轮次 ID")
    tenant_id: str = Field(description="租户 ID")
    occurred_at: datetime = Field(description="发生时间")

    speech_act: str = Field(description="Speech Act 分类：assert/query_existing/explicit_update/explicit_delete/ambiguous/unknown")
    lane_outcomes: list[LaneOutcome] = Field(default_factory=list, description="各 lane 的抽取结果")

    # 只有真实成功的提交才进入 commits
    # P0-2修复：支持混合类型，可包含EntityWriteReceipt或CommitReceipt
    commits: list[CommitReceipt | EntityWriteReceipt] = Field(default_factory=list, description="提交回执列表")

    # 聚合状态
    v2_write_success: bool = Field(description="至少一个 lane 成功")
    total_candidates: int = Field(default=0, description="总候选数")
    total_commits: int = Field(default=0, description="总提交数")

    # 失败信息
    failed_lanes: list[str] = Field(default_factory=list, description="失败的 lane 列表")


# ─────────────────────────────────────────────────────────────────────────────


class EvidenceItem(StrictModel):
    """证据条目（检索结果单条，Phase 3 用）"""
    memory_id: str = Field(description="记忆 ID")
    memory_type: MemoryType = Field(description="记忆类型")
    content: str = Field(description="内容文本")
    subject_id: str = Field(description="主体 ID")
    predicate: str = Field(description="谓词")
    status: str = Field(description="状态：active/superseded/deleted/expired")
    modality: Modality = Field(description="陈述模态")
    confidence: float = Field(ge=0.0, le=1.0, description="置信度")
    importance: float = Field(default=0.5, ge=0.0, le=1.0, description="重要性")
    source_turn_ids: list[str] = Field(default_factory=list, description="来源轮次 ID")
    source_date: datetime | None = Field(default=None, description="来源日期")
    expires_at: datetime | None = Field(default=None, description="过期时间")
    # 冲突裁决字段（P1-1）：来源类型 + 观测时间，决定同 subject+predicate 冲突时谁胜出
    source_kind: str = Field(
        default="persistent",
        description="来源类型：user_turn/dsm/persistent/inferred，优先级依次降低",
    )
    observed_at: datetime | None = Field(default=None, description="观测/生效时间，同来源时按此再排序")
    usage: str = Field(default="history_only", description="使用方式")
    # Canary Gate 验证字段（问题 #6 修复）：标识记忆来源，用于验证短期清理状态
    source: str = Field(
        default="long_term_index",
        description="记忆来源：long_term_index（长期索引）或 short_term_memory（短期记忆，测试用）",
    )
    semantic_score: float = Field(default=0.0, description="语义相似度分数")
    lexical_score: float = Field(default=0.0, description="词法分数")
    entity_score: float = Field(default=0.0, description="实体分数")
    final_score: float = Field(default=0.0, description="最终分数")


class EvidencePack(StrictModel):
    """证据包（Phase 3：生成模型的结构化记忆输入）

    ⚠️ 架构决策待定：DSM 当前状态（current_state）与 Evidence Pack 是独立的两路输入，
    不互相包含（见 CONTEXT.md「Evidence Pack」词条）。调用方需分别获取。
    但此边界尚在权衡中，可能回退为合并（EvidencePack 重新含 current_state）。
    详见 docs/decisions/dsm-evidence-pack-boundary-pending.md。
    """
    query: str = Field(description="查询文本")
    items: list[EvidenceItem] = Field(default_factory=list, description="证据条目列表")
    active_events: list[dict[str, Any]] = Field(default_factory=list, description="活跃事件列表")
    generated_at: datetime = Field(description="生成时间")


class RetrievalPlan(StrictModel):
    """检索计划（Phase 3：QueryRouter 产出，指导本轮查什么）"""
    memory_types: set[MemoryType] = Field(default_factory=set, description="要查的记忆类型集合")
    per_type_top_k: dict[str, int] = Field(default_factory=dict, description="每类记忆的 top_k，key=MemoryType.value")
    skip_retrieval: bool = Field(default=False, description="本轮跳过检索（如普通寒暄）")


class GuardAction(str, Enum):
    """Claim Guard 对单条主张的处置动作"""
    KEEP = "keep"               # 保留，有证据支撑
    DELETE = "delete"           # 删除该主张
    TO_QUESTION = "to_question"  # 改成询问
    REGENERATE = "regenerate"    # 重生成整段


class Claim(StrictModel):
    """单条主张（ClaimGuard 检测到的断言）"""
    text: str = Field(description="主张文本")
    span: tuple[int, int] = Field(description="在原文中的起止位置 (start, end)")
    mapped_memory_ids: list[str] = Field(default_factory=list, description="映射到的证据 memory_id")
    action: GuardAction = Field(description="处置动作")


class GuardResult(StrictModel):
    """Claim Guard 验证结果（Phase 3：生成后验证）"""
    claims: list[Claim] = Field(default_factory=list, description="检测到的主张列表")
    overall_action: GuardAction = Field(description="整体处置动作")


# ─── Phase 4A：评测与迁移契约 ────────────────────────────────────────────────

class EvalStage(str, Enum):
    """评测阶段枚举（四阶段独立评测，原方案 11.1）"""
    WRITE = "write"         # 写入：应记召回、误写率、主体/模态准确率、时间归一化
    UPDATE = "update"       # 更新：slot 更新准确率、复活率、删除闭环
    RETRIEVE = "retrieve"   # 检索：Recall@K、Precision@K、MRR、泄漏率
    GENERATE = "generate"   # 生成：grounded rate、无依据率、错位率


class EvalCase(StrictModel):
    """评测用例（Phase 4A）"""
    case_id: str = Field(description="用例 ID")
    stage: EvalStage = Field(description="评测阶段")
    input: dict[str, Any] = Field(description="输入，根据 stage 不同")
    gold: dict[str, Any] = Field(description="gold 标注")
    context: dict[str, Any] = Field(default_factory=dict, description="前置上下文，如 pre_insert")
    repeat: int = Field(default=1, ge=1, description="重复次数，取平均排除随机性")


class StageReport(StrictModel):
    """阶段指标报告（Phase 4A）"""
    stage: EvalStage = Field(description="评测阶段")
    total_cases: int = Field(ge=0, description="用例总数")
    metrics: dict[str, float] = Field(default_factory=dict, description="指标名 → 值")
    failed_cases: list[dict[str, Any]] = Field(default_factory=list, description="失败用例详情")
    summary: str = Field(default="", description="markdown 摘要")


class MigrationResult(StrictModel):
    """迁移结果统计（Phase 4A）"""
    batch_id: str = Field(description="迁移批次 UUID，用于回滚")
    total: int = Field(ge=0, description="旧记忆总数")
    success: int = Field(ge=0, description="迁移成功数")
    skipped: int = Field(ge=0, description="跳过数，如 joke")
    failed: int = Field(ge=0, description="失败数")
    by_type: dict[str, int] = Field(default_factory=dict, description="memory_type → 成功数")
    errors: list[dict[str, Any]] = Field(default_factory=list, description="失败记录详情")


# ─── DSM 边界预留（票 18 / ADR 0011）─────────────────────────────────────────
#
# DSM（Dialog State Memory）是独立服务，Memory V2 不感知其实现。以下 Protocol 和
# 数据类仅作为 Memory V2 ↔ DSM 的接口文档：主会话流并行调用 Memory V2（拿
# EvidencePack）和 DSM（拿 CurrentState），在 prompt 中独立拼接。
#
# ⚠️ 当前不实现，Phase 5 集成时由 DSM 团队提供 DSMReader 实现。EvidencePack
#    不包含 current_state——两者是独立数据源，边界见 ADR 0011。


class CurrentState(StrictModel):
    """DSM 返回的对话状态快照（短生命周期，会话内有效）。

    与 Memory V2 的持久化记忆（EvidenceItem）语义不同：
    - CurrentState 随对话轮次更新，会话结束即清理
    - EvidenceItem 是版本化的持久事实/事件

    示例 variables: {"那个地方": "北京", "他": "张三"}
    """
    variables: dict[str, Any] = Field(
        default_factory=dict, description="临时变量（指代消解、上下文绑定）"
    )
    pending_intents: list[str] = Field(
        default_factory=list, description="待处理意图（如'待确认：订机票'）"
    )
    context_trail: list[str] = Field(
        default_factory=list, description="上下文轨迹（近 N 轮摘要）"
    )
    last_updated_at: datetime | None = Field(
        default=None, description="状态最后更新时间"
    )


@runtime_checkable
class DSMReader(Protocol):
    """DSM 读接口（Memory V2 ↔ DSM 边界，票 18 / ADR 0011）。

    由 DSM 服务实现，主会话流调用。Memory V2 本身不调用此接口——它只定义边界，
    确保 EvidencePack 与 CurrentState 是并行、独立的两份数据。
    """

    def read_current_state(
        self,
        tenant_id: str,
        user_id: str,
        session_id: str | None = None,
    ) -> CurrentState:
        """读取指定 scope 的当前对话状态快照。"""
        ...
