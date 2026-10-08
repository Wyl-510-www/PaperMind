"""Phase 5C: 6 lane 专属 Prompt + JSON Schema。

每个 lane 有独立的 system prompt（含正向/负向示例）和 JSON schema 定义。
"""

# ═══════════════════════════════════════════════════════════════════════════════
# SEMANTIC — 稳定偏好/长期事实
# ═══════════════════════════════════════════════════════════════════════════════

SEMANTIC_PROMPT = """你负责从用户消息中抽取稳定的长期偏好和持久事实。

只允许抽取：
- 长期身份、稳定偏好（"我不吃香菜"、"我怕高"）
- 明确的长期禁忌和互动边界
- 持久事实描述（语言能力、知识领域、习惯等）
- 用户自身的身份信息：性别、生日、年龄、姓名、代词偏好（如"我是女生，第三人称用她"、"我的生日是11月8日"）
- 学习笔记、论文阅读结论、研究背景（"我读了《XXX论文》，结论是YYY"、"我学到了ZZZ知识"）

禁止抽取：
- 事件和任务（"周六聚会" → EVENT_TASK 负责）
- 第三方实体关系（"妈妈喜欢种花"、"我的室友叫安安" → ENTITY_RELATION 负责；注意：用户自身的性别、代词、生日等身份信息不是第三方关系，仍由本 lane 负责）
- 行为约束/称呼偏好（"不要叫小公主" → BEHAVIOR_POLICY 负责）
- 更新/删除指令（"改成"、"不是" → UPDATE_DELETE 负责）
- 寒暄、假设、玩笑、一次性临时需求

【P1-3修复：条件与例外处理原则】
对于包含条件、限制和例外的偏好表达，必须拆分为多条独立claim：

1. **条件偏好**：保留完整条件，不泛化
   - 例："熬夜改论文时不想吃重口夜宵" → 生成一条claim，保留condition="熬夜改论文时"
   - 不要泛化为"用户不喜欢重口味夜宵"（丢失条件）

2. **限制+例外**：各成独立claim，保留关系
   - 例："不喜欢蒜味特别重，少量蒜可以" → 生成两条claim：
     - claim1: "用户不喜欢蒜味特别重"（negative偏好）
     - claim2: "用户可以接受少量蒜"（positive偏好，标记为claim1的例外）
   - 不要简化为单一claim"禁止蒜味特别重"（丢失例外）

3. **程度区分**：保留完整的程度信息
   - 例："偶尔吃辣可以，但不要特辣" → 生成两条claim：
     - claim1: "用户偶尔吃辣可以接受"（带频率限定）
     - claim2: "用户不要特辣"（强度限制）

每条事实必须包含原文片段用于交叉校验。

输出严格 JSON（不要输出其他内容）：
{"facts": [
  {
    "text": "用户不喜欢蒜味特别重",
    "predicate": "diet.dislike",
    "modality": "fact",
    "confidence": 0.9,
    "source_span": "不喜欢蒜味特别重",
    "condition": null,
    "exception_of": null
  },
  {
    "text": "用户可以接受少量蒜",
    "predicate": "diet.allows",
    "modality": "fact",
    "confidence": 0.9,
    "source_span": "少量蒜可以",
    "condition": null,
    "exception_of": "claim_0"
  }
]}

predicate 示例：diet.dislike, diet.like, diet.allows, hobby.like, fear.of, skill.has, behavior.tendency, health.condition, identity.birthday, identity.name, identity.age, gender.self_reported, pronoun.preferred
modality 枚举：fact, wish, plan, hypothesis, joke, quote, question, uncertain
condition: 条件描述（如"熬夜改论文时"），无条件时为null
exception_of: 如果是某条claim的例外，填写该claim的索引（如"claim_0"），否则为null

没有可抽取内容时返回 {"facts": []}"""

SEMANTIC_SCHEMA = {
    "type": "object",
    "properties": {
        "facts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "规范化中文描述，'用户'+事实"},
                    "predicate": {"type": "string", "description": "谓词，如 diet.dislike"},
                    "modality": {"type": "string", "enum": ["fact", "wish", "plan", "hypothesis", "joke", "quote", "question", "uncertain"]},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "source_span": {"type": "string", "description": "用户原文片段"},
                    "condition": {"type": ["string", "null"], "description": "P1-3: 条件描述，无条件时为null"},
                    "exception_of": {"type": ["string", "null"], "description": "P1-3: 例外关系，指向另一条claim的索引"},
                },
                "required": ["text", "predicate", "source_span"],
            },
        },
    },
    "required": ["facts"],
}

# ═══════════════════════════════════════════════════════════════════════════════
# EVENT_TASK — 事件/任务
# ═══════════════════════════════════════════════════════════════════════════════

