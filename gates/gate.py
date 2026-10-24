#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性门禁 CLI（失败关闭）。

子命令：
  record            校验单条 approved record + 审批绑定 + 内容 hash
  asset-registry    校验 eng-knowledge-assets 的 records/registry/INDEX 一致性
  component-registry 校验公共组件 registry（七字段、依赖、路径、循环）
  plan              校验计划六要素与审批 scope_hash
  acceptance        校验验收结果聚合与独立复核
  external-write    PreToolUse 外发拦截（默认拒绝，需人工预批准）
  memory            长期记忆写入前的原始记录/秘密检查
  task-package      调用 orchestrator/task_packager.py 做 strict 校验
  install           校验安装 manifest 与来源/范围

失败时 exit 1（或 external-write 返回 deny），成功 exit 0。所有判定写
~/.claude/audit/gates.jsonl（可用 AI_GATE_AUDIT_LOG 覆盖）。
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

try:
    import yaml
except ImportError:
    yaml = None

REPO = Path(__file__).resolve().parent.parent
AUDIT_LOG = Path(os.environ.get("AI_GATE_AUDIT_LOG",
                                str(Path.home() / ".claude" / "audit" / "gates.jsonl")))
APPROVAL_DIR = Path(os.environ.get("AI_GATE_APPROVAL_DIR",
                                   str(Path.home() / ".claude" / "audit" / "approvals")))
EXTERNAL_PATTERNS = [
    (r"(?i)\bgit\s+push\b", "git push"),
    (r"(?i)\bgit\s+remote\s+(add|set-url)\b", "git remote 变更"),
    (r"(?i)\bgh\s+(pr|release|repo)\s+(create|merge|close|edit|delete|upload)\b", "GitHub 写操作"),
    (r"(?i)\bnpm\s+publish\b", "npm publish"),
    (r"(?i)\b(twine|pip)\s+.*\bupload\b", "包上传"),
    (r"(?i)\bdocker\s+push\b", "docker push"),
    (r"(?i)\b(scp|rsync)\b.*[:]", "远程复制"),
    (r"(?i)\bcurl\b.*\s-X\s*(POST|PUT|PATCH|DELETE)\b", "HTTP 写请求"),
    (r"(?i)\bInvoke-(WebRequest|RestMethod)\b.*-(Method|Body)\b", "HTTP 写请求"),
    (r"(?i)\blark-cli\b.*\b(send|create|update|delete)\b", "飞书写操作"),
    (r"(?i)\bssh\b", "ssh"),
]
SECRET_PATTERNS = [
    re.compile(r"\b(ghp|gho|ghu|ghs|ghr|github_pat)_[A-Za-z0-9_]{16,}"),
    re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}"),
    re.compile(r"(?i)(password|passwd|pwd|api[_-]?key|secret|token)\s*[:=]\s*\S{6,}"),
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
]
RAW_PATTERNS = [
    re.compile(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+"
               r"(?:DEBUG|TRACE|INFO|WARN(?:ING)?|ERROR|FATAL)\b", re.I),
    re.compile(r"^\s*(?:Speaker\s*[A-Z0-9]+|说话人\s*[A-Z0-9一二三四五六七八九十]+)\s*[:：]", re.I),
]
AI_FORMS = {"Memory", "Rule", "Skill", "Workflow", "Hook", "Prompt"}
LAYERS = {"个人级", "项目级", "领域级", "公共级"}
PROVENANCE = {"verified", "source-excerpt", "synthetic"}
STATUSES = {"approved", "deprecated", "superseded", "withdrawn"}
LIFECYCLE = {"pending", "implemented", "installed", "withdrawn", "superseded"}
COMPONENT_TYPES = {"skill", "agent", "hook", "flow", "rule", "memory", "prompt",
                   "gate", "schema", "tool", "doc"}
COMPONENT_STATUS = {"active", "experimental", "test-only", "deprecated", "withdrawn"}


def audit(event, **fields):
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "pid": os.getpid(),
               "event": event, **fields}
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except Exception:
        pass


def die(msg, code=1):
    print(f"❌ {msg}")
    audit("fail", message=msg)
    sys.exit(code)


def ok(msg):
    print(f"✅ {msg}")
    audit("pass", message=msg)


