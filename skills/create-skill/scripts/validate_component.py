#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""组件静态校验器（skill / hook / agent）。

用法:
    python validate_component.py --type skill <skill-dir>
    python validate_component.py --type hook  <hook-dir>
    python validate_component.py --type agent <agent-file.md>
    python validate_component.py --self-test

退出码即结论：0 = 通过（可带 WARN），1 = 有 FAIL。
只读校验，不修改被校验目录；py_compile 产物写临时目录，不在组件内留 __pycache__。
"""

from __future__ import annotations

import argparse
import json
import py_compile
import re
import sys
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:  # 允许降级：仅支持 "key: value" 形式
    yaml = None

FAIL, WARN, OK = "FAIL", "WARN", "OK"

# 敏感串由片段拼装，避免本文件自身被扫描命中。
_SECRET_PATTERNS = [
    ("github_pat", re.compile(r"\bgh" + r"p_[A-Za-z0-9]{20,}")),
    ("github_pat_fine", re.compile(r"github_" + r"pat_[A-Za-z0-9_]{20,}")),
    ("openai_key", re.compile(r"\bsk" + r"-[A-Za-z0-9]{20,}")),
    ("aws_key", re.compile(r"\bAK" + r"IA[0-9A-Z]{16}\b")),
    ("private_key", re.compile(r"BEGIN [A-Z ]*PRIV" + r"ATE KEY")),
    ("bearer", re.compile(r"Authori" + r"zation:\s*Bearer\s+\S+")),
]
_PERSONAL_PATH_PATTERNS = [
    ("win_home", re.compile(r"[A-Za-z]:" + r"\\Users\\[^\\\s]+")),
    ("posix_home", re.compile(r"/Us" + r"ers/[^/\s]+|/ho" + r"me/[^/\s]+")),
    ("drive_path", re.compile(r"(?<![\w~])[A-Za-z]:" + r"[\\/](?![\\/])")),
    ("unc_path", re.compile(r"\\{2}[A-Za-z0-9_.-]+\\" + r"(?![\\\[])")),
    ("profile_var", re.compile("%USER" + "PROFILE%")),
]

_FRONTMATTER_ALLOWED_SKILL = {"name", "description", "license", "metadata",
                              "compatibility", "allowed-tools"}
_FRONTMATTER_ALLOWED_AGENT = {"name", "description", "tools"}
_KEBAB = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

_SKILL_SECTIONS = [
    ("何时使用", r"何时使用|何时不用|when to use|when not to use"),
    ("输入", r"输入|input"),
    ("流程", r"流程|步骤|workflow|process"),
    ("输出", r"输出|output"),
    ("边界", r"边界|不做什么|boundary|out of scope"),
    ("验收", r"验收|校验|acceptance|validation"),
    ("示例", r"示例|example"),
]
_HOOK_README_KEYWORDS = [
    ("触发事件", r"触发事件|event"),
    ("matcher", r"matcher|匹配"),
    ("失败策略", r"失败策略|fail-open|fail-closed|失败时"),
    ("回滚", r"回滚|rollback"),
    ("安装", r"安装|install"),
]
_AGENT_SECTIONS = [
    ("职责", r"职责|定位|role"),
    ("边界", r"边界|何时不用|不做什么|boundary"),
    ("输出", r"输出|报告格式|output"),
]

# 占位符与未完成标记也由片段拼装，避免校验器扫描自己时误命中。
_PLACEHOLDER_HARD = re.compile(r"\bTO" + r"DO\b|\bFIX" + r"ME\b|<place" + r"holder>")
_PLACEHOLDER_SOFT = re.compile("待补" + "充|待" + "定|T" + "BD")

_TEXT_SUFFIXES = {".md", ".py", ".json", ".txt", ".yaml", ".yml", ".cmd", ".sh",
                   ".ps1", ".html", ".htm", ".js", ".ts", ".tsx", ".css", ".toml",
                   ".ini", ".cfg", ".bat"}


class Report:
    def __init__(self, target: str):
        self.target = target
        self.items: list[tuple[str, str, str]] = []

    def fail(self, code: str, msg: str) -> None:
        self.items.append((FAIL, code, msg))

    def warn(self, code: str, msg: str) -> None:
        self.items.append((WARN, code, msg))

    @property
    def failed(self) -> bool:
        return any(level == FAIL for level, _, _ in self.items)

    def render(self) -> str:
        lines = [f"组件: {self.target}"]
        for level, code, msg in self.items:
            lines.append(f"  {level} [{code}] {msg}")
        fails = sum(1 for i in self.items if i[0] == FAIL)
        warns = sum(1 for i in self.items if i[0] == WARN)
        lines.append(f"结果: {'FAIL' if fails else 'PASS'}  ({fails} 失败, {warns} 警告)")
        return "\n".join(lines)


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _parse_frontmatter(text: str):
    """返回 (dict | None, error)。缺失 frontmatter 也视为错误。"""
    m = re.match(r"^---\r?\n(.*?)\r?\n---\s*(?:\r?\n|$)", text, re.DOTALL)
    if not m:
        return None, "缺少 YAML frontmatter（文件必须以 --- 开头并有成对分隔）"
    raw = m.group(1)
    if yaml is None:
        data = {}
        for line in raw.splitlines():
            if ":" in line and not line.startswith((" ", "\t")):
                k, v = line.split(":", 1)
                data[k.strip()] = v.strip().strip('"').strip("'")
        return data, None
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        return None, f"frontmatter YAML 解析失败: {exc}"
    if not isinstance(data, dict):
        return None, "frontmatter 不是映射"
    return data, None


def _check_frontmatter(rep: Report, fm: dict, allowed: set[str], expect_name: str,
                       forbid_model: bool = False) -> None:
    for key in fm:
        if key not in allowed:
            rep.fail("fm-unknown-field", f"非官方 frontmatter 字段 '{key}'，允许: {sorted(allowed)}")
    if forbid_model and "model" in fm:
        rep.fail("fm-model", "禁止写 model 字段（本环境不可解析，工程内已有 2.1.2 教训）")

    name = fm.get("name")
    if not isinstance(name, str) or not name.strip():
        rep.fail("fm-name", "frontmatter 缺 name 或为空")
    else:
        name = name.strip()
        if not _KEBAB.match(name):
            rep.fail("fm-name-kebab", f"name '{name}' 不是 kebab-case")
        if len(name) > 64:
            rep.fail("fm-name-len", f"name 超长（{len(name)} > 64）")
        if name != expect_name:
            rep.fail("fm-name-match", f"name '{name}' 与目录/文件名 '{expect_name}' 不一致")

    desc = fm.get("description")
    if not isinstance(desc, str) or not desc.strip():
        rep.fail("fm-desc", "frontmatter 缺 description 或为空")
    else:
        desc = desc.strip()
        if len(desc) > 1024:
            rep.fail("fm-desc-len", f"description 超长（{len(desc)} > 1024）")
        if "<" in desc or ">" in desc:
            rep.fail("fm-desc-angle", "description 含尖括号（部分 IDE 拒绝）")
        if len(desc) < 60:
            rep.warn("fm-desc-short", "description 偏短，容易不触发")
        if not re.search(r"当|使用|创建|use when|when the user", desc):
            rep.warn("fm-desc-trigger", "description 未见触发语（如“当用户…”）")


def _check_text_hygiene(rep: Report, root: Path, files: list[Path]) -> None:
    for path in files:
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        text = _read_text(path)
        rel = path.relative_to(root) if root.is_dir() else path.name
        for label, pat in _SECRET_PATTERNS:
            if pat.search(text):
                rep.fail("secret", f"{rel}: 命中敏感模式 {label}")
        for label, pat in _PERSONAL_PATH_PATTERNS:
            if pat.search(text):
                rep.fail("personal-path", f"{rel}: 命中个人路径 {label}")
        if _PLACEHOLDER_HARD.search(text):
            rep.fail("placeholder", f"{rel}: 残留未完成占位（待写代码或未填内容）")
        if _PLACEHOLDER_SOFT.search(text):
            rep.warn("placeholder-soft", f"{rel}: 含未完成标记（未写完的内容）")


def _check_scale(rep: Report, files: list[Path]) -> None:
    if len(files) > 50:
        rep.warn("scale-count", f"文件数 {len(files)} > 50，考虑拆分或外置")
    for path in files:
        if path.stat().st_size > 200 * 1024:
            rep.warn("scale-size", f"{path.name} > 200 KB，建议移到 references/ 或 assets/")


def _check_py(rep: Report, root: Path, files: list[Path]) -> None:
    pys = [p for p in files if p.suffix == ".py"]
    if not pys:
        return
    with tempfile.TemporaryDirectory() as tmp:
        for path in pys:
            cfile = Path(tmp) / (path.stem + ".pyc")
            try:
                py_compile.compile(str(path), cfile=str(cfile), doraise=True)
            except py_compile.PyCompileError as exc:
                rep.fail("py-compile", f"{path.name}: {exc.msg.strip()}")


def _component_files(root: Path) -> list[Path]:
    return [p for p in root.rglob("*")
            if p.is_file() and "__pycache__" not in p.parts and p.suffix != ".pyc"]


def _split_sections(body: str) -> list[tuple[str, str]]:
    """按 markdown 标题切段，返回 [(标题, 正文)]。"""
    sections: list[tuple[str, str]] = []
    title: str | None = None
    buffer: list[str] = []
    in_fence = False
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            in_fence = not in_fence
            buffer.append(line)
            continue
        match = None if in_fence else re.match(r"^(#{1,4})\s+(.*)$", line)
        if match:
            if title is not None:
                sections.append((title, "\n".join(buffer)))
            title, buffer = match.group(2).strip(), []
        else:
            buffer.append(line)
    if title is not None:
        sections.append((title, "\n".join(buffer)))
    return sections


def _section_issues(body: str, patterns: list[tuple[str, str]]) -> tuple[list[str], list[str]]:
    """返回 (缺失的节, 只有标题没内容的节)。内容阈值：去空白后 < 20 字符。"""
    sections = _split_sections(body)
    missing, empty = [], []
    for label, pattern in patterns:
        matched = [(t, c) for t, c in sections if re.search(pattern, t, re.IGNORECASE)]
        if not matched:
            missing.append(label)
        elif all(len(re.sub(r"\s+", "", content)) < 20 for _, content in matched):
            empty.append(label)
    return missing, empty


def validate_skill(path: Path) -> Report:
    rep = Report(str(path))
    if not path.is_dir():
        rep.fail("path", "skill 必须是目录")
        return rep
    if path.parent.name != "skills":
        rep.fail("prefix", f"skill 必须位于 skills/ 下，实际父目录 '{path.parent.name}'")
    skill_md = path / "SKILL.md"
    if not skill_md.is_file():
        rep.fail("entry", "缺 SKILL.md")
        return rep

    text = _read_text(skill_md)
    fm, err = _parse_frontmatter(text)
    if err:
        rep.fail("fm", err)
    else:
        _check_frontmatter(rep, fm, _FRONTMATTER_ALLOWED_SKILL, path.name, forbid_model=True)

    body = re.sub(r"^---\r?\n.*?\r?\n---\s*", "", text, count=1, flags=re.DOTALL)
    if len(body.strip()) < 200:
        rep.fail("body", "SKILL.md 正文过短（<200 字符）")

    headings = [line.lstrip("#").strip() for line in body.splitlines() if line.startswith("#")]
    joined = "\n".join(headings)
    missing = [label for label, pat in _SKILL_SECTIONS if not re.search(pat, joined, re.IGNORECASE)]
    if missing:
        rep.fail("sections", f"缺必备节: {missing}")

    # 标题存在不等于内容存在：七节逐节校验正文长度（≥20 字），防空壳组件过校验。
    missing, empty = _section_issues(body, _SKILL_SECTIONS)
    if empty:
        rep.fail("sections-empty", f"必备节只有标题没有内容: {empty}")

    files = _component_files(path)
    _check_text_hygiene(rep, path, files)
    _check_py(rep, path, files)
    _check_scale(rep, files)
    return rep


def validate_hook(path: Path) -> Report:
    rep = Report(str(path))
    if not path.is_dir():
        rep.fail("path", "hook 必须是目录")
        return rep
    if path.parent.name != "hooks":
        rep.fail("prefix", f"hook 必须位于 hooks/ 下，实际父目录 '{path.parent.name}'")

    files = _component_files(path)
    pys = [p for p in path.glob("*.py")]
    if not pys:
        rep.fail("script", "hooks/<name>/ 根目录缺 .py 脚本")

    readme = path / "README.md"
    if not readme.is_file():
        rep.fail("readme", "缺 README.md")
    else:
        text = _read_text(readme)
        missing = [label for label, pat in _HOOK_README_KEYWORDS
                   if not re.search(pat, text, re.IGNORECASE)]
        if missing:
            rep.fail("readme-keywords", f"README 缺要素: {missing}")

    settings = path / "settings.example.json"
    if not settings.is_file():
        rep.fail("settings", "缺 settings.example.json")
    else:
        try:
            data = json.loads(_read_text(settings))
        except json.JSONDecodeError as exc:
            rep.fail("settings-json", f"settings.example.json 非法 JSON: {exc}")
            data = None
        if isinstance(data, dict):
            if "hooks" not in data:
                rep.fail("settings-hooks", "settings.example.json 缺 hooks 键")
            else:
                for event, groups in (data.get("hooks") or {}).items():
                    if not isinstance(groups, list):
                        rep.fail("settings-shape", f"{event} 不是列表")
                        continue
                    for group in groups:
                        for hook in (group or {}).get("hooks", []) or []:
                            cmd = str(hook.get("command", ""))
                            if not cmd:
                                rep.fail("settings-command", f"{event} 的 hook 缺 command")
                            if "timeout" not in hook:
                                rep.warn("settings-timeout", f"{event} 的 hook 未设 timeout")

    for script in pys:
        wrapper = path / "win" / (script.stem + ".cmd")
        if not wrapper.is_file():
            rep.fail("win-wrapper", f"{script.name} 缺 win/{script.stem}.cmd 包装器")
        src = _read_text(script)
        if "stdin" not in src and "json.load(" not in src:
            rep.warn("hook-stdin", f"{script.name}: 未见 stdin 读取，确认是否消费事件 JSON")
        if re.search(r"open\([^)]*settings\.json[^)]*['\"][wa]", src) or "settings.json" in src and "write_text" in src:
            rep.warn("hook-settings-write", f"{script.name}: 疑似直接写 settings.json（应只给示例配置）")

    tests = path / "tests"
    if not tests.is_dir() or not any(tests.glob("*.json")):
        rep.fail("tests", "缺 tests/*.json 最小样例输入")

    _check_text_hygiene(rep, path, files)
    _check_py(rep, path, files)
    _check_scale(rep, files)
    return rep


def validate_agent(path: Path) -> Report:
    rep = Report(str(path))
    if not path.is_file() or path.suffix != ".md":
        rep.fail("path", "agent 必须是单个 .md 文件")
        return rep
    if path.parent.name != "agents":
        rep.fail("prefix", f"agent 必须位于 agents/ 下，实际父目录 '{path.parent.name}'")

    text = _read_text(path)
    fm, err = _parse_frontmatter(text)
    if err:
        rep.fail("fm", err)
    else:
        _check_frontmatter(rep, fm, _FRONTMATTER_ALLOWED_AGENT, path.stem, forbid_model=True)
        tools = fm.get("tools")
        if tools is not None and not isinstance(tools, str):
            rep.fail("fm-tools", "tools 必须是用逗号分隔的字符串（省略 = 继承全部工具）")

    body = re.sub(r"^---\r?\n.*?\r?\n---\s*", "", text, count=1, flags=re.DOTALL)
    if len(body.strip()) < 80:
        rep.fail("body", "agent 正文过短（<80 字符），无法构成系统提示")
    elif len(body.strip()) < 400:
        rep.warn("body-short", "agent 正文偏短（<400 字符）：最小样例可接受，正式代理应补职责与边界")

    headings = "\n".join(line.lstrip("#").strip()
                         for line in body.splitlines() if line.startswith("#"))
    missing = [label for label, pat in _AGENT_SECTIONS if not re.search(pat, headings, re.IGNORECASE)]
    if missing:
        rep.fail("sections", f"缺必备节: {missing}")

    _check_text_hygiene(rep, path.parent, [path])
    return rep


VALIDATORS = {"skill": validate_skill, "hook": validate_hook, "agent": validate_agent}


# ---------------------------------------------------------------- self-test

def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _fixtures(root: Path) -> None:
    good_skill = """---