EVENT_TASK_PROMPT = """你负责从用户消息中抽取事件、任务和日程。

只允许抽取：
- 带时间的事件（"周六聚会"、"明天下午面试"）
- 任务和待办（"记得买牛奶"、"要交报告"）
- 事件状态变化（"聚会改期到周日"、"面试取消了"）

禁止抽取：长期偏好、临时状态、第三方关系、行为约束。

【P2-1修复：时间表达规范化】
对于时间表达，必须保留原始表达和时区信息：
- original_time_expression: 用户的原始时间表达（"明天"、"周六下午"、"纽约时间下午3点"）
- timezone_mentioned: 用户提到的时区（"纽约时间"、"EST"、"北京时间"），无明确提及时为null
- recurrence: 周期性表达（"每周三"、"每天"），非周期性时为null

时间表达类型示例：
- 相对时间："明天"、"这周"、"十天后" → 保留原始表达，由系统锚定到message_time
- 绝对时间："2024年9月21日"、"周六" → 保留原始表达
- 时区相关："纽约时间周三下午"、"EST下午3点" → 保留时区信息
- 周期性："每周三"、"通常下午" → 标记recurrence

【P2-2修复：事件生命周期管理】
准确识别事件和任务的状态：
- status字段必须准确反映当前状态：
  * scheduled: 计划中的事件/任务（"周六聚会"、"要交报告"）
  * in_progress: 正在进行（"这周在改论文"、"正在写代码"）
  * completed: 已完成（"论文交了"、"面试结束了"）
  * cancelled: 已取消（"聚会取消了"、"不去了"）

- 有效期约束（valid_from/valid_to）：
  * "这两个月不回国" → valid_from=今天, valid_to=两个月后
  * "下周出差" → valid_from/to根据"下周"计算

- 截止时间（due_time_expr）：
  * "十天后交初稿" → due_time_expr="十天后"
  * "周五前完成" → due_time_expr="周五"

输出严格 JSON：
{"events": [{"text": "这周在改论文方法章节", "event_type": "task", "start_expr": "这周", "end_expr": null, "status": "in_progress", "original_time_expression": "这周", "timezone_mentioned": null, "recurrence": null, "valid_from_expr": null, "valid_to_expr": null, "due_time_expr": null, "source_span": "这周在改论文方法章节"}]}

event_type 枚举：event, task
status 枚举：scheduled, in_progress, completed, cancelled
recurrence 枚举：daily, weekly, monthly, null（非周期性）
没有可抽取内容时返回 {"events": []}"""

EVENT_TASK_SCHEMA = {
    "type": "object",
    "properties": {
        "events": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "event_type": {"type": "string", "enum": ["event", "task"]},
                    "start_expr": {"type": ["string", "null"], "description": "原始时间表达，如'周六''明天下午'"},
                    "end_expr": {"type": ["string", "null"]},
                    "status": {"type": "string", "enum": ["scheduled", "in_progress", "completed", "cancelled"]},
                    "original_time_expression": {"type": ["string", "null"], "description": "P2-1: 用户原始时间表达"},
                    "timezone_mentioned": {"type": ["string", "null"], "description": "P2-1: 用户提到的时区"},
                    "recurrence": {"type": ["string", "null"], "enum": ["daily", "weekly", "monthly", None], "description": "P2-1: 周期性"},
                    "valid_from_expr": {"type": ["string", "null"], "description": "P2-2: 有效期开始时间表达"},
                    "valid_to_expr": {"type": ["string", "null"], "description": "P2-2: 有效期结束时间表达"},
                    "due_time_expr": {"type": ["string", "null"], "description": "P2-2: 截止时间表达"},
                    "source_span": {"type": "string"},
                },
                "required": ["text", "event_type", "source_span"],
            },
        },
    },
    "required": ["events"],
}

# ═══════════════════════════════════════════════════════════════════════════════
# ENTITY_RELATION — 第三方实体关系
# ═══════════════════════════════════════════════════════════════════════════════

ENTITY_RELATION_PROMPT = """你负责从用户消息中抽取关于第三方的属性和关系。

只允许抽取：
- 第三方实体（妈妈、朋友、宠物、同事、老师等）的属性
- 第三方实体的偏好和状态
- 第三方实体之间的关系

禁止抽取：
- 用户自己的属性（自己不吃香菜 → SEMANTIC 负责）
- 用户自己的短暂状态（由 DSM 独立处理，不在此抽取）

输出严格 JSON：
{"relations": [{"text": "妈妈喜欢种花", "entity_name": "妈妈", "relation_type": "preference", "source_span": "我妈妈喜欢种花"}]}

relation_type 枚举：preference, habit, status, relationship, health
没有可抽取内容时返回 {"relations": []}"""

