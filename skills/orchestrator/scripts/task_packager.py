#!/usr/bin/env python3
"""
任务包生成与管理工具。
用于 orchestrator 快速生成标准化任务包，减少手动格式错误。

用法:
  python task_packager.py new --name "读取文件" --desc "读取并分析文件" --type sub-agent
  python task_packager.py validate task.json [--strict]
  python task_packager.py list tasks/

--strict 强制 §6.5 五类字段（输入/依赖/产出契约/验收清单/失败处理）齐全，
check_method=auto 必须带 check_script（且脚本路径须存在，内联命令只要求非空），
execution.type=self 必须带 execution.verifier（§6.6 独立验收）。分发前必须通过 --strict。
"""

import argparse
import json
import os
import re
import shlex
import sys
import uuid
from datetime import datetime, timezone

# Windows 终端兼容：强制 UTF-8 输出
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# §6.5 必含的五类字段
REQUIRED_FIVE = ["input", "dependencies", "output_contract", "acceptance_criteria", "failure_handling"]

# execution.type 合法值（含 self 异常路径）
VALID_TYPES = {"sub-agent", "script", "skill", "hook", "self"}

# 内联命令：必须是 <interpreter> -c/-e <code> 的完整 argv，不能靠字符串前缀猜测
INLINE_INTERPRETERS = {
    "python", "python3", "py", "bash", "sh", "node", "ruby", "perl",
    "powershell", "pwsh",
}
CHECK_METHODS = {"manual", "auto"}
SEVERITIES = {"blocker", "major", "minor"}
TASK_STATUS = {"todo", "running", "done", "failed", "blocked"}
TASK_CLASS = {"deterministic", "judgment"}
RETRY_STRATEGIES = {"same_executor", "new_executor", "escalate", "none"}
MODEL_DEFAULT_ALLOWLIST = {
    "DeepSeek-V4-Flash-Official", "GLM-5.3", "Kimi-K3", "MiniMax-M3",
    "claude-sonnet-4-20250514", "claude-opus-4-1-20250805",
}


def generate_task_id():
    """生成短任务 ID"""
    return "T-" + uuid.uuid4().hex[:6].upper()


def parse_check_script(check_script, base_dir):
    """返回 (kind, argv|error)。kind: inline|file。"""
    try:
        argv = shlex.split(check_script, posix=True)
    except ValueError as e:
        return None, f"check_script 无法解析: {e}"
    if not argv:
        return None, "check_script 为空"
    head = os.path.basename(argv[0]).lower()
    if head in INLINE_INTERPRETERS:
        if len(argv) < 3 or argv[1] not in ("-c", "-e"):
            return None, (f"内联命令必须是 `{head} -c '<code>'` 形式，"
                          f"不能把解释器名当任意前缀")
        return "inline", argv
    path = argv[0] if os.path.isabs(argv[0]) else os.path.join(base_dir, argv[0])
    if not os.path.isfile(path):
        return None, f"check_script 路径不存在: {argv[0]}"
    return "file", argv