def split_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        return None, text
    if yaml is None:
        return {"__no_yaml__": True}, m.group(2)
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}, ""


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def record_content_hash(fm, body):
    payload = {k: v for k, v in fm.items() if k != "implementation"}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str) + "\n---\n" + body
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_placeholder(v):
    return v is None or str(v).strip().lower() in {
        "", "-", "待填", "待定", "待补充", "todo", "tbd", "n/a", "xxx", "<待填>"}


def nonempty(v):
    return isinstance(v, str) and not is_placeholder(v)


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def find_record(assets_repo, asset_id):
    import glob
    hits = []
    for f in glob.glob(str(Path(assets_repo) / "assets" / "**" / "*.md"), recursive=True):
        fm, body = split_frontmatter(open(f, encoding="utf-8").read())
        if fm and fm.get("asset_id") == asset_id:
            hits.append((Path(f), fm, body))
    return hits


def approval_path(assets_repo, asset_id):
    return Path(assets_repo) / "approvals" / f"{asset_id}.json"


def verify_record(assets_repo, asset_id):
    hits = find_record(assets_repo, asset_id)
    if len(hits) != 1:
        die(f"{asset_id}: record 命中 {len(hits)} 条，必须唯一")
    path, fm, body = hits[0]
    required = ["asset_id", "proposal_id", "title", "form", "secondary_tags", "domains",
                "layer", "ai_form", "source", "owner", "status", "approved_by",
                "approved_date", "provenance_status", "provenance_note"]
    missing = [k for k in required if k not in fm]
    if missing:
        die(f"{asset_id}: record 缺字段 {missing}")
    for k in ("asset_id", "proposal_id", "title", "form", "source", "owner",
              "approved_by", "approved_date", "provenance_status", "provenance_note"):
        if not nonempty(fm.get(k)):
            die(f"{asset_id}: {k} 为空或占位符")
    if fm.get("layer") not in LAYERS:
        die(f"{asset_id}: layer 非法")
    if fm.get("ai_form") not in AI_FORMS:
        die(f"{asset_id}: ai_form 非法")
    if fm.get("provenance_status") not in PROVENANCE:
        die(f"{asset_id}: provenance_status 非法")
    if fm.get("status") not in STATUSES:
        die(f"{asset_id}: status 非法 {fm.get('status')!r}")
    if fm.get("status") != "approved":
        die(f"{asset_id}: status={fm.get('status')}，不可分发")
    projects = [x for x in as_list(fm.get("projects", fm.get("project"))) if x != "无"]
    if fm.get("layer") == "项目级" and len(projects) != 1:
        die(f"{asset_id}: 项目级必须且只能有一个项目")
    if len(projects) > 1 and fm.get("layer") not in ("领域级", "公共级"):
        die(f"{asset_id}: 多项目资产只能领域级/公共级")

    ap = approval_path(assets_repo, asset_id)
    if not ap.is_file():
        die(f"{asset_id}: 缺审批绑定文件 {ap}")
    try:
        approval = json.load(open(ap, encoding="utf-8"))
    except Exception as e:
        die(f"{asset_id}: 审批文件解析失败 {e}")
    for k in ("asset_id", "approver", "approved_at", "decision", "record_sha256",
              "content_sha256", "scope"):
        if k not in approval:
            die(f"{asset_id}: 审批文件缺 {k}")
    if approval.get("decision") != "approved":
        die(f"{asset_id}: 审批 decision={approval.get('decision')!r}")
    if approval.get("asset_id") != asset_id:
        die(f"{asset_id}: 审批文件 asset_id 不符")
    if approval.get("record_sha256") != sha256_file(path):
        die(f"{asset_id}: record 文件 hash 与审批绑定不一致（内容已变更，需重新审批）")
    if approval.get("content_sha256") != record_content_hash(fm, body):
        die(f"{asset_id}: record 正文/映射 hash 与审批绑定不一致")
    scope = approval.get("scope") or {}
    for k in ("layer", "ai_form", "owner", "provenance_status"):
        if scope.get(k) != fm.get(k):
            die(f"{asset_id}: 审批 scope.{k}={scope.get(k)!r} 与 record {fm.get(k)!r} 不一致")
    if sorted(as_list(scope.get("projects"))) != sorted(projects):
        die(f"{asset_id}: 审批 scope.projects 与 record 不一致")
    if sorted(as_list(scope.get("domains"))) != sorted(as_list(fm.get("domains"))):
        die(f"{asset_id}: 审批 scope.domains 与 record 不一致")
    return path, fm, body, approval


# ---------------------------------------------------------------- subcommands

