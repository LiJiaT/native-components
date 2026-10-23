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

# 内联命令前缀：check_script 以这些开头时视为命令，不检查文件路径
INLINE_CMD_PREFIXES = ("python", "python3", "bash", "sh", "node", "ruby", "perl")


def generate_task_id():
    """生成短任务 ID"""
    return "T-" + uuid.uuid4().hex[:6].upper()


def is_inline_command(check_script):
    """判断 check_script 是否为内联命令（如 python -c、bash -c），而非脚本路径。"""
    script = check_script.strip()
    return script.startswith(INLINE_CMD_PREFIXES) or (" -c " in script)


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
                "check_method": "manual",
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


def validate_task_package(filepath, strict=False):
    """验证任务包是否符合 schema。

    strict=True 时（分发前强制）:
      - §6.5 五类字段（input/dependencies/output_contract/acceptance_criteria/failure_handling）缺一 → 失败
      - acceptance_criteria 为空 → 失败
      - check_method=auto 的验收项没有 check_script → 失败（确定性优先，模型不得口头判 auto）
    """
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            pkg = json.load(f)
    except Exception as e:
        print(f"✗ 读取失败: {e}")
        return False

    required_fields = ["task_id", "name", "description", "input",
                       "output_contract", "acceptance_criteria", "execution"]
    missing = [f for f in required_fields if f not in pkg]

    if missing:
        print(f"✗ 缺少必填字段: {', '.join(missing)}")
        return False

    errors = []

    if strict:
        # §6.5 五项必含
        for field in REQUIRED_FIVE:
            if field not in pkg or pkg[field] is None:
                errors.append(f"§6.5 必含字段缺失: {field}")
        if not pkg.get("acceptance_criteria"):
            errors.append("验收清单为空 (acceptance_criteria)")
        # check_method=auto 必须有 check_script（确定性优先，模型不得口头判 auto）
        for item in pkg.get("acceptance_criteria") or []:
            check_script = item.get("check_script") or ""
            if item.get("check_method") == "auto":
                if not check_script:
                    errors.append(
                        f"验收项 {item.get('id', '?')}: check_method=auto 但无 check_script，"
                        "无法程序化重算；请改为 manual 或提供 check_script"
                    )
                elif not is_inline_command(check_script) and not os.path.exists(check_script):
                    errors.append(
                        f"验收项 {item.get('id', '?')}: check_script 路径不存在: {check_script}"
                    )
    else:
        if not pkg.get("acceptance_criteria"):
            print("⚠ 验收清单为空（--strict 下将失败）")

    # 检查执行配置
    exec_type = pkg.get("execution", {}).get("type")
    if exec_type not in VALID_TYPES:
        errors.append(f"无效的执行类型: {exec_type} (有效值: {', '.join(sorted(VALID_TYPES))})")
    if exec_type == "self":
        verifier = (
            pkg.get("execution", {}).get("verifier")
            or pkg.get("verification", {}).get("verifier")
        )
        if not verifier:
            errors.append(
                "execution.type=self 必须提供 execution.verifier"
                "（另一 sub-agent / 脚本路径 / 人）"
            )

    if errors:
        for e in errors:
            print(f"✗ {e}")
        return False

    mode = "strict" if strict else "loose"
    print(f"✓ 任务包验证通过 ({mode}): {pkg['task_id']} - {pkg['name']}")
    print(f"  执行类型: {exec_type}")
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
                            help="强制 §6.5 五类字段 + auto 必须有 check_script")

    # list
    list_parser = subparsers.add_parser("list", help="列出任务包")
    list_parser.add_argument("directory", nargs="?", default=".", help="目录路径")

    args = parser.parse_args()

    if args.command == "new":
        create_task_package(args.name, args.desc, args.type, args.output)
    elif args.command == "validate":
        ok = validate_task_package(args.file, strict=args.strict)
        sys.exit(0 if ok else 1)
    elif args.command == "list":
        ok = list_task_packages(args.directory)
        sys.exit(0 if ok else 1)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()