def create_task_package(name, description, task_type, output_path=None):
    """创建一个最小任务包模板"""
    task_id = generate_task_id()
    now = datetime.now(timezone.utc).isoformat()

    # model 只对 sub-agent 有意义；脚本/skill/hook 是确定性执行，不写模型
    execution = {
        "type": task_type,
        "target": "",
        "timeout_seconds": 300,
    }
    if task_type == "sub-agent":
        execution["model"] = "DeepSeek-V4-Flash-Official"
    if task_type == "self":
        # self 是异常路径（§6.6：仅内部推理、不交付），必须指定独立 verifier
        execution["verifier"] = ""

    package = {
        "task_id": task_id,
        "name": name,
        "description": description,
        "phase": "execution",
        "input": {
            "files": [],
            "data": {},
            "context_summary": ""
        },
        "dependencies": [],
        "output_contract": {
            "primary": {
                "type": "text",
                "format": "markdown",
                "location": "直接在回复中输出"
            },
            "must_not_include": []
        },
        "acceptance_criteria": [
            {
                "id": "AC-01",
                "description": "完成任务目标",
                "expected": "<可观察的期望结果>",
                "evidence_path": "<证据落点：文件/日志/命令输出>",
                "check_method": "manual",
                "check_script": "",
                "independent_review": True,
                "severity": "major"
            }
        ],
        "failure_handling": {
            "max_retries": 2,
            "retry_strategy": "same_executor",
            "escalation_target": "orchestrator"
        },
        "execution": execution,
        "metadata": {
            "created_at": now,
            "created_by": "orchestrator",
            "priority": "medium",
            "estimated_complexity": "medium",
            "task_class": "deterministic" if task_type != "sub-agent" else "judgment",
            "status": "todo",
            "tags": []
        }
    }

    # 根据类型调整默认值
    if task_type == "script":
        package["execution"]["timeout_seconds"] = 60
    elif task_type == "skill":
        package["execution"]["timeout_seconds"] = 600
    elif task_type == "sub-agent":
        package["execution"]["timeout_seconds"] = 300

    if output_path:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(package, f, indent=2, ensure_ascii=False)
        print(f"✓ 任务包已生成: {output_path}")
    else:
        print(json.dumps(package, indent=2, ensure_ascii=False))

    return package


def _nonempty_str(v):
    return isinstance(v, str) and bool(v.strip())


def _type_name(v):
    return type(v).__name__


