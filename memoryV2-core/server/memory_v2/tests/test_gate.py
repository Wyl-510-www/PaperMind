"""Tests for server/memory_v2/gate.py"""

import pytest

from server.memory_v2.write.gate import (
    MemoryGate,
    build_fact_key,
    detect_signals,
    DISALLOWED_MODALITIES,
)
from server.memory_v2.contracts import (
    DeterministicSignals,
    MemoryCandidate,
    MemoryType,
    Modality,
    SubjectRef,
)


# ─── helpers ────────────────────────────────────────────────────────────────

def make_subject(is_current_user: bool = True, name: str = "用户") -> SubjectRef:
    return SubjectRef(
        kind="user" if is_current_user else "person",
        canonical_name=name,
        is_current_user=is_current_user,
    )


def make_candidate(**kwargs) -> MemoryCandidate:
    defaults = dict(
        candidate_id="cand-001",
        subject=make_subject(),
        predicate="diet.dislike",
        value="香菜",
        normalized_text_zh="用户不吃香菜",
        memory_type=MemoryType.SEMANTIC,
        modality=Modality.FACT,
        confidence=0.92,
        durability="stable",
        source_span="我不吃香菜",
    )
    defaults.update(kwargs)
    return MemoryCandidate(**defaults)


# ─── detect_signals ──────────────────────────────────────────────────────────

def test_detect_hypothesis_signal():
    s = detect_signals("如果明天下雨就不去了")
    assert s.has_hypothesis is True


def test_detect_joke_marker():
    s = detect_signals("我开玩笑的啦")
    assert s.has_joke_marker is True


def test_detect_quote_marker():
    s = detect_signals("小说里的台词是这样的")
    assert s.has_quote_marker is True


def test_detect_no_signals():
    s = detect_signals("我不吃香菜")
    assert s.has_hypothesis is False
    assert s.has_joke_marker is False


# ─── build_fact_key ──────────────────────────────────────────────────────────

def test_build_fact_key_basic():
    """基本 fact_key 构造：set 型谓词含 value hash（P2-7 更新）"""
    c = make_candidate(predicate="diet.dislike", value="香菜")
    key = build_fact_key(c)
    # diet.dislike 是 set 型，含 value hash
    assert key.startswith("用户:diet.dislike:")
    assert len(key) > len("用户:diet.dislike:")  # 有 hash 后缀


def test_build_fact_key_with_entity_id():
    c = make_candidate(
        subject=SubjectRef(
            canonical_name="阿宁",
            entity_id="person:aning",
            is_current_user=False,
        ),
        predicate="food.dislike",
    )
    key = build_fact_key(c)
    assert key == "person:aning:food.dislike"


def test_build_fact_key_set_cardinality_includes_value():
    """set 型谓词 fact_key 含 value hash，不同值独立版本化（P2-7 / ADR 0010）。"""
    c1 = make_candidate(predicate="diet.dislike", value="香菜")
    c2 = make_candidate(predicate="diet.dislike", value="芹菜")

    key1 = build_fact_key(c1)
    key2 = build_fact_key(c2)

    # 不同 value → 不同 fact_key（含 value hash），不会互相 supersede
    assert key1 != key2
    assert key1.startswith("用户:diet.dislike:")
    assert key2.startswith("用户:diet.dislike:")


def test_build_fact_key_single_cardinality_ignores_value():
    """single 型谓词 fact_key 不含 value，新值覆盖旧值（P2-7 / ADR 0010）。"""
    c1 = make_candidate(predicate="nickname.current", value="小明")
    c2 = make_candidate(predicate="nickname.current", value="老王")

    key1 = build_fact_key(c1)
    key2 = build_fact_key(c2)

    # 同 predicate → 同 fact_key，新版本 supersede 旧版本
    assert key1 == key2
    assert key1 == "用户:nickname.current"


# ─── 规则 1：置信度过低 ──────────────────────────────────────────────────────

def test_rule1_low_confidence_rejected():
    gate = MemoryGate(minimum_confidence=0.60)
    c = make_candidate(confidence=0.55)
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is False
    assert d.reason_code == "LOW_CONFIDENCE"


