"""Memory routing: lane planning (TypedWriteRouter) and dispatch (MemoryDispatcher).

TypedWriteRouter: 抽取前 lane 规划（确定性关键词匹配）
MemoryDispatcher: 门控后分发（按 WriteDecision.route 分发到对应 store）
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from ..contracts import MemoryType, WriteDecision, ExtractionLane, LanePlan
from ..store.entity_store import EntityStore
from ..store.fact_store import FactStore
from ..store.event_store import EventStore
from ..critical_identity import is_critical_predicate
logger = logging.getLogger(__name__)


# ============================================================================
# TypedWriteRouter: gate 前 lane 规划
# ============================================================================

# 5 组关键词，匹配任一激活对应 lane
# P1-4修复：扩展EVENT_MARKERS覆盖更多任务/日程表达
EVENT_MARKERS = frozenset({
    # 原有：会议和安排类
    "安排", "改期", "取消", "推迟", "提前", "约了", "聚会", "会议", "活动",
    "任务", "计划", "待办", "日程", "预约", "订了", "定了", "要去", "准备",

    # P1-4新增：任务类
    "在做", "在改", "在写", "在准备", "正在", "要做", "得做", "需要完成",
    "在完成", "正进行",

    # P1-4新增：交付类
    "交", "提交", "上交", "交付", "初稿", "终稿", "草稿", "要交", "得交",

    # P1-4新增：日程类
    "每周", "每天", "通常", "一般", "固定", "周一", "周二", "周三", "周四",
    "周五", "周六", "周日", "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday",

    # P1-4新增：导师/第三方任务
    "让我", "要求我", "希望我", "安排我", "叫我", "催我",
})

ENTITY_MARKERS = frozenset({
    # 核心家庭成员
    "妈妈", "爸爸", "老婆", "老公", "孩子", "儿子", "女儿",
    "我妈", "我爸", "父亲", "母亲", "爷爷", "奶奶", "外公", "外婆",
    "哥哥", "姐姐", "弟弟", "妹妹", "姐夫", "妹夫", "嫂子", "弟媳",
    "叔叔", "阿姨", "舅舅", "姑姑", "姨妈", "伯伯",
    
    # 情感关系
    "女朋友", "男朋友", "前任", "前女友", "前男友", "爱人", "伴侣",
    "媳妇", "老伴",
    
    # 社交关系
    "朋友", "闺蜜", "兄弟", "姐妹", "好友", "发小", "死党",
    "我朋友", "朋友圈", "铁哥们",
    
    # 工作关系
    "同事", "老板", "上司", "下属", "领导", "经理", "主管", "总监",
    "我同事", "我老板", "同行", "合伙人", "搭档", "助理", "秘书",
    
    # 学习关系
    "老师", "同学", "教授", "导师", "学生", "师父", "师傅", "徒弟",
    "我老师", "我同学", "班主任", "辅导员", "教练", "健身教练",
    "游泳教练", "瑜伽教练", "钢琴老师", "吉他老师",
    
    # 居住关系
    "室友", "舍友", "同屋", "邻居", "房东", "房客", "租客", "楼上", "楼下",
    
    # 服务关系
    "医生", "护士", "保姆", "月嫂", "司机", "快递员", "外卖员",
    "理发师", "造型师", "美容师", "按摩师", "私教",
    "律师", "会计", "顾问", "中介",
    
    # 宠物
    "宠物", "猫", "狗", "猫咪", "狗狗", "小猫", "小狗", "猫猫", "狗子",
    "金毛", "哈士奇", "泰迪", "柯基", "萨摩耶", "拉布拉多",
    "鹦鹉", "仓鼠", "兔子", "乌龟", "鱼",
    
    # 称谓代词
    "他", "她", "他们", "她们", "它", "ta", "TA",
    
    # 角色身份
    "偶像", "明星", "歌手", "演员", "作家", "博主", "UP主",
    "主播", "网红",
})

POLICY_MARKERS = frozenset({
    "不要", "别再", "不许", "禁止", "隐私", "每句话", "不能", "少问", "别问",
    "叫我", "称呼", "语气", "风格", "态度", "回复", "别", "不用", "不喜欢被",
})

UPDATE_MARKERS = frozenset({
    "改成", "不是", "纠正", "修正", "更正", "其实", "应该是", "错了", "搞错了",
    "已经完成", "完成了", "做完了", "不去了", "取消了", "算了",
})


# Phase 5D: LLM 补漏用 lane 描述
_LLM_CONFIRM_DESC = {
    "event_task": "事件/任务/日程，如周六聚会、下周五出差、记得买牛奶",
    "entity_relation": "第三方实体关系，如妈妈喜欢种花、朋友不吃辣、同事要离职",
    "behavior_policy": "行为约束/称呼偏好/回复风格，如不准抽烟、别叫我宝宝、说话温柔点",
    "update_delete": "纠正/更新/删除指令，如不是我喜欢甜的、聚会改成周日、取消面试",
}


class TypedWriteRouter:
    """Lane 规划器：关键词初筛 + LLM 补漏（取并集，LLM 只加不删）。

    ADR 0017: keyword ∪ LLM, LLM only adds never removes.
    """

    def __init__(self, llm_client=None):
        self._llm = llm_client

    def plan(self, user_text: str) -> LanePlan:
        """同步版本：仅关键词匹配（向后兼容）。"""
        lanes: list[ExtractionLane] = [ExtractionLane.SEMANTIC]
        reason_codes: dict[str, str] = {"semantic": "baseline"}

        self._keyword_match(user_text, lanes, reason_codes)
        return LanePlan(lanes=lanes, reason_codes=reason_codes)

    async def plan_async(self, user_text: str) -> LanePlan:
        """异步版本：关键词初筛 + LLM 补漏。

        P1-4修复：LLM补漏改为始终启用（当无lane命中或仅semantic时）。
        LLM 只加不删，不否定关键词的结果。
        """
        lanes: list[ExtractionLane] = [ExtractionLane.SEMANTIC]
        reason_codes: dict[str, str] = {"semantic": "baseline"}

        keyword_lanes = self._keyword_match(user_text, lanes, reason_codes)

        # P1-4修复：LLM补漏策略调整
        # 触发条件：无lane命中 或 仅semantic兜底
        llm_supplement_needed = (
            len(keyword_lanes) == 0 or  # 无非semantic lane命中
            (len(keyword_lanes) == 1 and "semantic" in reason_codes and len(reason_codes) == 1)  # 仅semantic
        )

        if llm_supplement_needed and self._llm is not None:
            extra = await self._llm_confirm(user_text)
            for lane_name in extra:
                if lane_name not in keyword_lanes:
                    lane = ExtractionLane(lane_name)
                    lanes.append(lane)
                    reason_codes[lane_name] = "LLM_SUPPLEMENT"
                    logger.info(
                        f"P1-4: LLM supplement triggered. input={user_text[:50]}..., "
                        f"keyword_lanes={list(keyword_lanes)}, llm_added={lane_name}"
                    )

        return LanePlan(lanes=lanes, reason_codes=reason_codes)

    def _keyword_match(self, user_text, lanes, reason_codes) -> set[str]:
        """关键词匹配，返回命中的非 semantic lane 名集合。"""
        matched = set()
        if any(marker in user_text for marker in EVENT_MARKERS):
            lanes.append(ExtractionLane.EVENT_TASK)
            reason_codes["event_task"] = "EVENT_MARKERS"
            matched.add("event_task")
        if any(marker in user_text for marker in ENTITY_MARKERS):
            lanes.append(ExtractionLane.ENTITY_RELATION)
            reason_codes["entity_relation"] = "ENTITY_MARKERS"
            matched.add("entity_relation")
        if any(marker in user_text for marker in POLICY_MARKERS):
            lanes.append(ExtractionLane.BEHAVIOR_POLICY)
            reason_codes["behavior_policy"] = "POLICY_MARKERS"
            matched.add("behavior_policy")
        if any(marker in user_text for marker in UPDATE_MARKERS):
            lanes.append(ExtractionLane.UPDATE_DELETE)
            reason_codes["update_delete"] = "UPDATE_MARKERS"
            matched.add("update_delete")
        return matched

    async def _llm_confirm(self, user_text: str) -> list[str]:
        """LLM 补漏：返回关键词漏掉的 lane 名列表。"""
        desc = "\n".join(f"- {l}: {d}" for l, d in _LLM_CONFIRM_DESC.items())
        prompt = f"""用户说："{user_text}"

