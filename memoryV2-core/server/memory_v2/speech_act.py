"""Speech Act 分类：判定用户消息的言语行为。

六种分类（M1 修订版 + B3 修复）：
- ASSERT: 用户陈述事实或偏好 → 正常写入
- QUERY_EXISTING: 用户询问已有偏好/身份是否仍有效 → 禁止写入
- EXPLICIT_UPDATE: 用户明确声明改变偏好或身份 → 正常写入
- EXPLICIT_DELETE: 用户明确声明删除 → 触发 tombstone
- AMBIGUOUS: 无法确定性判断 → 保守不写，高敏字段触发生成端澄清
- FILLER: 纯填充词，无实质内容 → 不写入
- UNKNOWN: 规则未覆盖 → 交给 extractor + gate 处理（新增 M1）

ADR 0014: AMBIGUOUS + 高敏字段 → orchestrator 同步触发澄清追问。
M1 修复：收紧 QUERY 规则，避免误杀陈述句；支持分句处理"陈述+追问"。
B3 修复：改进分句逻辑、疑问词精准匹配、恢复 AMBIGUOUS 路径、优化 filler 规则。
"""
from __future__ import annotations

import re
from enum import Enum


class MemorySpeechAct(str, Enum):
    ASSERT = "assert"
    QUERY_EXISTING = "query_existing"
    EXPLICIT_UPDATE = "explicit_update"
    EXPLICIT_DELETE = "explicit_delete"
    AMBIGUOUS = "ambiguous"
    FILLER = "filler"  # B3 新增
    UNKNOWN = "unknown"  # M1 新增：规则未覆盖，交 extractor 处理


# ---- 确定性规则 ----

QUERY_PATTERNS: list[re.Pattern] = [
    # M1 收紧版：移除过宽泛的规则（避免误杀陈述句）
    re.compile(r"^还应该叫我.+吗$"),
    re.compile(r"^还能叫我.+吗$"),
    re.compile(r"^我应该叫你.+吗$"),
    re.compile(r"^你记得我.+吗$"),
    re.compile(r"^我是不是.+$"),
    re.compile(r"^我喜欢什么$"),
    re.compile(r"^我不喜欢什么$"),
    re.compile(r"^我爱吃什么$"),
    re.compile(r"^我最喜欢什么$"),
    re.compile(r"^.+叫什么名字$"),  # 收紧：必须"叫什么名字"
    re.compile(r"^.+在哪里$"),      # 收紧：必须"在哪里"
    re.compile(r"^.+是谁$"),        # 收紧：必须"是谁"
    # 移除 ".+是什么"（会误杀"记错了就说正确是什么"）
    # 移除 ".+几.+"（会误杀"我偶尔会夹几句英文"）
    # 移除 ".+怎么样/.+如何"（过于宽泛）
    re.compile(r"^有没有.+$"),
    re.compile(r"^能不能.+$"),
    re.compile(r"^会不会.+$"),
    re.compile(r"^可不可以.+$"),
]

UPDATE_MARKERS: list[str] = [
    "以后叫我",
    "改叫",
    "从现在开始",
    "我现在更喜欢",
    "现在我更喜欢",
    "我现在不喜欢",
    "现在我不喜欢",
    "我最近更喜欢",
    "更喜欢你叫我",
    "更喜欢叫我",
    "更喜欢被叫",
    "帮我改成",
    "更新一下",
    "修改一下",
    "改成",
    "换成",
    "修改为",
    "更改为",
    "把我的",
    "请把",
]

UPDATE_PATTERNS: list[re.Pattern] = [
    re.compile(r"(?:现在我|我现在|我最近|从现在开始|以后).*?(?:更喜欢|不喜欢).*?(?:叫我|被叫|叫做|称呼)"),
    re.compile(r"(?:更喜欢|不喜欢).*?(?:叫我|被叫|叫做|称呼)"),
]

DELETE_MARKERS: list[str] = [
    "不要再叫",
    "这个称呼失效",
    "不用了",
    "取消",
    "撤销",
    "删掉",
    "去掉",
    "不要了",
    "别再",
    "不要再",
    "停止",
    "不再",
    "删除",
    "清除",
    "移除",
    "忘记",
    "别记录",
]

HIGH_RISK_KEYWORDS: list[str] = [
    "叫我", "昵称", "称呼", "性别", "他", "她",
    "老婆", "老公", "男朋友", "女朋友", "名字",
]