def cmd_record(args):
    path, fm, body, approval = verify_record(args.assets_repo, args.asset_id)
    ok(f"record {args.asset_id} 完整且审批绑定当前内容（{path.name}）")


def cmd_asset_registry(args):
    repo = Path(args.assets_repo)
    reg = json.load(open(repo / "registry.json", encoding="utf-8"))
    entries = reg.get("assets")
    if not isinstance(entries, list):
        die("registry.json 缺 assets 列表")
    ids = [e.get("asset_id") for e in entries]
    if len(ids) != len(set(ids)):
        die("registry.json 存在重复 asset_id")
    index_text = (repo / "INDEX.md").read_text(encoding="utf-8") if (repo / "INDEX.md").exists() else ""
    errors = []
    for e in entries:
        aid = e.get("asset_id")
        try:
            path, fm, body, approval = verify_record(repo, aid)
        except SystemExit:
            errors.append(aid)
            continue
        for key in ("proposal_id", "title", "layer", "ai_form", "owner",
                    "provenance_status"):
            if e.get(key) != fm.get(key):
                errors.append(f"{aid}.{key}")
        if e.get("path") != str(path.relative_to(repo)).replace("\\", "/"):
            errors.append(f"{aid}.path")
        impl = e.get("implementation") or {}
        if impl.get("status") and impl["status"] not in LIFECYCLE:
            errors.append(f"{aid}.implementation.status")
        if impl.get("status") == "withdrawn" and impl.get("installed"):
            errors.append(f"{aid}: withdrawn 但仍有 installed 日期")
        if fm.get("provenance_status") == "synthetic":
            if impl and impl.get("installed") and impl.get("status") != "withdrawn":
                errors.append(f"{aid}: synthetic 不得有生产安装记录")
        if aid not in index_text:
            errors.append(f"{aid}: INDEX.md 未登记")
    if errors:
        die(f"asset registry 对账失败: {errors}")
    ok(f"asset registry 一致（{len(entries)} 条，审批/内容 hash/INDEX 全部通过）")


def cmd_component_registry(args):
    reg = json.load(open(Path(args.repo) / "registry.json", encoding="utf-8"))
    if reg.get("schema_version") != "1":
        die("component registry schema_version 必须为 '1'")
    comps = reg.get("components")
    if not isinstance(comps, list) or not comps:
        die("component registry 无组件")
    names, errors = [], []
    for c in comps:
        req = ["name", "type", "owner", "interface", "dependencies", "version", "status", "path"]
        missing = [k for k in req if k not in c]
        if missing:
            errors.append(f"{c.get('name', '?')}: 缺 {missing}")
            continue
        name = c["name"]
        if name in names:
            errors.append(f"重复组件: {name}")
        names.append(name)
        if c["type"] not in COMPONENT_TYPES:
            errors.append(f"{name}: type 非法")
        if c["status"] not in COMPONENT_STATUS:
            errors.append(f"{name}: status 非法")
        if not re.fullmatch(r"\d+\.\d+\.\d+", str(c["version"])):
            errors.append(f"{name}: version 非 semver")
        if not nonempty(c["owner"]):
            errors.append(f"{name}: owner 为空")
        if not nonempty(c["interface"]):
            errors.append(f"{name}: interface 为空")
        if not isinstance(c["dependencies"], list):
            errors.append(f"{name}: dependencies 必须是列表")
        p = Path(args.repo) / c["path"]
        if not p.exists():
            errors.append(f"{name}: path 不存在 {c['path']}")
    known = set(names)
    graph = {c.get("name"): [] for c in comps if isinstance(c, dict)}
    for c in comps:
        if not isinstance(c, dict):
            continue
        for d in c.get("dependencies") or []:
            if d.startswith("external:"):
                continue
            if d not in known:
                errors.append(f"{c.get('name')}: 依赖未知 {d}")
            else:
                graph[c["name"]].append(d)
    visiting, done = set(), set()

    def visit(n, stack):
        if n in done:
            return
        if n in visiting:
            errors.append("依赖环: " + " -> ".join(stack + [n]))
            return
        visiting.add(n)
        for d in graph.get(n, []):
            visit(d, stack + [n])
        visiting.discard(n); done.add(n)

    for n in graph:
        visit(n, [])
    if errors:
        die(f"component registry 失败: {errors}")
    ok(f"component registry 一致（{len(comps)} 个组件，七字段/依赖/路径通过）")