def test_rule1_confidence_boundary():
    gate = MemoryGate(minimum_confidence=0.60)
    c = make_candidate(confidence=0.60)
    d = gate.decide(c, DeterministicSignals())
    # 不会因为规则 1 拒绝，但可能被其他规则拒绝
    assert d.reason_code != "LOW_CONFIDENCE"


# ─── 规则 2：modality 不允许 ─────────────────────────────────────────────────

def test_rule2_hypothesis_rejected():
    gate = MemoryGate()
    c = make_candidate(modality=Modality.HYPOTHESIS)
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is False
    assert d.reason_code == "MODALITY_HYPOTHESIS"


def test_rule2_joke_rejected():
    gate = MemoryGate()
    c = make_candidate(modality=Modality.JOKE)
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is False
    assert d.reason_code == "MODALITY_JOKE"


def test_rule2_quote_rejected():
    gate = MemoryGate()
    c = make_candidate(modality=Modality.QUOTE)
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is False
    assert d.reason_code == "MODALITY_QUOTE"


def test_rule2_question_rejected():
    gate = MemoryGate()
    c = make_candidate(modality=Modality.QUESTION)
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is False
    assert d.reason_code == "MODALITY_QUESTION"


# ─── 规则 3：交叉校验 ────────────────────────────────────────────────────────

def test_rule3_hypothesis_conflict_rejected():
    """LLM 标 fact，但原文有'如果' → 拒绝（交叉校验）"""
    gate = MemoryGate()
    c = make_candidate(modality=Modality.FACT, source_span="如果去游泳的话")
    signals = detect_signals(c.source_span)
    d = gate.decide(c, signals)
    assert d.accepted is False
    assert d.reason_code == "HYPOTHESIS_CONFLICT"


def test_rule3_joke_conflict_rejected():
    """LLM 标 fact，但原文有'开玩笑' → 拒绝"""
    gate = MemoryGate()
    c = make_candidate(modality=Modality.FACT, source_span="我开玩笑的")
    signals = detect_signals(c.source_span)
    d = gate.decide(c, signals)
    assert d.accepted is False
    assert d.reason_code == "JOKE_CONFLICT"


def test_rule3_no_conflict_accepted():
    """原文无假设标记，LLM 标 fact → 不触发规则 3"""
    gate = MemoryGate()
    c = make_candidate(modality=Modality.FACT, source_span="我去游泳了")
    signals = detect_signals(c.source_span)
    d = gate.decide(c, signals)
    # 不会因为规则 3 拒绝，但要检查最终是否接受（semantic 要求）
    assert d.reason_code not in ("HYPOTHESIS_CONFLICT", "JOKE_CONFLICT")


def test_rule3_hypothesis_with_llm_hypothesis_rejected():
    """原文有'如果'，LLM 也标 hypothesis → 规则 2 拒绝（而不是规则 3）"""
    gate = MemoryGate()
    c = make_candidate(modality=Modality.HYPOTHESIS, source_span="如果明天去")
    signals = detect_signals(c.source_span)
    d = gate.decide(c, signals)
    assert d.accepted is False
    assert d.reason_code == "MODALITY_HYPOTHESIS"  # 规则 2 先触发


# ─── 规则 4：第三方实体 ──────────────────────────────────────────────────────

def test_rule4_third_party_routed():
    """subject.is_current_user=False → 路由到 ENTITY_RELATION"""
    gate = MemoryGate()
    c = make_candidate(
        subject=make_subject(is_current_user=False, name="阿宁"),
        memory_type=MemoryType.SEMANTIC,
        durability="stable",
    )
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is True
    assert d.route == MemoryType.ENTITY_RELATION
    assert d.reason_code == "THIRD_PARTY_ROUTE"


def test_rule4_current_user_not_routed():
    """subject.is_current_user=True → 不触发规则 4"""
    gate = MemoryGate()
    c = make_candidate(subject=make_subject(is_current_user=True))
    d = gate.decide(c, DeterministicSignals())
    # 继续走 semantic 路径，不走 entity_relation
    assert d.route != MemoryType.ENTITY_RELATION