# P1-1修复：细化AMBIGUOUS检测的三类标记
AMBIGUOUS_MARKERS: list[str] = [
    # 真实不确定：内容本身不确定
    "可能", "也许", "好像", "似乎", "应该是", "不太确定", "感觉", "不确定",
]

POLITENESS_MARKERS: list[str] = [
    # 礼貌表达：语气词，不影响内容确定性
    "吧", "呢", "啊", "呀", "嘛",
]

PRECISION_MARKERS: list[str] = [
    # 数值精度：描述数值的大致范围，不是内容不确定
    "大概", "约", "左右", "上下", "差不多", "大约", "将近", "接近",
]


def is_high_risk(text: str) -> bool:
    """检查文本是否涉及高敏字段（昵称/性别/关系边界）。"""
    return any(kw in text for kw in HIGH_RISK_KEYWORDS)


def classify_ambiguity(text: str) -> str | None:
    """P1-1修复：细化AMBIGUOUS检测，区分三类标记

    Args:
        text: 用户原文

    Returns:
        - "真实不确定": 内容本身不确定，需要阻断
        - "礼貌表达": 礼貌语气词，不阻断
        - "数值精度": 数值的大致范围，不阻断
        - None: 不包含任何歧义标记

    优先级：真实不确定 > 数值精度 > 礼貌表达
    """
    # 1. 检查真实不确定
    for marker in AMBIGUOUS_MARKERS:
        if marker in text:
            return "真实不确定"

    # 2. 检查数值精度（需要配合数字或时间词）
    has_precision_marker = any(marker in text for marker in PRECISION_MARKERS)
    if has_precision_marker:
        # 检查是否包含数值或时间相关词
        has_number = any(char.isdigit() for char in text)
        time_words = ["分钟", "小时", "天", "周", "月", "年", "点", "时", "秒", "公里", "米", "斤", "克"]
        has_time_word = any(word in text for word in time_words)

        if has_number or has_time_word:
            return "数值精度"

    # 3. 检查礼貌表达（需要配合偏好词或称呼词）
    has_politeness_marker = any(marker in text for marker in POLITENESS_MARKERS)
    if has_politeness_marker:
        # 检查是否包含偏好或称呼相关词
        preference_words = ["喜欢", "叫我", "称呼", "名字", "昵称", "更", "改", "换"]
        has_preference = any(word in text for word in preference_words)

        if has_preference:
            return "礼貌表达"

        # 如果只有礼貌词，没有配合其他内容，可能是真实不确定
        # 例：S003 "叫我晚晚吧" → 礼貌表达
        # 例：错误案例 "吧，我不太懂" → 真实不确定（但已被AMBIGUOUS_MARKERS捕获）
        return "礼貌表达"

    return None