def _validate_shape(pkg, errors):
    """类型/结构检查；不依赖 strict，任何调用方都不该拿到形状错误的任务包。"""
    if not _nonempty_str(pkg.get("task_id")):
        errors.append("task_id 必须是非空字符串")
    if not _nonempty_str(pkg.get("name")):
        errors.append("name 必须是非空字符串")
    if not _nonempty_str(pkg.get("description")):
        errors.append("description 必须是非空字符串")

    inp = pkg.get("input")
    if not isinstance(inp, dict):
        errors.append(f"input 必须是对象，实际 {_type_name(inp)}")
    else:
        if not isinstance(inp.get("files", []), list) or not all(isinstance(x, str) for x in inp.get("files", [])):
            errors.append("input.files 必须是字符串列表")
        if not isinstance(inp.get("data", {}), dict):
            errors.append("input.data 必须是对象")
        if not isinstance(inp.get("context_summary", ""), str):
            errors.append("input.context_summary 必须是字符串")

    deps = pkg.get("dependencies")
    if not isinstance(deps, list) or not all(isinstance(x, str) and x.strip() for x in deps):
        errors.append("dependencies 必须是非空字符串列表（可为空列表）")

    oc = pkg.get("output_contract")
    if not isinstance(oc, dict):
        errors.append(f"output_contract 必须是对象，实际 {_type_name(oc)}")
    else:
        primary = oc.get("primary")
        if not isinstance(primary, dict):
            errors.append("output_contract.primary 必须是对象")
        else:
            for key in ("type", "format", "location"):
                if not _nonempty_str(primary.get(key)):
                    errors.append(f"output_contract.primary.{key} 必须是非空字符串")
        if not isinstance(oc.get("must_not_include", []), list):
            errors.append("output_contract.must_not_include 必须是列表")

    ac = pkg.get("acceptance_criteria")
    if not isinstance(ac, list):
        errors.append(f"acceptance_criteria 必须是列表，实际 {_type_name(ac)}")
        return
    if not ac:
        errors.append("验收清单为空 (acceptance_criteria)")
    ids = []
    for i, item in enumerate(ac):
        if not isinstance(item, dict):
            errors.append(f"acceptance_criteria[{i}] 必须是对象，实际 {_type_name(item)}")
            continue
        aid = item.get("id")
        if not _nonempty_str(aid):
            errors.append(f"acceptance_criteria[{i}].id 为空")
        elif aid in ids:
            errors.append(f"验收项 id 重复: {aid}")
        else:
            ids.append(aid)
        if not _nonempty_str(item.get("description")):
            errors.append(f"验收项 {aid or i}: description 为空")
        if item.get("check_method") not in CHECK_METHODS:
            errors.append(f"验收项 {aid or i}: check_method 非法 {item.get('check_method')!r}")
        if item.get("severity") not in SEVERITIES:
            errors.append(f"验收项 {aid or i}: severity 非法 {item.get('severity')!r}")
        if not _nonempty_str(item.get("expected")):
            errors.append(f"验收项 {aid or i}: expected 为空（必须写可观察的期望结果）")
        if not _nonempty_str(item.get("evidence_path")):
            errors.append(f"验收项 {aid or i}: evidence_path 为空（必须写证据落点）")
        if not isinstance(item.get("independent_review"), bool):
            errors.append(f"验收项 {aid or i}: independent_review 必须是布尔值")

    fh = pkg.get("failure_handling")
    if not isinstance(fh, dict):
        errors.append(f"failure_handling 必须是对象，实际 {_type_name(fh)}")
    else:
        if not isinstance(fh.get("max_retries"), int) or fh.get("max_retries", -1) < 0:
            errors.append("failure_handling.max_retries 必须是非负整数")
        if fh.get("retry_strategy") not in RETRY_STRATEGIES:
            errors.append(f"failure_handling.retry_strategy 非法: {fh.get('retry_strategy')!r}")
        if not _nonempty_str(fh.get("escalation_target")):
            errors.append("failure_handling.escalation_target 为空")

    ex = pkg.get("execution")
    if not isinstance(ex, dict):
        errors.append(f"execution 必须是对象，实际 {_type_name(ex)}")
        return
    exec_type = ex.get("type")
    if exec_type not in VALID_TYPES:
        errors.append(f"无效的执行类型: {exec_type} (有效值: {', '.join(sorted(VALID_TYPES))})")
    if not _nonempty_str(ex.get("target")):
        errors.append("execution.target 为空")
    to = ex.get("timeout_seconds")
    if not isinstance(to, int) or not (1 <= to <= 86400):
        errors.append("execution.timeout_seconds 必须是 1..86400 的整数")
    if exec_type == "sub-agent" and not _nonempty_str(ex.get("model")):
        errors.append("execution.type=sub-agent 必须提供 model")
    if exec_type in ("script", "hook") and _nonempty_str(ex.get("target")):
        probe = ex["target"] if os.path.isabs(ex["target"]) else os.path.join(os.path.dirname(os.path.abspath(pkg["__file__"])), ex["target"])
        if not os.path.isfile(probe) and not shlex.split(ex["target"])[0] in INLINE_INTERPRETERS:
            errors.append(f"execution.target 脚本不存在: {ex['target']}")
    if exec_type == "self":
        verifier = ex.get("verifier") or pkg.get("verification", {}).get("verifier")
        if not _nonempty_str(verifier):
            errors.append("execution.type=self 必须提供 execution.verifier")
        elif verifier.strip().lower() in ("same-run", "same_run", "self", ex.get("target", "")):
            errors.append("execution.verifier 不能与执行者/同一 run 相同（独立验收）")