def cmd_plan(args):
    p = json.load(open(args.file, encoding="utf-8"))
    required = ["goal", "constraints", "inputs", "outputs", "boundaries", "acceptance",
                "human_gates", "version"]
    missing = [k for k in required if k not in p]
    if missing:
        die(f"计划缺字段: {missing}")
    for k in ("constraints", "inputs", "outputs", "boundaries", "acceptance", "human_gates"):
        if not isinstance(p[k], list) or not p[k]:
            die(f"计划 {k} 必须是非空列表")
    if not nonempty(p.get("goal")):
        die("计划 goal 为空")
    if not nonempty(p.get("version")):
        die("计划 version 为空")
    base = {k: v for k, v in p.items() if k != "approval"}
    digest = hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if args.require_approval:
        ap = p.get("approval") or {}
        if not ap:
            die("计划未经批准（缺 approval）")
        if ap.get("scope_hash") != digest:
            die("计划批准 scope_hash 与当前计划不一致（计划已变更，需重新确认）")
        if not nonempty(ap.get("approver")) or not nonempty(ap.get("approved_at")):
            die("计划 approval 缺 approver/approved_at")
    ok(f"计划六要素通过（scope_hash={digest[:12]}…）")


def cmd_acceptance(args):
    d = json.load(open(args.file, encoding="utf-8"))
    for k in ("task_id", "criteria", "verdict", "reviewer", "executor", "reviewed_at"):
        if k not in d:
            die(f"acceptance 缺 {k}")
    crit = d.get("criteria")
    if not isinstance(crit, list) or not crit:
        die("acceptance.criteria 为空")
    ids = [c.get("id") for c in crit if isinstance(c, dict)]
    if len(ids) != len(set(ids)) or any(not nonempty(x) for x in ids):
        die("验收项 id 缺失或重复")
    for c in crit:
        for k in ("expected", "evidence_path", "result"):
            if not c.get(k):
                die(f"验收项 {c.get('id')} 缺 {k}")
        if c["result"] not in ("pass", "fail", "blocked"):
            die(f"验收项 {c.get('id')} result 非法")
        if args.base_dir and not os.path.exists(os.path.join(args.base_dir, c["evidence_path"])):
            die(f"验收项 {c.get('id')} evidence_path 不存在: {c['evidence_path']}")
    if d.get("independent") is not True:
        die("acceptance 必须 independent: true")
    if d.get("reviewer") == d.get("executor"):
        die("reviewer 与 executor 相同，不是独立复核")
    recomputed = ("fail" if any(c["result"] == "fail" for c in crit)
                  else "blocked" if any(c["result"] == "blocked" for c in crit) else "pass")
    if d.get("verdict") != recomputed:
        die(f"verdict={d.get('verdict')!r} 与逐项结果重算 {recomputed!r} 不一致")
    if recomputed != "pass":
        die(f"验收未通过: {recomputed}")
    ok(f"验收结果一致（{len(crit)} 项全部 pass，独立复核）")


def cmd_external_write(args):
    if args.command:
        command = args.command
        payload = {}
    else:
        payload = json.load(sys.stdin)
        tool = payload.get("tool_name", "")
        if tool not in ("Bash", "Shell", "shell", "run_terminal_cmd"):
            audit("external-write-allow", tool=tool, reason="非 shell 工具")
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "allow"}}))
            return
        command = str((payload.get("tool_input") or {}).get("command", ""))
    hit = next((label for pat, label in EXTERNAL_PATTERNS if re.search(pat, command)), None)
    if not hit:
        audit("external-write-allow", command=command, reason="未命中外部写模式")
        if payload:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "allow"}}))
        else:
            ok("未命中外部写模式")
        return
    digest = hashlib.sha256(command.encode("utf-8")).hexdigest()
    ap = APPROVAL_DIR / f"{digest}.json"
    approved = False
    if ap.is_file():
        try:
            a = json.load(open(ap, encoding="utf-8"))
            approved = (a.get("command") == command
                        and float(a.get("expires_at", 0)) >= time.time()
                        and nonempty(a.get("approved_by")))
        except Exception:
            approved = False
    if approved:
        audit("external-write-allow", command=command, reason="human-approval", approval=str(ap))
        if payload:
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse", "permissionDecision": "allow"}}))
        else:
            ok("外部写命令已有人工预批准")
        return
    reason = (f"外部写动作被 R3 门禁拒绝（{hit}）。需人工预批准："
              f"python gates/gate.py approve --command \"{command}\" --by <人> --minutes 30")
    audit("external-write-deny", command=command, reason=hit)
    if payload:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": "deny",
            "permissionDecisionReason": reason}}))
    else:
        print(f"❌ {reason}")
        sys.exit(2)