def test_rule4_third_party_low_confidence_rejected():
    """第三方实体 confidence < 0.85 被拒绝（P1-6 / ADR 0009）。

    修复前：规则 4 绕过 semantic_minimum_confidence（0.85），0.70 的第三方被接受。
    修复后：第三方实体同样检查 0.85 门槛，0.70 被拒绝。
    """
    gate = MemoryGate()
    c = make_candidate(
        subject=make_subject(is_current_user=False, name="张三"),
        memory_type=MemoryType.SEMANTIC,
        durability="stable",
        confidence=0.70,  # 高于通用门槛 0.60，但低于 semantic 门槛 0.85
    )
    d = gate.decide(c, DeterministicSignals())

    # 应被拒绝（与用户画像享有同等门槛）
    assert d.accepted is False
    assert "CONFIDENCE" in d.reason_code or "LOW" in d.reason_code


def test_rule4_third_party_high_confidence_accepted():
    """第三方实体 confidence >= 0.85 才被接受（P1-6 / ADR 0009）。"""
    gate = MemoryGate()
    c = make_candidate(
        subject=make_subject(is_current_user=False, name="张三"),
        memory_type=MemoryType.SEMANTIC,
        durability="stable",
        confidence=0.90,  # 满足 semantic 门槛
    )
    d = gate.decide(c, DeterministicSignals())

    assert d.accepted is True
    assert d.route == MemoryType.ENTITY_RELATION


# ─── 规则 5：semantic 非稳定 ─────────────────────────────────────────────────

def test_rule5_semantic_not_stable_rejected():
    gate = MemoryGate()
    c = make_candidate(memory_type=MemoryType.SEMANTIC, durability="temporary")
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is False
    assert d.reason_code == "SEMANTIC_NOT_STABLE"


def test_rule5_semantic_stable_passes():
    gate = MemoryGate()
    c = make_candidate(memory_type=MemoryType.SEMANTIC, durability="stable")
    d = gate.decide(c, DeterministicSignals())
    # 不会因为规则 5 拒绝
    assert d.reason_code != "SEMANTIC_NOT_STABLE"


# ─── 规则 6：semantic 置信度不足 ─────────────────────────────────────────────

def test_rule6_semantic_confidence_rejected():
    gate = MemoryGate(semantic_minimum_confidence=0.85)
    c = make_candidate(
        memory_type=MemoryType.SEMANTIC,
        durability="stable",
        confidence=0.80,
    )
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is False
    assert d.reason_code == "SEMANTIC_CONFIDENCE"


def test_rule6_semantic_confidence_boundary():
    gate = MemoryGate(semantic_minimum_confidence=0.85)
    c = make_candidate(
        memory_type=MemoryType.SEMANTIC,
        durability="stable",
        confidence=0.85,
    )
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is True


# ─── 规则 7：state 类型 ──────────────────────────────────────────────────────



# ─── semantic 完整流程 ───────────────────────────────────────────────────────

def test_semantic_full_path_accepted():
    """semantic + stable + 高置信度 + 用户本人 → 接受，生成 fact_key"""
    gate = MemoryGate()
    c = make_candidate(
        memory_type=MemoryType.SEMANTIC,
        durability="stable",
        confidence=0.92,
        subject=make_subject(is_current_user=True),
        predicate="diet.dislike",
    )
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is True
    assert d.route == MemoryType.SEMANTIC
    assert d.reason_code == "STABLE_SEMANTIC"
    # diet.dislike 是 set 型谓词，fact_key 含 value hash（ADR 0010）
    assert d.fact_key.startswith("用户:diet.dislike:")


# ─── 其他类型 ────────────────────────────────────────────────────────────────

def test_episodic_accepted():
    gate = MemoryGate()
    c = make_candidate(memory_type=MemoryType.EPISODIC)
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is True
    assert d.route == MemoryType.EPISODIC


def test_discard_rejected():
    gate = MemoryGate()
    c = make_candidate(memory_type=MemoryType.DISCARD)
    d = gate.decide(c, DeterministicSignals())
    assert d.accepted is False
    assert d.reason_code == "EXTRACTOR_DISCARD"
