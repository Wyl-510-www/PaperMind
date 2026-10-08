"""Tests for server/memory_v2/scorer.py"""

import pytest
from typing import Any

from server.memory_v2.contracts import EvidenceItem, MemoryType, Modality
from server.memory_v2.retrieve.scorer import (
    Scorer,
    SEMANTIC_WEIGHT,
    LEXICAL_WEIGHT,
    CONFIDENCE_WEIGHT,
    IMPORTANCE_WEIGHT,
    RECENCY_WEIGHT,
)


# ─── FakeReranker ────────────────────────────────────────────────────────────

class FakeReranker:
    """测试用 fake reranker，返回预设分数"""

    def __init__(self, scores: dict[str, float]):
        self._scores = scores

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        """按预设 scores 重排"""
        for cand in candidates:
            memory_id = cand.get("memory_id", cand.get("event_id"))
            cand["rerank_score"] = self._scores.get(memory_id, 0.5)
        return sorted(candidates, key=lambda c: c["rerank_score"], reverse=True)


# ─── 打分公式测试 ────────────────────────────────────────────────────────────

def test_scoring_formula_weights():
    """打分公式权重为命名常量"""
    assert SEMANTIC_WEIGHT + LEXICAL_WEIGHT + CONFIDENCE_WEIGHT + IMPORTANCE_WEIGHT + RECENCY_WEIGHT == 1.0


def test_score_and_trim_basic():
    """基本打分：按 final_score 排序"""
    scorer = Scorer()
    reranker = FakeReranker({"m1": 0.9, "m2": 0.5})

    candidates = [
        {
            "memory_id": "m1",
            "score": 0.9,
            "confidence": 0.8,
            "importance": 0.7,
            "modality": "fact",
            "status": "active",
            "content": "用户不吃香菜",
        },
        {
            "memory_id": "m2",
            "score": 0.5,
            "confidence": 0.6,
            "importance": 0.5,
            "modality": "fact",
            "status": "active",
            "content": "用户喜欢甜食",
        },
    ]

    items = scorer.score_and_trim(
        candidates=candidates,
        query="test",
        token_budget=1000,
        reranker=reranker,
    )

    # m1 分数高排前面
    assert len(items) == 2
    assert items[0].memory_id == "m1"
    assert items[0].final_score > items[1].final_score


# ─── token budget 裁剪测试 ───────────────────────────────────────────────────

def test_token_budget_continue_on_oversized(count_tokens_called=[]):
    """遇到超预算的长候选时 continue 跳过而非 break（修复原方案 6.4 bug）"""
    scorer = Scorer(count_tokens=lambda text: len(text))  # 简单计数
    reranker = FakeReranker({"m1": 0.9, "m2": 0.8, "m3": 0.7})

    candidates = [
        {
            "memory_id": "m1",
            "score": 0.9,
            "confidence": 0.9,
            "importance": 0.8,
            "modality": "fact",
            "status": "active",
            "content": "短内容",  # 3 tokens
        },
        {
            "memory_id": "m2",
            "score": 0.8,
            "confidence": 0.8,
            "importance": 0.7,
            "modality": "fact",
            "status": "active",
            "content": "这是一条非常非常非常非常非常长的内容" * 10,  # 超长
        },
        {
            "memory_id": "m3",
            "score": 0.7,
            "confidence": 0.7,
            "importance": 0.6,
            "modality": "fact",
            "status": "active",
            "content": "中等内容",  # 4 tokens
        },
    ]

    items = scorer.score_and_trim(
        candidates=candidates,
        query="test",
        token_budget=10,  # 只能容纳 m1 + m3，m2 超预算
        reranker=reranker,
    )

    # m2 超预算被跳过，但 m3 仍被保留（不是 break 掉后续）
    memory_ids = [item.memory_id for item in items]
    assert "m1" in memory_ids
    assert "m2" not in memory_ids
    assert "m3" in memory_ids  # 关键：m3 没有被 m2 break 掉