def _validate_strict(pkg, errors, base_dir, tasks_dir=None):
    for field in REQUIRED_FIVE:
        if field not in pkg or pkg[field] is None:
            errors.append(f"§6.5 必含字段缺失: {field}")

    meta = pkg.get("metadata")
    if not isinstance(meta, dict):
        errors.append("metadata 必须是对象")
        meta = {}
    if meta.get("task_class") not in TASK_CLASS:
        errors.append(f"metadata.task_class 必须是 {sorted(TASK_CLASS)} 之一")
    if meta.get("status") not in TASK_STATUS:
        errors.append(f"metadata.status 必须是 {sorted(TASK_STATUS)} 之一")

    task_id = pkg.get("task_id")
    deps = pkg.get("dependencies") or []
    if task_id in deps:
        errors.append("dependencies 不得包含自身 task_id（自依赖）")
    if len(deps) != len(set(deps)):
        errors.append("dependencies 存在重复项")
    if [d for d in deps if not str(d).startswith("external:")] and not tasks_dir:
        errors.append("存在内部依赖时必须提供 --tasks-dir，以核对依赖任务已完成")

    major_independent = False
    for i, item in enumerate(pkg.get("acceptance_criteria") or []):
        if not isinstance(item, dict):
            continue
        aid = item.get("id", i)
        if item.get("check_method") == "auto":
            check_script = item.get("check_script")
            if not _nonempty_str(check_script):
                errors.append(f"验收项 {aid}: check_method=auto 但无 check_script")
            else:
                kind, detail = parse_check_script(check_script, base_dir)
                if kind is None:
                    errors.append(f"验收项 {aid}: {detail}")
        if item.get("independent_review") is not True and item.get("severity") == "blocker":
            errors.append(f"验收项 {aid}: blocker 级验收必须 independent_review=true")
        if item.get("severity") == "major" and item.get("independent_review") is True:
            major_independent = True
    if not major_independent:
        errors.append("至少一项 major 验收必须 independent_review=true（独立复核）")

    ex = pkg.get("execution") or {}
    ex_type = ex.get("type")
    task_class = meta.get("task_class")
    if ex_type == "sub-agent":
        model = ex.get("model")
        if task_class != "judgment":
            errors.append("sub-agent 任务的 metadata.task_class 必须是 judgment")
        if model not in MODEL_DEFAULT_ALLOWLIST:
            errors.append(f"execution.model 不在允许清单: {model!r}")
    else:
        if ex.get("model"):
            errors.append(f"{ex_type} 是确定性执行，不得指定 model（模型路由门禁）")
        if task_class == "judgment" and ex_type not in ("self",):
            errors.append(f"{ex_type} 任务的 metadata.task_class 必须是 deterministic")

    if tasks_dir:
        check_dag(pkg, tasks_dir, errors)


def check_dag(pkg, tasks_dir, errors):
    """按目录内全部任务检查重复 ID、断链与环。"""
    all_tasks = {}
    for fname in os.listdir(tasks_dir):
        if not fname.endswith(".json"):
            continue
        try:
            other = json.load(open(os.path.join(tasks_dir, fname), encoding="utf-8"))
        except Exception:
            continue
        tid = other.get("task_id")
        if tid:
            all_tasks.setdefault(tid, []).append(fname)
    dup = [k for k, v in all_tasks.items() if len(v) > 1]
    if dup:
        errors.append(f"任务 ID 重复: {dup}")
    ids = set(all_tasks) | {pkg.get("task_id")}
    graph = {pkg.get("task_id"): list(pkg.get("dependencies") or [])}
    for tid in all_tasks:
        try:
            t = json.load(open(os.path.join(tasks_dir, all_tasks[tid][0]), encoding="utf-8"))
            graph[tid] = list(t.get("dependencies") or [])
        except Exception:
            pass
    for d in pkg.get("dependencies") or []:
        if d.startswith("external:"):
            continue
        if d not in all_tasks:
            errors.append(f"任务 {pkg.get('task_id')} 依赖不存在: {d}")
            continue
        try:
            dep = json.load(open(os.path.join(tasks_dir, all_tasks[d][0]), encoding="utf-8"))
        except Exception as e:
            errors.append(f"依赖 {d} 读取失败: {e}")
            continue
        status = (dep.get("metadata") or {}).get("status")
        if status != "done":
            errors.append(f"依赖 {d} 状态为 {status!r}，必须为 done 才能派发")

    for tid, ds in graph.items():
        for d in ds:
            if d not in ids and not d.startswith("external:"):
                errors.append(f"任务 {tid} 依赖不存在: {d}")

    visiting, done = set(), set()

    def visit(node, stack):
        if node in done:
            return True
        if node in visiting:
            errors.append("依赖环: " + " -> ".join(stack + [node]))
            return False
        visiting.add(node)
        for d in graph.get(node, []):
            if d in graph and not visit(d, stack + [node]):
                return False
        visiting.discard(node); done.add(node)
        return True

    for tid in list(graph):
        visit(tid, [])