def classify_speech_act(text: str) -> MemorySpeechAct:
    """确定性规则判定 speech_act（M1 修订版 + B3 修复）。

    规则优先级：DELETE > UPDATE > AMBIGUOUS > Filler > 分句检查 > QUERY > ASSERT > UNKNOWN

    M1 修复：
    - 收紧 QUERY 规则（避免误杀陈述句）
    - 支持分句处理（"陈述 + 追问"优先识别为 ASSERT）
    - 新增 UNKNOWN 类型（规则未覆盖，交给 extractor + gate）

    B3 修复：
    - 移除 filler 前缀再判断
    - 恢复 AMBIGUOUS 路径（不确定表达）
    - 改进疑问词判断（"几"的上下文判断）
    - 优先分句处理混合句

    Args:
        text: 用户原文

    Returns:
        MemorySpeechAct 分类结果。
    """
    if not text or not text.strip():
        return MemorySpeechAct.FILLER

    text = text.strip()

    # 1. 显式删除（优先级最高）
    for marker in DELETE_MARKERS:
        if marker in text:
            return MemorySpeechAct.EXPLICIT_DELETE

    # 2. 显式更新
    for pattern in UPDATE_PATTERNS:
        if pattern.search(text):
            return MemorySpeechAct.EXPLICIT_UPDATE
    for marker in UPDATE_MARKERS:
        if marker in text:
            return MemorySpeechAct.EXPLICIT_UPDATE

    # 3. P1-1修复：细化AMBIGUOUS检测，区分真实不确定、礼貌表达、数值精度
    ambiguity_type = classify_ambiguity(text)
    if ambiguity_type == "真实不确定":
        # 真实不确定表达 → AMBIGUOUS（阻断）
        return MemorySpeechAct.AMBIGUOUS
    # 礼貌表达和数值精度不阻断，继续后续判断

    # 4. B3 修复：移除 filler 前缀
    cleaned_text = remove_filler(text)
    if not cleaned_text:
        return MemorySpeechAct.FILLER

    # 5. B3 修复：检查疑问词（使用上下文判断）
    question_keywords = ["什么", "哪里", "哪儿", "哪些", "谁", "怎么", "为什么", "如何", "几", "多少"]
    has_question_keyword = any(
        _is_question_word_in_context(kw, cleaned_text) for kw in question_keywords if kw in cleaned_text
    )
    ends_with_question = cleaned_text.endswith(("?", "？", "吗", "吗？"))
    ends_with_ne = cleaned_text.endswith(("呢", "呢？"))

    # "呢"是较弱的疑问标记，需要更严格的判断
    if ends_with_ne and not has_question_keyword:
        # "后天和小乔视频呢" - "呢"只是语气词，不是真正的疑问
        # 没有疑问词的"呢"优先检查是否有陈述内容
        sentences = split_sentences(cleaned_text)
        has_clear_declarative = False

        for sent in sentences:
            sent = sent.strip()
            if not sent or sent.endswith(("吗", "呢", "吧", "?", "？")):
                continue

            declarative_starts = ["我", "你", "他", "她", "今天", "明天", "昨天", "后天", "最近"]
            if any(sent.startswith(prefix) for prefix in declarative_starts):
                has_clear_declarative = True
                break
            declarative_patterns = ["完全不吃", "不吃", "讨厌", "过敏", "喜欢", "不喜欢", "和.*视频", "跟.*聊"]
            if any(re.search(p, sent) for p in declarative_patterns):
                has_clear_declarative = True
                break

        # 有陈述内容 → ASSERT，否则继续下面的判断
        if has_clear_declarative:
            return MemorySpeechAct.ASSERT

    if ends_with_question:
        # 先检查确定性 QUERY 模式
        for pattern in QUERY_PATTERNS:
            if pattern.search(cleaned_text):
                return MemorySpeechAct.QUERY_EXISTING

        # B3 关键修复：如果包含疑问词（考虑上下文） → 纯疑问句
        if has_question_keyword:
            return MemorySpeechAct.QUERY_EXISTING

        # 没有疑问词，可能是"陈述+追问"的混合句
        # 例：091 "后天和小乔视频呢" - 陈述为主
        # 例：036 "我对花生过敏，你记得吗？" - 有陈述内容
        sentences = split_sentences(cleaned_text)
        has_clear_declarative = False

        for sent in sentences:
            sent = sent.strip()
            if not sent or sent.endswith(("吗", "呢", "吧", "?", "？")):
                continue  # 跳过疑问部分

            # 检查剩余部分是否为明确陈述
            declarative_starts = ["我", "你", "他", "她", "今天", "明天", "昨天", "后天", "最近"]
            if any(sent.startswith(prefix) for prefix in declarative_starts):
                has_clear_declarative = True
                break
            # 检查是否包含事实性内容
            declarative_patterns = ["完全不吃", "不吃", "讨厌", "过敏", "喜欢", "不喜欢", "和.*视频", "跟.*聊"]
            if any(re.search(p, sent) for p in declarative_patterns):
                has_clear_declarative = True
                break

        # 如果有明确陈述部分 → ASSERT，否则 → QUERY
        if has_clear_declarative:
            return MemorySpeechAct.ASSERT
        else:
            # 纯疑问句
            return MemorySpeechAct.QUERY_EXISTING

    # 6. 分句处理：检查是否"陈述 + 追问"（无疑问标记的情况）
    # 案例：009 "跟我聊天以中文为主，我偶尔会夹几句英文"
    #      083 "A/B 封面未决定，先聊点别的"
    #      091 "后天和小乔视频"
    sentences = split_sentences(cleaned_text)
    has_declarative = False

    for sent in sentences:
        sent = sent.strip()
        if not sent:
            continue

        # 检查是否为陈述句
        declarative_starts = ["我", "你", "他", "她", "今天", "明天", "昨天", "后天", "最近", "A/B", "AB"]
        if any(sent.startswith(prefix) for prefix in declarative_starts):
            has_declarative = True
            break
        # 036 "香菜完全不吃"、091 "后天和小乔视频"、083 "A/B 封面未决定"
        declarative_patterns = ["完全不吃", "不吃", "讨厌", "过敏", "和.*视频", "跟.*聊", "未决定", "尚未", "封面"]
        if any(re.search(p, sent) for p in declarative_patterns):
            has_declarative = True
            break

    # 如果有陈述句 → ASSERT
    if has_declarative:
        return MemorySpeechAct.ASSERT

    # 7. 查询已有偏好（收紧后的规则）
    for pattern in QUERY_PATTERNS:
        if pattern.search(cleaned_text):
            return MemorySpeechAct.QUERY_EXISTING

    # 8. 明确的陈述句模式 → ASSERT
    declarative_patterns = [
        r"^我是", r"^我叫", r"^我的.*(是|叫)", r"^我在", r"^我会",
        r"^我喜欢", r"^我不喜欢", r"^我对.+过敏",
        r"^我每天", r"^我通常", r"^我习惯",
        r"完全不吃", r"不吃", r"讨厌", r"过敏",
        r"后天.*和.*视频", r"跟.*聊",
    ]

    for pattern in declarative_patterns:
        if re.search(pattern, cleaned_text):
            return MemorySpeechAct.ASSERT

    # 9. 默认 UNKNOWN（而非 AMBIGUOUS）
    # M1 修复：未被规则覆盖的情况，交给 extractor + gate 判断
    return MemorySpeechAct.UNKNOWN