# ─── 最低阈值测试 ────────────────────────────────────────────────────────────

def test_min_threshold_filters_low_scores():
    """最低阈值过滤低相关候选"""
    scorer = Scorer(min_threshold=0.6)
    reranker = FakeReranker({"m1": 0.9, "m2": 0.4})

    candidates = [
        {
            "memory_id": "m1",
            "score": 0.9,
            "confidence": 0.8,
            "importance": 0.7,
            "modality": "fact",
            "status": "active",
            "content": "高分候选",
        },
        {
            "memory_id": "m2",
            "score": 0.4,
            "confidence": 0.5,
            "importance": 0.4,
            "modality": "fact",
            "status": "active",
            "content": "低分候选",
        },
    ]

    items = scorer.score_and_trim(
        candidates=candidates,
        query="test",
        token_budget=1000,
        reranker=reranker,
    )

    # m2 低于阈值被过滤
    assert len(items) == 1
    assert items[0].memory_id == "m1"


# ─── evidence_level 填充测试 ─────────────────────────────────────────────────

def test_evidence_level_filled():
    """EvidenceItem 的 usage 字段由 derive_evidence_level 填充"""
    scorer = Scorer()
    reranker = FakeReranker({"m1": 0.9})

    candidates = [
        {
            "memory_id": "m1",
            "score": 0.9,
            "confidence": 0.9,  # 高置信度
            "importance": 0.8,
            "modality": "fact",  # fact
            "status": "active",
            "content": "用户不吃香菜",
        },
    ]

    items = scorer.score_and_trim(
        candidates=candidates,
        query="test",
        token_budget=1000,
        reranker=reranker,
    )

    # usage 应为 "confirmed"（confidence=0.9, modality=fact, status=active）
    assert items[0].usage == "confirmed"


# ─── slot 去重测试 ───────────────────────────────────────────────────────────

def test_slot_deduplication():
    """昵称/禁忌等 slot 只保留唯一 active 版本（最新）"""
    scorer = Scorer()
    reranker = FakeReranker({"m1": 0.9, "m2": 0.8})

    candidates = [
        {
            "memory_id": "m1",
            "score": 0.9,
            "confidence": 0.9,
            "importance": 0.8,
            "modality": "fact",
            "status": "active",
            "predicate": "nickname",
            "content": "小明",
            "source_date": "2026-07-31T10:00:00Z",
        },
        {
            "memory_id": "m2",
            "score": 0.8,
            "confidence": 0.8,
            "importance": 0.7,
            "modality": "fact",
            "status": "active",
            "predicate": "nickname",
            "content": "老王",
            "source_date": "2026-07-30T10:00:00Z",  # 更早
        },
    ]

    items = scorer.score_and_trim(
        candidates=candidates,
        query="test",
        token_budget=1000,
        reranker=reranker,
    )

    # slot 去重：只保留最新的 m1
    assert len(items) == 1
    assert items[0].memory_id == "m1"


# ─── 分类型 recency 衰减测试 ──────────────────────────────────────────────

def test_type_specific_recency_decay():
    """分类型 recency：稳定事实中性，短期状态按时间衰减（简化实现）"""
    from datetime import datetime, timezone, timedelta

    scorer = Scorer()
    now = datetime.now(timezone.utc)

    # 稳定事实（semantic）不受时间影响
    semantic_old = {
        "memory_type": "semantic",
        "source_date": (now - timedelta(days=100)).isoformat(),
    }
    semantic_new = {
        "memory_type": "semantic",
        "source_date": (now - timedelta(days=1)).isoformat(),
    }
    # 稳定事实（semantic）不受时间影响，返回 1.0（不衰减）
    assert scorer._type_specific_recency(semantic_old) == 1.0
    assert scorer._type_specific_recency(semantic_new) == 1.0

    # 短期状态（state）越新越相关，30 天内衰减
    state_fresh = {
        "memory_type": "state",
        "source_date": (now - timedelta(days=1)).isoformat(),
    }
    state_old = {
        "memory_type": "state",
        "source_date": (now - timedelta(days=29)).isoformat(),
    }
    state_ancient = {
        "memory_type": "state",
        "source_date": (now - timedelta(days=100)).isoformat(),
    }

    fresh_score = scorer._type_specific_recency(state_fresh)
    old_score = scorer._type_specific_recency(state_old)
    ancient_score = scorer._type_specific_recency(state_ancient)

    # 新 > 旧 > 古老（衰减）
    assert fresh_score > old_score > ancient_score
    assert fresh_score > 0.9  # 1 天前应接近 1.0
    assert ancient_score == 0.3  # 超 30 天固定 0.3


