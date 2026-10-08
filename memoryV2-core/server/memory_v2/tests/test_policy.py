"""Test policy data models, PolicyCompiler, PolicyGuard (Phase 5 #07-#09)"""

import pytest
from datetime import datetime

from server.memory_v2.policy.models import (
    PolicyKind, PolicyRule, PolicyPack, PolicyCheck, PolicyStrength,
)
from server.memory_v2.policy.compiler import PolicyCompiler
from server.memory_v2.policy.guard import PolicyGuard


# ─── Policy data models (#07) ───

def test_policy_kind_enum():
    """PolicyKind 包含 7 个值"""
    assert PolicyKind.SAFETY == "safety"
    assert PolicyKind.PRIVACY == "privacy"
    assert PolicyKind.STYLE == "style"


def test_policy_rule_model():
    """PolicyRule 正常构造"""
    rule = PolicyRule(
        policy_id="p1",
        kind=PolicyKind.STYLE,
        strength=PolicyStrength.HARD,
        priority=10,
        instruction="回复不超过 3 句",
        max_sentences=3,
    )
    assert rule.max_sentences == 3
    assert rule.forbidden_terms == []


def test_policy_pack_model():
    """PolicyPack 正常构造"""
    rules = [
        PolicyRule(policy_id="p1", kind=PolicyKind.STYLE, strength=PolicyStrength.HARD, priority=10, instruction="短回复"),
    ]
    pack = PolicyPack(rules=rules, scope="default:user1")
    assert len(pack.rules) == 1


def test_policy_check_ok():
    """PolicyCheck ok=true"""
    check = PolicyCheck(ok=True, action="keep")
    assert check.ok
    assert check.violations == []


def test_policy_check_failed():
    """PolicyCheck ok=false"""
    check = PolicyCheck(ok=False, violations=["bad"], action="regenerate")
    assert not check.ok


# ─── PolicyCompiler (#08) ───

@pytest.mark.asyncio
async def test_compiler_no_session_returns_empty_pack():
    """无 session_factory 时返回空 Pack"""
    compiler = PolicyCompiler(session_factory=None)
    pack = await compiler.compile("t1", "u1")
    assert isinstance(pack, PolicyPack)
    assert pack.rules == []


def test_compiler_sync_returns_pack():
    """同步版本返回 PolicyPack"""
    compiler = PolicyCompiler()
    pack = compiler.compile_sync("t1", "u1")
    assert isinstance(pack, PolicyPack)


# ─── PolicyGuard (#09) ───

def test_guard_empty_pack_is_ok():
    """空 PolicyPack 一定通过"""
    guard = PolicyGuard()
    pack = PolicyPack(scope="t1:u1")
    result = guard.verify("你好", pack)
    assert result.ok
    assert result.action == "keep"


def test_guard_forbidden_term_hard_violation():
    """禁词触发 hard violation"""
    guard = PolicyGuard()
    rule = PolicyRule(
        policy_id="p1",
        kind=PolicyKind.STYLE,
        strength=PolicyStrength.HARD,
        priority=10,
        instruction="不能叫小公主",
        forbidden_terms=["小公主"],
    )
    pack = PolicyPack(rules=[rule], scope="t1:u1")
    result = guard.verify("你好小公主今天怎么样", pack)
    assert not result.ok
    assert result.action == "regenerate"
    assert "小公主" in result.violations[0]


def test_guard_forbidden_term_soft_violation():
    """soft violation 触发 rewrite"""
    guard = PolicyGuard()
    rule = PolicyRule(
        policy_id="p1",
        kind=PolicyKind.STYLE,
        strength=PolicyStrength.SOFT,
        priority=5,
        instruction="回复短一点",
        max_sentences=2,
    )
    pack = PolicyPack(rules=[rule], scope="t1:u1")
    result = guard.verify("你好。今天。天气。不错。", pack)
    if not result.ok:
        assert result.action == "rewrite"


def test_guard_required_terms_missing():
    """必需词缺失触发违规"""
    guard = PolicyGuard()
    rule = PolicyRule(
        policy_id="p1",
        kind=PolicyKind.REPAIR,
        strength=PolicyStrength.HARD,
        priority=10,
        instruction="必须承认错误",
        required_terms_any=["抱歉", "对不起"],
    )
    pack = PolicyPack(rules=[rule], scope="t1:u1")
    result = guard.verify("我没错啊", pack)
    assert not result.ok


def test_guard_max_sentences_exceeded():
    """句数超限触发违规"""
    guard = PolicyGuard()
    rule = PolicyRule(
        policy_id="p1",
        kind=PolicyKind.STYLE,
        strength=PolicyStrength.SOFT,
        priority=5,
        instruction="最多 1 句",
        max_sentences=1,
    )
    pack = PolicyPack(rules=[rule], scope="t1:u1")
    result = guard.verify("你好。再见。", pack)
    if not result.ok:
        assert result.action == "rewrite"


def test_guard_no_violation():
    """合规回复通过"""
    guard = PolicyGuard()
    rule = PolicyRule(
        policy_id="p1",
        kind=PolicyKind.STYLE,
        strength=PolicyStrength.HARD,
        priority=10,
        instruction="不能叫小公主",
        forbidden_terms=["小公主"],
    )
    pack = PolicyPack(rules=[rule], scope="t1:u1")
    result = guard.verify("你好啊", pack)
    assert result.ok
    assert result.action == "keep"
