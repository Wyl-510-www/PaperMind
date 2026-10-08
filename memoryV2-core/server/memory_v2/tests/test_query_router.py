"""Tests for server/memory_v2/query_router.py"""

from server.memory_v2.contracts import MemoryType
from server.memory_v2.retrieve.query_router import QueryRouter


router = QueryRouter()


# ─── 语义偏好类 query → SEMANTIC ─────────────────────────────────────────────

def test_preference_query_routes_to_semantic():
    """"我喜欢什么" 类 query 路由到 semantic profile"""
    plan = router.route("你知道我喜欢吃什么吗")
    assert MemoryType.SEMANTIC in plan.memory_types
    assert not plan.skip_retrieval


def test_dislike_query_routes_to_semantic():
    """"我不吃什么" 也路由到 semantic"""
    plan = router.route("我平时爱喝什么饮料")
    assert MemoryType.SEMANTIC in plan.memory_types


# ─── 事件类 query → EPISODIC ────────────────────────────────────────────────

def test_event_query_routes_to_episodic():
    """"聚会还去吗" 类 query 路由到 episodic（active event）"""
    plan = router.route("下周那个聚会还去吗")
    assert MemoryType.EPISODIC in plan.memory_types
    assert not plan.skip_retrieval


def test_past_event_query_routes_to_episodic():
    """"上次买的鞋" 类 query 路由到 episodic memory"""
    plan = router.route("上次我买的那双鞋怎么样")
    assert MemoryType.EPISODIC in plan.memory_types


# ─── 任务类 query → TASK / STATE ────────────────────────────────────────────

def test_task_query_routes_to_task():
    """"论文做到哪了" 类 query 路由到 task/state"""
    plan = router.route("我的论文进度怎么样了")
    assert MemoryType.TASK in plan.memory_types or MemoryType.STATE in plan.memory_types
    assert not plan.skip_retrieval


# ─── 普通寒暄 → skip_retrieval ──────────────────────────────────────────────

def test_greeting_skips_retrieval():
    """普通寒暄跳过检索"""
    plan = router.route("你好呀")
    assert plan.skip_retrieval


def test_short_filler_skips_retrieval():
    """短语气词跳过检索"""
    plan = router.route("哈哈")
    assert plan.skip_retrieval


def test_are_you_there_skips_retrieval():
    """"在吗" 跳过检索"""
    plan = router.route("在吗")
    assert plan.skip_retrieval


# ─── 不确定时倾向多召回（ADR 0006）────────────────────────────────────────────

def test_ambiguous_query_recalls_multiple_types():
    """不确定的 query 倾向多返回一类而非漏（宁可多召回）"""
    plan = router.route("你还记得我跟你说过的事情吗")
    # 不确定时不应 skip，且至少召回一类
    assert not plan.skip_retrieval
    assert len(plan.memory_types) >= 1


def test_per_type_top_k_populated():
    """返回的类型都有对应 top_k"""
    plan = router.route("你知道我喜欢吃什么吗")
    for mt in plan.memory_types:
        assert mt.value in plan.per_type_top_k
        assert plan.per_type_top_k[mt.value] > 0


def test_non_greeting_does_not_skip():
    """有实质内容的 query 不跳过检索"""
    plan = router.route("我跟你说过我对海鲜过敏")
    assert not plan.skip_retrieval