# ─── 证据优先级冲突裁决测试 ──────────────────────────────────────────────────

def test_conflict_resolution():
    """冲突裁决：同 subject+predicate 只保留最高分（Story 33-35 简化实现）"""
    scorer = Scorer()
    reranker = FakeReranker({"m1": 0.9, "m2": 0.5})

    candidates = [
        {
            "memory_id": "m1",
            "score": 0.9,
            "confidence": 0.9,
            "importance": 0.8,
            "modality": "fact",
            "status": "active",
            "subject_id": "user",
            "predicate": "diet.preference",
            "content": "用户喜欢甜食（最新）",
        },
        {
            "memory_id": "m2",
            "score": 0.5,
            "confidence": 0.7,
            "importance": 0.6,
            "modality": "fact",
            "status": "active",
            "subject_id": "user",
            "predicate": "diet.preference",
            "content": "用户喜欢咸食（旧）",
        },
    ]

    items = scorer.score_and_trim(
        candidates=candidates,
        query="test",
        token_budget=1000,
        reranker=reranker,
    )

    # 冲突裁决：只保留高分的 m1，m2 被过滤
    assert len(items) == 1
    assert items[0].memory_id == "m1"


def test_conflict_resolution_source_priority_beats_score():
    """来源优先级高于分数：高可信显式证据胜过低可信推断证据（P1-1）。

    m_inferred 分数更高（rerank 0.95），但 source_kind=inferred；
    m_explicit 分数低（rerank 0.5），但 source_kind=user_turn（最高优先级）。
    修复前：按 final_score 去重 → 保留 m_inferred（错误）。
    修复后：按 source_kind 优先级 → 保留 m_explicit。
    """
    scorer = Scorer()
    reranker = FakeReranker({"m_inferred": 0.95, "m_explicit": 0.5})

    candidates = [
        {
            "memory_id": "m_inferred",
            "score": 0.95,
            "confidence": 0.9,
            "modality": "fact",
            "status": "active",
            "subject_id": "user",
            "predicate": "diet.preference",
            "content": "推断用户可能喜欢香菜",
            "source_kind": "inferred",
        },
        {
            "memory_id": "m_explicit",
            "score": 0.5,
            "confidence": 0.9,
            "modality": "fact",
            "status": "active",
            "subject_id": "user",
            "predicate": "diet.preference",
            "content": "用户明确说不吃香菜",
            "source_kind": "user_turn",
        },
    ]

    items = scorer.score_and_trim(
        candidates=candidates, query="test", token_budget=1000, reranker=reranker
    )

    # 高优先级来源胜出，即便分数更低
    assert len(items) == 1
    assert items[0].memory_id == "m_explicit"


