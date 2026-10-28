#!/usr/bin/env python3
"""
UserPromptSubmit hook: Engineering Agent 复杂度预分类。

快速分析用户输入的复杂度，判定为复杂任务时注入 engineering-agent 工作流提示，
让 Claude 自动进入编排模式，不需要用户手动调用 /engineering-agent。

启发式规则（命中 2+ 个信号判定为复杂）：
  1. 输入长度 > 300 字符
  2. 包含多步骤/项目/规划类关键词
  3. 超过 3 行（结构化输入）
  4. "帮我做一个" 类请求且不含 "简单"

设计原则：任何异常都静默退出（exit 0、无输出），绝不阻断用户 prompt。
"""

import json
import re
import sys


# 复杂任务关键词
COMPLEX_KEYWORDS = [
    # 规划/分解类
    '计划', '规划', '分解', '分步骤', '分阶段', '分步',
    '项目', '系统', '架构', '设计', '调研', '研究',
    'workflow', 'pipeline', 'engineering-agent', '编排',
    # 多交付物类
    '完整的', '一套', '整个', '全面',
    # 工程类
    '工程', '实现', '开发', '搭建', '部署',
    # 文档类
    '方案', '报告', '白皮书', 'spec', '设计文档',
]

# 简单任务关键词（降低复杂度评分）
SIMPLE_KEYWORDS = [
    '简单', '快速', '一句话', '帮我看一下', '看看',
    '查一下', '翻译', '解释一下', '什么是',
]


def classify_complexity(prompt: str) -> tuple[bool, list[str]]:
    """判定 prompt 是否为复杂任务，返回 (is_complex, triggered_signals)"""
    signals = []
    low = prompt.lower()

    # 信号 1：长度
    if len(prompt) > 300:
        signals.append(f'长输入 ({len(prompt)} 字符)')

    # 信号 2：复杂关键词
    complex_hits = [kw for kw in COMPLEX_KEYWORDS if kw in low]
    if len(complex_hits) >= 2:
        signals.append(f'复杂关键词 ({", ".join(complex_hits[:3])})')
    elif len(complex_hits) == 1 and len(prompt) > 150:
        signals.append(f'关键词+中等长度 ({complex_hits[0]})')

    # 信号 3：多行结构化输入
    line_count = prompt.count('\n') + 1
    if line_count > 3:
        signals.append(f'多行输入 ({line_count} 行)')

    # 信号 4："帮我做一个 X" 模式
    if re.search(r'帮我(做|写|搞|弄|搭)一个', prompt) and '简单' not in low:
        signals.append('请求构建类任务')

    # 信号 5：明确的多步骤标志
    step_patterns = ['第一步', '第二步', '首先', '其次', '然后', '最后']
    step_hits = sum(1 for p in step_patterns if p in prompt)
    if step_hits >= 2:
        signals.append(f'多步骤描述 ({step_hits} 个步骤词)')

    # 简单关键词抵消
    simple_hits = sum(1 for kw in SIMPLE_KEYWORDS if kw in low)
    if simple_hits >= 2 and len(signals) <= 2:
        # 多个简单关键词明确表示要简单做，降低一个信号等级
        signals = signals[:-1] if signals else []

    is_complex = len(signals) >= 2
    return is_complex, signals


def main() -> None:
    try:
        sys.stdin.reconfigure(encoding="utf-8")
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    try:
        raw = sys.stdin.read()
    except Exception:
        return

    if not raw.strip():
        return

    try:
        data = json.loads(raw)
        prompt = data.get("prompt") or ""
    except Exception:
        return

    if not prompt:
        return

    is_complex, signals = classify_complexity(prompt)

    if not is_complex:
        # 简单任务，不注入，静默返回
        return

    # 复杂任务，注入 engineering-agent 模式提示
    signal_desc = "、".join(signals)
    ctx = (
        f"[Engineering Agent 自动激活] 检测到当前任务可能较为复杂 "
        f"（触发信号：{signal_desc}）。"
        "请考虑委派给 Engineering Agent 处理，工作流如下：\n"
        "1. 先做复杂度判断（确认是否真的需要工程化流程）\n"
        "2. 复杂任务则按 澄清→规划→分解→验收→写回 五步执行\n"
        "3. 如判断为简单任务可直接执行，不必强行套流程\n"
        "详细流程见 Engineering Agent 定义。"
    )

    try:
        sys.stdout.write(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": ctx,
                    }
                },
                ensure_ascii=False,
            )
        )
    except Exception:
        pass


if __name__ == "__main__":
    main()