以下记忆类型中，哪些是用户这段话确实涉及的？只选确实涉及的，不涉及的不要选。
{desc}

返回 JSON: {{"activate": ["lane1"]}} 或 {{"activate": []}}"""

        try:
            result = await self._llm.structured_extract(
                system_prompt="判断用户输入涉及哪些记忆类型。只选确实涉及的。",
                user_text=prompt,
            )
            if result is None:
                return []
            return result.get("activate", [])
        except Exception:
            logger.warning("LLM lane confirm failed, fallback to keyword only", exc_info=True)
            return []


# ============================================================================
# MemoryDispatcher: gate 后分发
# ============================================================================


class MemoryDispatcher:
    """类型分发器：把门控决策分发到对应存储后端"""

    def __init__(
        self,
        entity_store: EntityStore | None = None,
        fact_store: FactStore | None = None,
        event_store: EventStore | None = None,
        audit_log_path: str | None = None,
        critical_identity_repo=None,
        preference_repo=None,  # P0-4: PreferenceRepository
    ):
        """
        Args:
            entity_store: 第三方实体存储。None 时 ENTITY_RELATION 路由只记日志
            fact_store: semantic 事实存储。None 时 SEMANTIC 路由保持占位（向后兼容）
            event_store: event/task 存储。None 时 EPISODIC/TASK 路由保持占位
            audit_log_path: 审计日志 JSONL 路径。None 时只用 logger
            critical_identity_repo: CriticalIdentityRepo。非 None 时高敏 predicate 双写
        """
        self.entity_store = entity_store
        self.fact_store = fact_store
        self.event_store = event_store
        self.audit_log_path = Path(audit_log_path) if audit_log_path else None
        self.critical_identity = critical_identity_repo
        self.preference_repo = preference_repo  # P0-4

    async def dispatch(
        self,
        decision: WriteDecision,
        tenant_id: str,
        user_id: str,
        source_turn_id: str | None = None,
        occurred_at: datetime | None = None,
        metadata: dict | None = None,
    ):
        """按 decision.route 分发。

        Args:
            metadata: Phase 3 笔记元数据（JSON 字典），传递给 semantic 路由

        Returns:
            memory_id (str) / EntityWriteReceipt / "discarded" / "pending"（DSM 未实现）

        P0-2修复：ENTITY_RELATION路由现在返回EntityWriteReceipt对象，包含完整的ID映射
        """
        # 被拒绝的候选：只记审计日志
        if not decision.accepted:
            self._audit(decision, tenant_id, user_id, "discarded", source_turn_id)
            return "discarded"

        # Ticket 06: 显式删除 → tombstone
        if getattr(decision.candidate, 'explicit_delete', False):
            return self._route_delete(decision, tenant_id, user_id, source_turn_id)

        route = decision.route

        if route == MemoryType.ENTITY_RELATION:
            result = self._route_entity(decision, tenant_id, user_id, source_turn_id)
        elif route == MemoryType.SEMANTIC or route == MemoryType.BEHAVIOR_POLICY:
            result = await self._route_semantic(decision, tenant_id, user_id, source_turn_id, occurred_at=occurred_at, metadata=metadata)
        elif route in (MemoryType.EPISODIC, MemoryType.TASK):
            result = self._route_event(decision, tenant_id, user_id, source_turn_id, occurred_at=occurred_at)
        elif route == MemoryType.PREFERENCE:  # P0-4
            result = await self._route_preference(decision, tenant_id, user_id, source_turn_id, occurred_at=occurred_at)
        elif route == MemoryType.RELATIONSHIP:
            logger.info("RELATIONSHIP route (Phase 2 占位)")
            result = "pending_phase2"
        else:
            logger.warning("未知路由: %s", route)
            result = "discarded"

        self._audit(decision, tenant_id, user_id, result, source_turn_id)
        return result

    def _route_entity(
        self,
        decision: WriteDecision,
        tenant_id: str,
        user_id: str,
        source_turn_id: str | None,
    ):
        """路由到第三方实体存储

        Returns:
            EntityWriteReceipt 或 str（当entity_store为None时返回"pending_no_store"）
        """
        if self.entity_store is None:
            logger.info("ENTITY_RELATION route（无 entity_store，仅记日志）")
            return "pending_no_store"

        # P0-2修复：EntityStore.write()现在返回EntityWriteReceipt
        return self.entity_store.write(decision, tenant_id, user_id, source_turn_id)

    async def _route_semantic(
        self,
        decision: WriteDecision,
        tenant_id: str,
        user_id: str,
        source_turn_id: str | None,
        occurred_at: datetime | None = None,
        metadata: dict | None = None,
    ) -> str:
        """路由到 semantic 事实存储，高敏 predicate 双写 Critical Identity

        Args:
            metadata: Phase 3 笔记元数据，传递给 fact_store
        """
        if self.fact_store is None:
            logger.info("SEMANTIC route（无 fact_store，占位）: fact_key=%s", decision.fact_key)
            return "pending_phase2"

        result = self.fact_store.write_fact(
            decision, tenant_id, user_id, source_turn_id=source_turn_id,
            occurred_at=occurred_at,
            metadata=metadata,
        )

        # 高敏 predicate 双写到 Critical Identity Store
        pred = decision.candidate.predicate
        if self.critical_identity and is_critical_predicate(pred):
            try:
                value = decision.candidate.normalized_text_zh or str(decision.candidate.value or "")
                self.critical_identity.write_fact(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    predicate=pred,
                    value=str(value),
                    source_turn_id=source_turn_id or "",
                    source_span=decision.candidate.source_span or "",
                    confidence=decision.candidate.confidence,
                    explicit=True,
                )
            except Exception:
                logger.exception("CriticalIdentity 双写失败: predicate=%s user=%s", pred, user_id)

        return result

    def _route_event(
        self,
        decision: WriteDecision,
        tenant_id: str,
        user_id: str,
        source_turn_id: str | None,
        occurred_at: datetime | None = None,
    ) -> str:
        """路由到 event/task 存储"""
        if self.event_store is None:
            logger.info("%s route（无 event_store，占位）", decision.route.value)
            return "pending_phase2"
        return self.event_store.create_event(
            decision, tenant_id, user_id, source_turn_id=source_turn_id,
            occurred_at=occurred_at,
        )

    def _route_delete(
        self,
        decision: WriteDecision,
        tenant_id: str,
        user_id: str,
        source_turn_id: str | None,
    ) -> str:
        """P0-7: 显式删除 → tombstone + 事务提交 + 错误处理。

        完整删除流程：
        1. 高敏字段：block_value
        2. 语义事实：更新 status=deleted + 提交事务
        3. 事件：transition 到 CANCELLED 状态
        """
        # 步骤 1: 高敏字段删除 → block_value
        pred = decision.candidate.predicate
        if pred and is_critical_predicate(pred) and self.critical_identity:
            try:
                value = decision.candidate.normalized_text_zh or str(decision.candidate.value or "")
                self.critical_identity.block_value(
                    tenant_id=tenant_id,
                    user_id=user_id,
                    predicate=pred,
                    value=str(value),
                )
                logger.info("DELETE 触发 block_value: predicate=%s value=%s", pred, value)
            except Exception:
                logger.exception("CriticalIdentity 删除操作失败: predicate=%s user=%s", pred, user_id)
                return "delete_critical_identity_failed"

        # 步骤 2: 语义事实删除（通过 fact_key 定位）
        if decision.fact_key and self.fact_store:
            try:
                logger.info("DELETE via fact_key=%s", decision.fact_key)

                # P0-4: 通过 active pointer 定位 memory_id，然后调用 Repository 的 delete_memory 方法
                from sqlalchemy import select
                from server.memory_v2.store.active_fact import ActiveFact

                stmt = select(ActiveFact).where(
                    ActiveFact.tenant_id == tenant_id,
                    ActiveFact.user_id == user_id,
                    ActiveFact.fact_key == decision.fact_key,
                )
                active_pointer = self.fact_store.session.execute(stmt).scalars().first()

                if active_pointer and active_pointer.memory_id:
                    # 调用 Repository 的 delete_memory 方法
                    success = self.fact_store.delete_memory(
                        memory_id=active_pointer.memory_id,
                        tenant_id=tenant_id,
                        user_id=user_id,
                    )

                    if success:
                        logger.info("DELETE 成功: fact_key=%s memory_id=%s",
                                   decision.fact_key, active_pointer.memory_id)
                        return f"deleted:{decision.fact_key}"
                    else:
                        logger.warning("DELETE Repository 调用失败")
                        return "delete_fact_failed"
                else:
                    logger.warning("DELETE 未找到 active pointer: fact_key=%s", decision.fact_key)
                    return f"delete_not_found:{decision.fact_key}"

            except Exception:
                logger.exception("FactStore 删除失败: fact_key=%s", decision.fact_key)
                self.fact_store.session.rollback()
                return "delete_fact_failed"

        # 步骤 3: 事件删除（通过 event_id 定位）
        if decision.object_id and self.event_store:
            try:
                logger.info("DELETE via event_id=%s", decision.object_id)

                # P0-4: 修复 EventStatus 导入路径
                from server.memory_v2.transitions import EventStatus

                # 获取事件以确定当前版本
                event = self.event_store.get_event(decision.object_id)
                if not event:
                    logger.warning("DELETE 未找到事件: event_id=%s", decision.object_id)
                    return f"delete_event_not_found:{decision.object_id}"

                # 调用 transition 迁移到 CANCELLED
                now = datetime.now(timezone.utc)
                success = self.event_store.transition(
                    event_id=decision.object_id,
                    new_status=EventStatus.CANCELLED,
                    expected_version=event.version,
                    now=now,
                )

                if success:
                    logger.info("DELETE 成功: event_id=%s", decision.object_id)
                    return f"deleted_event:{decision.object_id}"
                else:
                    logger.warning("DELETE 版本冲突: event_id=%s", decision.object_id)
                    return f"delete_event_version_conflict:{decision.object_id}"

            except Exception:
                logger.exception("EventStore 删除失败: event_id=%s", decision.object_id)
                return "delete_event_failed"

        logger.warning("DELETE 无法定位目标: fact_key=%s object_id=%s", decision.fact_key, decision.object_id)
        return "delete_no_target"

    def _audit(
        self,
        decision: WriteDecision,
        tenant_id: str,
        user_id: str,
        result: str,
        source_turn_id: str | None,
    ):
        """写审计日志（JSONL 一行一条）"""
        candidate = decision.candidate
        record = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "tenant_id": tenant_id,
            "user_id": user_id,
            "candidate_id": candidate.candidate_id,
            "source_span": candidate.source_span,
            "normalized_text_zh": candidate.normalized_text_zh,
            "memory_type": candidate.memory_type.value,
            "modality": candidate.modality.value,
            "accepted": decision.accepted,
            "route": decision.route.value,
            "reason_code": decision.reason_code,
            "result": result,
            "fact_key": decision.fact_key,
            "source_turn_id": source_turn_id,
        }

        if self.audit_log_path:
            self.audit_log_path.parent.mkdir(parents=True, exist_ok=True)
            with self.audit_log_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        else:
            logger.info("audit: %s", json.dumps(record, ensure_ascii=False))

    async def _route_preference(
        self,
        decision: WriteDecision,
        tenant_id: str,
        user_id: str,
        source_turn_id: str | None,
        occurred_at: datetime | None = None,
    ) -> str:
        """P0-4: 路由到偏好存储"""
        if self.preference_repo is None:
            logger.info("PREFERENCE route（无 preference_repo，占位）")
            return "pending_no_store"
        
        try:
            # P0-1: 修复字段名（strength → preference_strength, evidence_type → provenance）
            cand = decision.candidate
            fact_id = await self.preference_repo.write_preference(
                tenant_id=tenant_id,
                user_id=user_id,
                domain=cand.domain or "general",
                object_key=cand.object_key or "",
                polarity=cand.polarity or "positive",
                strength=cand.preference_strength or "normal",
                evidence_type=cand.provenance or "inferred",
                source_turn_id=source_turn_id or "",
                source_span=cand.source_span or "",
                confidence=cand.confidence,
            )
            return fact_id
        except Exception:
            logger.exception("Preference 写入失败")
            return "error"