name: probe-good-skill
description: 当用户需要检查文件命名规范时使用，给出命名建议并列出反例，不修改文件。
---

# Probe Good Skill

## 何时使用
用户要检查文件命名时使用；纯格式美化、重命名操作不要使用。

## 输入
目标目录路径（必填）；报告输出路径可选，默认写到当前目录。

## 流程
1. 读取目标目录的文件清单，跳过隐藏目录。
2. 逐个比对命名规则，输出违规清单与建议名。

## 输出
`reports/naming.md`，一行一个违规项，含建议名与违规类型。

## 边界
不修改任何文件，不重命名，不删除，只读扫描。

## 验收
`python -c "print(1)"` 退出码 0，且报告文件真实存在。

## 示例
输入 `src/`，输出 3 条违规与对应建议名。
"""
    bad_skill = ("---\nname: Probe_Bad\ndescription: 太短\nmodel: inherit\n---\n\n# Bad\n\n"
                 + "TO" + "DO: 待" + "补" + "充\n\ntoken: gh" + "p_" + "A" * 24 + "\n")
    empty_shell = ("---\nname: probe-empty-shell\ndescription: 当用户需要演示空壳技能如何绕过节级校验时使用，本样例故意只写标题不写内容。\n---\n\n# Empty Shell\n\n"
                   + "这是一段用来把正文长度撞过下限的填充文字，重复多次以免触发正文过短的检查。" * 4
                   + "\n\n## 何时使用\n略。\n\n## 输入\n略。\n\n## 流程\n略。\n\n"
                   + "## 输出\n略。\n\n## 边界\n略。\n\n## 验收\n略。\n\n## 示例\n略。\n")
    bad_path = (good_skill.replace("probe-good-skill", "probe-bad-path")
                .replace("# Probe Good Skill",
                         "# Probe Bad Path\n\n报告固定写到 " + "D" + ":/Project/reports/naming.md。"
                         + "\n\n兼容旧共享目录 " + chr(92) * 2 + "server" + chr(92) + "share。"))
    bad_py = good_skill.replace("probe-good-skill", "probe-bad-py")
    misplaced = good_skill.replace("probe-good-skill", "probe-misplaced")
    _write(root / "skills" / "probe-good-skill" / "SKILL.md", good_skill)
    _write(root / "skills" / "probe-bad-skill" / "SKILL.md", bad_skill)
    _write(root / "skills" / "probe-empty-shell" / "SKILL.md", empty_shell)
    _write(root / "skills" / "probe-bad-path" / "SKILL.md", bad_path)
    _write(root / "skills" / "probe-bad-py" / "SKILL.md", bad_py)
    _write(root / "skills" / "probe-bad-py" / "scripts" / "broken.py", "def broken(:\n    pass\n")
    _write(root / "misc" / "probe-misplaced" / "SKILL.md", misplaced)

    hook = root / "hooks" / "probe-good-hook"
    _write(hook / "README.md", "# Probe Hook\n\n触发事件：SessionStart\nmatcher：startup\n"
                               "输入：stdin JSON\n输出：无\n失败策略：fail-open exit 0\n"
                               "安装：合并 settings.example.json\n回滚：删除目录\n")
    _write(hook / "settings.example.json",
           '{"hooks": {"SessionStart": [{"hooks": [{"type": "command", '
           '"command": "~/.claude/hooks/probe-good-hook/probe.py", "timeout": 5}]}]}}')
    _write(hook / "probe.py", "import json, sys\njson.load(sys.stdin)\nsys.exit(0)\n")
    _write(hook / "win" / "probe.cmd", "@echo off\nexit /b 0\n")
    _write(hook / "tests" / "warmup.json", '{"session_id": "t"}\n')

    bad_hook = root / "hooks" / "probe-bad-hook"
    _write(bad_hook / "README.md", "# Bad Hook\n")
    _write(bad_hook / "probe.py", "import sys\nsys.exit(0)\n")
    _write(bad_hook / "settings.example.json", "{not json")

    good_agent = """---