ENTITY_RELATION_SCHEMA = {
    "type": "object",
    "properties": {
        "relations": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "entity_name": {"type": "string", "description": "第三方实体的规范化名称"},
                    "relation_type": {"type": "string", "enum": ["preference", "habit", "status", "relationship", "health"]},
                    "source_span": {"type": "string"},
                },
                "required": ["text", "entity_name", "source_span"],
            },
        },
    },
    "required": ["relations"],
}

# ═══════════════════════════════════════════════════════════════════════════════
# BEHAVIOR_POLICY — 行为约束
# ═══════════════════════════════════════════════════════════════════════════════

BEHAVIOR_POLICY_PROMPT = """你负责从用户消息中抽取行为约束、边界和风格偏好。

只允许抽取：
- 称呼约束（"不要叫我小公主"、"叫我阿宁就好"、"我喜欢叫你晚晚"）
- 隐私边界（"少问我隐私问题"、"别问我家里的事"）
- 回复风格（"说话温柔一点"、"别每句话都问我问题"、"回复短一点"）
- 内容排除（"不用问我吃了没"、"不要推荐辣的"）
- 纠错方式偏好（"如果我说错了直接提醒我"）
- 信息不足时的处理偏好（"不确定就别编"）

禁止抽取：事实、状态、事件、第三方关系。

策略分类（kind）：
- safety：健康/过敏安全底线
- privacy：隐私边界
- content_exclusion：内容排除
- relationship_boundary：不允许的称呼/关系边界
- style：回复风格/长度/语气
- repair：纠错方式
- uncertainty：信息不足时处理

策略强度（strength）：
- hard：严禁违反，违反必须重生成
- soft：尽量遵守，违反可改写

【P1-2修复：称呼方向识别】
对于称呼类策略，必须识别主体和方向：
- "我喜欢叫你X" / "我叫你X" → subject="current_user", target="assistant", direction="user_to_assistant"
- "你可以叫我X" / "叫我X" → subject="assistant", target="current_user", direction="assistant_to_user"
- "不要叫我X" → subject="assistant", target="current_user", direction="assistant_to_user"

输出严格 JSON：
{"policies": [{
    "text": "用户喜欢叫助手晚晚宝宝",
    "kind": "relationship_boundary",
    "strength": "soft",
    "subject": "current_user",
    "target": "assistant",
    "direction": "user_to_assistant",
    "forbidden_terms": [],
    "allowed_terms": ["晚晚宝宝"],
    "source_span": "我喜欢叫你晚晚宝宝"
}]}

没有可抽取内容时返回 {"policies": []}"""""

BEHAVIOR_POLICY_SCHEMA = {
    "type": "object",
    "properties": {
        "policies": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "kind": {"type": "string", "enum": ["safety", "privacy", "content_exclusion", "relationship_boundary", "style", "repair", "uncertainty"]},
                    "strength": {"type": "string", "enum": ["hard", "soft"]},
                    "subject": {"type": "string", "enum": ["current_user", "assistant"], "description": "P1-2: 动作主体"},
                    "target": {"type": "string", "enum": ["current_user", "assistant"], "description": "P1-2: 动作目标"},
                    "direction": {"type": "string", "enum": ["user_to_assistant", "assistant_to_user"], "description": "P1-2: 称呼方向"},
                    "forbidden_terms": {"type": "array", "items": {"type": "string"}},
                    "allowed_terms": {"type": "array", "items": {"type": "string"}, "description": "P1-2: 允许的称呼列表"},
                    "source_span": {"type": "string"},
                },
                "required": ["text", "kind", "strength", "source_span"],
            },
        },
    },
    "required": ["policies"],
}

# ═══════════════════════════════════════════════════════════════════════════════
# UPDATE_DELETE — 更新/删除
# ═══════════════════════════════════════════════════════════════════════════════

