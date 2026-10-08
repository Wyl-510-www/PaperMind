"""Speech Act 分类单元测试。"""
import pytest
from server.memory_v2.speech_act import (
    MemorySpeechAct,
    classify_speech_act,
    is_high_risk,
    needs_clarification,
)


class TestClassifySpeechAct:
    """确定性规则分类测试。"""

    # ---- QUERY_EXISTING ----
    @pytest.mark.parametrize("text", [
        "你还应该叫我阿晚吗",
        "还能叫我阿晚吗",
        "我应该叫你阿晚吗",
        "我喜欢什么",
        "我不喜欢什么",
        "我爱吃什么",
        "我最喜欢什么",
        "你记得我不吃香菜吗",
        "我是不是不喜欢吃辣",
    ])
    def test_query_existing(self, text):
        assert classify_speech_act(text) == MemorySpeechAct.QUERY_EXISTING

    # ---- EXPLICIT_UPDATE ----
    @pytest.mark.parametrize("text", [
        "以后叫我小满",
        "改叫晚晚吧",
        "从现在开始我喜欢吃辣了",
        "我现在更喜欢微辣",
        "我现在不喜欢吃香菜了",
        "帮我改成叫我小满",
    ])
    def test_explicit_update(self, text):
        assert classify_speech_act(text) == MemorySpeechAct.EXPLICIT_UPDATE

    # ---- EXPLICIT_DELETE ----
    @pytest.mark.parametrize("text", [
        "不要再叫我阿晚了",
        "这个称呼失效了",
        "不用了谢谢",
        "取消周六的聚会",
        "删掉那条记忆",
        "不要了",
    ])
    def test_explicit_delete(self, text):
        assert classify_speech_act(text) == MemorySpeechAct.EXPLICIT_DELETE

    # ---- AMBIGUOUS ----
    @pytest.mark.parametrize("text", [
        "可以叫我小公主吗",
        "我喜欢辣吗",
        "今天想吃什么好呢",
        "你在干嘛呢",
    ])
    def test_ambiguous(self, text):
        assert classify_speech_act(text) == MemorySpeechAct.AMBIGUOUS

    # ---- ASSERT ----
    @pytest.mark.parametrize("text", [
        "我不吃香菜",
        "今天天气真好",
        "我平时喝无糖乌龙茶",
        "我养了一只猫",
        "你上周推荐的那家火锅很不错",
    ])
    def test_assert(self, text):
        assert classify_speech_act(text) == MemorySpeechAct.ASSERT

    # ---- 优先级：DELETE > QUERY ----
    def test_delete_before_query(self):
        """包含删除标记的句子不应被误判为问句。"""
        assert classify_speech_act("能不能不要再叫我阿晚了") == MemorySpeechAct.EXPLICIT_DELETE

    # ---- 优先级：UPDATE > AMBIGUOUS ----
    def test_update_before_ambiguous(self):
        """以"吗"结尾但包含更新标记 → 应为更新。"""
        assert classify_speech_act("以后叫我小满可以吗") == MemorySpeechAct.EXPLICIT_UPDATE

    # ---- 空输入 ----
    def test_empty_text(self):
        assert classify_speech_act("") == MemorySpeechAct.ASSERT
        assert classify_speech_act("   ") == MemorySpeechAct.ASSERT


class TestHighRisk:
    """高敏字段检测测试。"""

    @pytest.mark.parametrize("text", [
        "可以叫我小公主吗",
        "以后叫我晚晚",
        "不要叫我老婆",
        "我的昵称是什么",
        "他是我的朋友",
        "我的名字是林晚",
    ])
    def test_high_risk(self, text):
        assert is_high_risk(text) is True

    @pytest.mark.parametrize("text", [
        "今天天气真好",
        "我不吃香菜",
        "推荐一家餐厅",
        "明天去游泳",
    ])
    def test_not_high_risk(self, text):
        assert is_high_risk(text) is False


class TestNeedsClarification:
    """ADR 0014: AMBIGUOUS + 高敏 → 需要澄清。"""

    def test_ambiguous_high_risk(self):
        assert needs_clarification("可以叫我小公主吗") is True

    def test_ambiguous_not_high_risk(self):
        assert needs_clarification("今天想吃什么好呢") is False

    def test_assert_not_clarify(self):
        assert needs_clarification("我不吃香菜") is False

    def test_query_not_clarify(self):
        """QUERY_EXISTING 不是 AMBIGUOUS，不需要澄清（直接不写即可）。"""
        assert needs_clarification("你还应该叫我阿晚吗") is False