def cmd_approve(args):
    digest = hashlib.sha256(args.command.encode("utf-8")).hexdigest()
    APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    ap = APPROVAL_DIR / f"{digest}.json"
    rec = {"command": args.command, "approved_by": args.by,
           "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "expires_at": time.time() + args.minutes * 60}
    ap.write_text(json.dumps(rec, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    audit("external-write-approve", command=args.command, approver=args.by,
          expires_in_minutes=args.minutes)
    ok(f"已写入人工预批准（{args.minutes} 分钟内有效）: {ap}")


def cmd_memory(args):
    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    raw = sum(1 for line in text.splitlines() if any(p.search(line) for p in RAW_PATTERNS))
    if raw >= 2:
        die(f"{args.file}: 疑似原始记录（{raw} 行时间戳/发言人），不得写入长期记忆")
    for p in SECRET_PATTERNS:
        if p.search(text):
            die(f"{args.file}: 疑似秘密/凭据，不得写入长期记忆")
    if args.require_provenance:
        fm, _ = split_frontmatter(text)
        if not fm or not fm.get("provenance_status"):
            die(f"{args.file}: 长期记忆缺 provenance_status")
    ok(f"memory 检查通过（{args.file}）")


def cmd_task_package(args):
    script = REPO / "skills" / "orchestrator" / "scripts" / "task_packager.py"
    cmd = [sys.executable, str(script), "validate", args.file]
    if args.strict:
        cmd.append("--strict")
    if args.tasks_dir:
        cmd += ["--tasks-dir", args.tasks_dir]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    sys.stdout.write(r.stdout)
    if r.returncode != 0:
        die("task package 校验失败")
    ok("task package 校验通过")


def cmd_install(args):
    m = json.load(open(args.manifest, encoding="utf-8"))
    for k in ("schema_version", "installed_at", "target_root", "components",
              "backup_root", "source_commit"):
        if k not in m:
            die(f"install manifest 缺 {k}")
    if m.get("schema_version") != "1":
        die("install manifest schema_version 必须为 '1'")
    for c in m.get("components") or []:
        for k in ("name", "version", "type", "source", "targets", "hashes"):
            if k not in c:
                die(f"install 组件 {c.get('name', '?')} 缺 {k}")
        if not c.get("targets"):
            die(f"install 组件 {c.get('name')} 无目标")
    ok(f"install manifest 通过（{len(m.get('components') or [])} 个组件）")


def build_parser():
    ap = argparse.ArgumentParser(description="确定性门禁（失败关闭）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("record")
    p.add_argument("--assets-repo", required=True)
    p.add_argument("--asset-id", required=True)
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("asset-registry")
    p.add_argument("--assets-repo", required=True)
    p.set_defaults(func=cmd_asset_registry)

    p = sub.add_parser("component-registry")
    p.add_argument("--repo", default=str(REPO))
    p.set_defaults(func=cmd_component_registry)

    p = sub.add_parser("plan")
    p.add_argument("--file", required=True)
    p.add_argument("--require-approval", action="store_true")
    p.set_defaults(func=cmd_plan)

    p = sub.add_parser("acceptance")
    p.add_argument("--file", required=True)
    p.add_argument("--base-dir")
    p.set_defaults(func=cmd_acceptance)

    p = sub.add_parser("external-write")
    p.add_argument("--command")
    p.set_defaults(func=cmd_external_write)

    p = sub.add_parser("approve")
    p.add_argument("--command", required=True)
    p.add_argument("--by", required=True)
    p.add_argument("--minutes", type=int, default=30)
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("memory")
    p.add_argument("--file", required=True)
    p.add_argument("--require-provenance", action="store_true")
    p.set_defaults(func=cmd_memory)

    p = sub.add_parser("task-package")
    p.add_argument("--file", required=True)
    p.add_argument("--strict", action="store_true")
    p.add_argument("--tasks-dir")
    p.set_defaults(func=cmd_task_package)

    p = sub.add_parser("install")
    p.add_argument("--manifest", required=True)
    p.set_defaults(func=cmd_install)
    return ap


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