UPDATE_DELETE_PROMPT = """你负责从用户消息中识别显式的更新、删除和纠正指令。

【核心约束】
1. 只抽取当前消息明确表达、或由输入的已存在真值直接支持的claim。
2. "A，不是B"表示当前A成立、B被否定；不推出过去曾B、曾说B或最近从B变A。
3. 历史claim必须由当前消息明确的历史陈述或可核对的旧证据支持。
4. 形成supersede关系须引用真实旧目标；"A，不是B"本身不能推出曾B或曾说B。
5. 保留谓词、主体、极性、时态、条件和例外；作品名中的否定词属于实体名称。
6. 不能支持的字段保持unknown，不补用户过去经历。

【P2-2修复：事件取消操作】
cancel操作需要明确标记event_id_hint，以便后续更新对应事件的status为cancelled：
- "面试取消了" → action=cancel, event_id_hint="面试"
- "不去聚会了" → action=cancel, event_id_hint="聚会"
- "算了不做了" → action=cancel, event_id_hint="最近提到的任务"

【正确示例】
输入: "我住皇后区，不是曼哈顿"
输出: {"updates": [
  {"text": "用户住皇后区", "action": "assert", "polarity": "positive", "source_span": "我住皇后区"},
  {"text": "用户不住曼哈顿", "action": "assert", "polarity": "negative", "source_span": "不是曼哈顿"}
]}
注意：不输出"之前说住曼哈顿"，因为这是无依据的历史。

输入: "我现在住皇后区了，之前住曼哈顿"（且已有旧truth: lives_in=曼哈顿）
输出: {"updates": [
  {"text": "用户现在住皇后区", "action": "correct", "polarity": "positive", "supersedes_hint": "曼哈顿住址", "source_span": "我现在住皇后区了"},
  {"text": "用户之前住曼哈顿", "action": "assert", "polarity": "positive", "temporal": "past", "source_span": "之前住曼哈顿"}
]}
注意：只有当用户明确说"之前"且有旧truth时才记录历史。

输入: "周六聚会改成周日"
输出: {"updates": [{"text": "聚会改期到周日", "action": "reschedule", "target_hint": "周六聚会", "source_span": "周六聚会改成周日"}]}

输入: "算了不去了"
输出: {"updates": [{"text": "取消活动", "action": "cancel", "event_id_hint": "最近提到的活动", "source_span": "算了不去了"}]}

输入: "面试取消了"（P2-2示例）
输出: {"updates": [{"text": "面试已取消", "action": "cancel", "event_id_hint": "面试", "source_span": "面试取消了"}]}

【错误示例 - 禁止】
输入: "我喜欢甜的，不是辣的"
❌ 错误输出: {"updates": [{"text": "用户喜欢甜的，之前说不喜欢甜的", ...}]}
✓ 正确输出: {"updates": [
  {"text": "用户喜欢甜的", "action": "assert", "polarity": "positive", "source_span": "我喜欢甜的"},
  {"text": "用户不喜欢辣的", "action": "assert", "polarity": "negative", "source_span": "不是辣的"}
]}

只允许抽取：
- 显式更新/纠正指令（需要明确说"之前"或"现在改成"）
- 事件改期（需要明确的时间变更）
- 事件取消（需要取消标记）
- 删除指令（"当我没说"、"撤回刚才的"）
- 否定陈述（"不是B"记录为negative，不创造历史）

禁止抽取：新建事实（由其他lane负责）、无依据的历史声称。

输出严格 JSON：
{"updates": [{"text": "规范化描述", "action": "correct|reschedule|cancel|delete|assert", "polarity": "positive|negative", "temporal": "current|past|future", "supersedes_hint": "旧值描述", "target_hint": "目标提示", "event_id_hint": "事件标识", "source_span": "原文片段"}]}

action 枚举：
- assert: 陈述新事实（包括否定）
- correct: 纠正已存在的事实（需要supersedes_hint）
- reschedule: 事件改期
- cancel: 取消事件/任务（P2-2：需要event_id_hint）
- delete: 删除信息

没有可抽取内容时返回 {"updates": []}"""

UPDATE_DELETE_SCHEMA = {
    "type": "object",
    "properties": {
        "updates": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string", "description": "规范化中文描述"},
                    "action": {"type": "string", "enum": ["assert", "correct", "reschedule", "cancel", "delete"], "description": "动作类型"},
                    "polarity": {"type": "string", "enum": ["positive", "negative"], "description": "极性，positive或negative"},
                    "temporal": {"type": "string", "enum": ["current", "past", "future"], "description": "时态"},
                    "supersedes_hint": {"type": "string", "description": "被替代的旧值描述（仅correct时需要）"},
                    "target_hint": {"type": "string", "description": "目标提示"},
                    "event_id_hint": {"type": "string", "description": "P2-2: 事件标识提示（cancel操作时使用）"},
                    "source_span": {"type": "string", "description": "原文片段"},
                },
                "required": ["text", "action", "source_span"],
            },
        },
    },
    "required": ["updates"],
}

# ═══════════════════════════════════════════════════════════════════════════════
# Lane → (Prompt, Schema) 映射表
# ═══════════════════════════════════════════════════════════════════════════════

LANE_CONFIG = {
    "semantic": (SEMANTIC_PROMPT, SEMANTIC_SCHEMA),
    "event_task": (EVENT_TASK_PROMPT, EVENT_TASK_SCHEMA),
    "entity_relation": (ENTITY_RELATION_PROMPT, ENTITY_RELATION_SCHEMA),
    "behavior_policy": (BEHAVIOR_POLICY_PROMPT, BEHAVIOR_POLICY_SCHEMA),
    "update_delete": (UPDATE_DELETE_PROMPT, UPDATE_DELETE_SCHEMA),
}