def test_conflict_resolution_same_source_falls_back_to_score():
    """同来源类型时回退到 final_score（P1-1）。"""
    scorer = Scorer()
    reranker = FakeReranker({"hi": 0.9, "lo": 0.4})

    candidates = [
        {
            "memory_id": "lo", "score": 0.4, "confidence": 0.8, "modality": "fact",
            "status": "active", "subject_id": "user", "predicate": "diet.preference",
            "content": "旧偏好", "source_kind": "persistent",
        },
        {
            "memory_id": "hi", "score": 0.9, "confidence": 0.8, "modality": "fact",
            "status": "active", "subject_id": "user", "predicate": "diet.preference",
            "content": "新偏好", "source_kind": "persistent",
        },
    ]

    items = scorer.score_and_trim(
        candidates=candidates, query="test", token_budget=1000, reranker=reranker
    )

    assert len(items) == 1
    assert items[0].memory_id == "hi"


# ─── 票 08：Scorer 确定性与质量加固 ───────────────────────────────────────────

def test_scorer_recency_deterministic_with_clock_injection():
    """clock 注入使 recency 计算确定（P2-4）。"""
    from datetime import datetime, timezone, timedelta

    fixed_now = datetime(2026, 8, 1, 12, 0, 0, tzinfo=timezone.utc)
    scorer = Scorer(clock=lambda: fixed_now)

    # state 类型，1 天前
    cand = {
        "memory_type": "state",
        "source_date": (fixed_now - timedelta(days=1)).isoformat(),
    }
    recency = scorer._type_specific_recency(cand)

    # 衰减公式：1 天前 → 1.0 - (1/30)*0.7 ≈ 0.9767
    expected = 1.0 - (1 / 30) * 0.7
    assert abs(recency - expected) < 0.01


def test_min_threshold_default_nonzero():
    """min_threshold 默认非零，过滤低分噪音（P2-5）。"""
    from server.memory_v2.retrieve.scorer import DEFAULT_MIN_THRESHOLD

    # 默认阈值应非零（如 0.15）
    assert DEFAULT_MIN_THRESHOLD > 0
    assert DEFAULT_MIN_THRESHOLD <= 0.2  # 合理范围

    scorer = Scorer()
    reranker = FakeReranker({"low": 0.01, "hi": 0.5})

    candidates = [
        {
            "memory_id": "low", "score": 0.01, "confidence": 0.1, "importance": 0.2,
            "modality": "fact", "status": "active",
        },
        {
            "memory_id": "hi", "score": 0.5, "confidence": 0.8, "importance": 0.7,
            "modality": "fact", "status": "active",
        },
    ]

    items = scorer.score_and_trim(
        candidates=candidates, query="test", token_budget=1000, reranker=reranker
    )

    # 低分被默认阈值过滤（final_score = 0.45*0.01 + 0.15*0.1 + 0.1*0.2 + 0.1*1.0 ≈ 0.14 < 0.15）
    assert len(items) == 1
    assert items[0].memory_id == "hi"


def test_slot_dedup_by_subject_and_predicate():
    """slot 去重按 (subject_id, predicate) 聚合，不同主体独立（P2-6）。"""
    scorer = Scorer()
    reranker = FakeReranker({"u1": 0.9, "u2": 0.85, "idol": 0.8})

    candidates = [
        {
            "memory_id": "u1", "score": 0.9, "confidence": 0.9, "modality": "fact",
            "status": "active", "subject_id": "user", "predicate": "nickname",
            "content": "用户昵称小明",
        },
        {
            "memory_id": "u2", "score": 0.85, "confidence": 0.85, "modality": "fact",
            "status": "active", "subject_id": "user", "predicate": "nickname",
            "content": "用户昵称老王（旧）",
        },
        {
            "memory_id": "idol", "score": 0.8, "confidence": 0.8, "modality": "fact",
            "status": "active", "subject_id": "idol:123", "predicate": "nickname",
            "content": "偶像昵称小花",
        },
    ]

    items = scorer.score_and_trim(
        candidates=candidates, query="test", token_budget=1000, reranker=reranker
    )

    # user.nickname 保留高分的 u1，idol:123.nickname 保留 idol（不同主体独立）
    assert len(items) == 2
    ids = {item.memory_id for item in items}
    assert ids == {"u1", "idol"}