name: probe-good-agent
description: 当主 agent 需要只回 OK 的最小派发样例时委派该子代理，用于验证 subagent 注册是否生效。
---

# Probe Good Agent

## 定位
最小可用子代理：收到任务只回 OK。

## 职责
确认派发链路可用，不处理真实业务。

## 边界
不读写文件，不调用工具。

## 输出
一行 `OK`。
"""
    bad_agent = """---
name: ProbeBadAgent
description: 短
model: inherit
---

# Bad
"""
    _write(root / "agents" / "probe-good-agent.md", good_agent)
    _write(root / "agents" / "probe-bad-agent.md", bad_agent)


def self_test() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _fixtures(root)

        cases = [
            ("good-skill", "skill", root / "skills" / "probe-good-skill", False),
            ("bad-skill", "skill", root / "skills" / "probe-bad-skill", True),
            ("empty-shell", "skill", root / "skills" / "probe-empty-shell", True),
            ("bad-path", "skill", root / "skills" / "probe-bad-path", True),
            ("bad-py", "skill", root / "skills" / "probe-bad-py", True),
            ("misplaced", "skill", root / "misc" / "probe-misplaced", True),
            ("good-hook", "hook", root / "hooks" / "probe-good-hook", False),
            ("bad-hook", "hook", root / "hooks" / "probe-bad-hook", True),
            ("good-agent", "agent", root / "agents" / "probe-good-agent.md", False),
            ("bad-agent", "agent", root / "agents" / "probe-bad-agent.md", True),
        ]
        for label, kind, path, expect_fail in cases:
            rep = VALIDATORS[kind](path)
            got_fail = rep.failed
            if got_fail != expect_fail:
                failures.append(f"{label}: 期望 {'失败' if expect_fail else '通过'}，实际 "
                                f"{'失败' if got_fail else '通过'}\n{rep.render()}")
            else:
                print(f"  ✅ {label}: {'按预期失败' if expect_fail else '按预期通过'}"
                      f"（{sum(1 for i in rep.items if i[0] == FAIL)} fail, "
                      f"{sum(1 for i in rep.items if i[0] == WARN)} warn）")

        # 负例必须命中具体检查项，防止“碰巧失败”。
        expected_codes = {
            root / "skills" / "probe-bad-skill":
                ("fm-model", "placeholder", "secret", "fm-name-kebab", "sections"),
            root / "skills" / "probe-empty-shell": ("sections-empty",),
            root / "skills" / "probe-bad-path": ("personal-path",),
            root / "skills" / "probe-bad-py": ("py-compile",),
            root / "misc" / "probe-misplaced": ("prefix",),
        }
        for path, codes_expected in expected_codes.items():
            codes = {code for _, code, _ in VALIDATORS["skill"](path).items}
            for code in codes_expected:
                if code not in codes:
                    failures.append(f"{path.name} 未命中预期检查项 {code}；实际 {sorted(codes)}")

        hook_codes = {code for _, code, _ in VALIDATORS["hook"](root / "hooks" / "probe-bad-hook").items}
        for code in ("readme-keywords", "settings-json", "win-wrapper", "tests"):
            if code not in hook_codes:
                failures.append(f"bad-hook 未命中预期检查项 {code}；实际 {sorted(hook_codes)}")

        agent_codes = {code for _, code, _ in VALIDATORS["agent"](root / "agents" / "probe-bad-agent.md").items}
        for code in ("fm-model", "fm-name-kebab", "sections"):
            if code not in agent_codes:
                failures.append(f"bad-agent 未命中预期检查项 {code}；实际 {sorted(agent_codes)}")

    if failures:
        print("\nself-test FAILED:")
        for item in failures:
            print(" -", item)
        return 1
    print("\nself-test PASSED: 正例通过、负例失败、检查项命中")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="组件静态校验器（skill/hook/agent）")
    parser.add_argument("--type", choices=sorted(VALIDATORS), help="组件类型")
    parser.add_argument("path", nargs="?", help="组件路径")
    parser.add_argument("--self-test", action="store_true", help="跑内置正负例自测")
    parser.add_argument("--json", action="store_true", help="以 JSON 输出结果")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.type or not args.path:
        parser.error("需要 --type 与 path（或使用 --self-test）")

    path = Path(args.path).resolve()
    rep = VALIDATORS[args.type](path)
    if args.json:
        print(json.dumps({"target": rep.target,
                          "failed": rep.failed,
                          "items": [{"level": l, "code": c, "message": m}
                                    for l, c, m in rep.items]},
                         ensure_ascii=False, indent=2))
    else:
        print(rep.render())
    return 1 if rep.failed else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    sys.exit(main())