def validate_task_package(filepath, strict=False, tasks_dir=None):
    """验证任务包是否符合 schema（默认结构层，strict 为分发前门禁）。"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            pkg = json.load(f)
    except Exception as e:
        print(f"✗ 读取失败: {e}")
        return False
    if not isinstance(pkg, dict):
        print("✗ 任务包必须是 JSON 对象")
        return False
    pkg["__file__"] = os.path.abspath(filepath)

    required_fields = ["task_id", "name", "description", "input",
                       "output_contract", "acceptance_criteria", "execution"]
    missing = [f for f in required_fields if f not in pkg]
    if missing:
        print(f"✗ 缺少必填字段: {', '.join(missing)}")
        return False

    errors = []
    _validate_shape(pkg, errors)
    if strict:
        _validate_strict(pkg, errors, os.path.dirname(os.path.abspath(filepath)), tasks_dir)

    if errors:
        for e in errors:
            print(f"✗ {e}")
        return False

    mode = "strict" if strict else "loose"
    print(f"✓ 任务包验证通过 ({mode}): {pkg['task_id']} - {pkg['name']}")
    print(f"  执行类型: {pkg.get('execution', {}).get('type')}")
    print(f"  验收项数: {len(pkg.get('acceptance_criteria', []))}")
    return True


def list_task_packages(directory):
    """列出目录中的所有任务包。目录不存在返回 False。"""
    if not os.path.isdir(directory):
        print(f"✗ 目录不存在: {directory}")
        return False

    tasks = []
    for fname in os.listdir(directory):
        if fname.endswith('.json'):
            fpath = os.path.join(directory, fname)
            try:
                with open(fpath, 'r', encoding='utf-8') as f:
                    pkg = json.load(f)
                tasks.append({
                    "id": pkg.get("task_id", "?"),
                    "name": pkg.get("name", fname),
                    "phase": pkg.get("phase", "?"),
                    "type": pkg.get("execution", {}).get("type", "?")
                })
            except Exception:
                pass

    if not tasks:
        print("（无任务包）")
        return True

    print(f"任务包列表 ({len(tasks)} 个):")
    print("-" * 60)
    for t in tasks:
        print(f"  {t['id']:8s}  {t['phase']:12s}  {t['type']:10s}  {t['name']}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Orchestrator 任务包工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # new
    new_parser = subparsers.add_parser("new", help="创建新任务包")
    new_parser.add_argument("--name", required=True, help="任务名称")
    new_parser.add_argument("--desc", required=True, help="任务描述")
    new_parser.add_argument("--type", default="sub-agent",
                           choices=sorted(VALID_TYPES),
                           help="执行类型 (default: sub-agent; self 为异常路径，须配 verifier)")
    new_parser.add_argument("-o", "--output", help="输出文件路径")

    # validate
    val_parser = subparsers.add_parser("validate", help="验证任务包")
    val_parser.add_argument("file", help="任务包 JSON 文件")
    val_parser.add_argument("--strict", action="store_true",
                            help="分发前门禁：类型/枚举/依赖/路由/独立验收全量校验")
    val_parser.add_argument("--tasks-dir", help="同批任务包目录，用于重复 ID、断链与依赖环检查")

    # list
    list_parser = subparsers.add_parser("list", help="列出任务包")
    list_parser.add_argument("directory", nargs="?", default=".", help="目录路径")

    args = parser.parse_args()

    if args.command == "new":
        create_task_package(args.name, args.desc, args.type, args.output)
    elif args.command == "validate":
        ok = validate_task_package(args.file, strict=args.strict, tasks_dir=args.tasks_dir)
        sys.exit(0 if ok else 1)
    elif args.command == "list":
        ok = list_task_packages(args.directory)
        sys.exit(0 if ok else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()