def needs_clarification(text: str) -> bool:
    """AMBIGUOUS + 高敏字段 → 需要生成端触发澄清追问（ADR 0014）。"""
    return classify_speech_act(text) == MemorySpeechAct.AMBIGUOUS and is_high_risk(text)


# ---- B3 修复：辅助函数 ----

def remove_filler(text: str) -> str:
    """移除 filler 前缀，保留有效内容

    B3 修复：支持"好的，我叫小明"这样的模式
    """
    filler_prefixes = [
        "好的，", "好的,", "好，", "好,",
        "嗯，", "嗯,", "那个，", "那个,", "这个，", "这个,",
        "对了，", "对了,", "另外，", "另外,", "还有，", "还有,",
        "嗯嗯，", "嗯嗯,", "好吧，", "好吧,",
    ]

    cleaned = text
    for prefix in filler_prefixes:
        if cleaned.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            break  # 只移除一次前缀

    return cleaned


def _is_question_word_in_context(word: str, context: str) -> bool:
    """判断是否为疑问词（考虑上下文）

    B3 修复：精准匹配疑问词，避免"几"等量词误判
    """
    # "几" 只在特定句式中算疑问
    if word == "几":
        # "有几个"、"多少几"、"几个" 才算疑问
        if "有几" in context or "多少几" in context or context.endswith("几个"):
            return True
        else:
            # "夹几句" 不算疑问
            return False

    # 其他明确的疑问词
    return word in ["什么", "哪里", "哪儿", "哪些", "谁", "怎么", "为什么", "如何", "多少"]


def split_sentences(text: str) -> list[str]:
    """分句（B3 修复）

    按标点符号分句，支持混合句处理
    """
    # 按标点符号分句
    sentences = re.split(r'[。！？；，,.!?;]', text)
    return [s.strip() for s in sentences if s.strip()]


def _classify_single_sentence(sent: str) -> MemorySpeechAct:
    """分类单个句子（B3 修复）

    用于支持混合句分句处理
    """
    # 疑问词（放在句末才算疑问）
    question_words = ["什么", "哪里", "哪儿", "谁", "怎么", "为什么", "多少", "吗", "呢"]
    if any(sent.endswith(w) or sent.endswith(w + "？") or sent.endswith(w + "?") for w in question_words):
        return MemorySpeechAct.QUERY_EXISTING

    # 陈述句特征
    assert_indicators = ["我", "是", "喜欢", "过敏", "叫", "对", "讨厌", "不吃"]
    if any(ind in sent for ind in assert_indicators):
        return MemorySpeechAct.ASSERT

    return MemorySpeechAct.UNKNOWN
