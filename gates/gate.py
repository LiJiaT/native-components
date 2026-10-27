#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""确定性门禁 CLI（失败关闭）。

子命令：
  record            校验单条 approved record + 审批绑定 + 内容 hash
  asset-registry    校验 native-assets 的 records/registry/INDEX 一致性
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
from datetime import datetime
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
    # git 的全局参数（-C/-c/--git-dir）必须先于子命令识别
    (r"(?i)(?:^|[;&|]\s*|\s)git\b[^;&|\n]*?\s(?:push|remote\s+(?:add|set-url|remove|rename)|"
     r"lfs\s+push)\b", "git 远程写操作"),
    (r"(?i)\bgh\s+(?:pr|release|repo|issue|gist|workflow)\s+"
     r"(?:create|merge|close|edit|delete|upload|comment|run|dispatch|enable|disable)\b",
     "GitHub 写操作"),
    (r"(?i)\bgh\s+api\b.*(?:-X\s*(?:POST|PUT|PATCH|DELETE)|--method[= ](?:POST|PUT|PATCH|DELETE)|"
     r"-f\b|--field\b|--raw-field\b)", "GitHub API 写操作"),
    (r"(?i)\b(?:npm|pnpm|yarn)\s+publish\b", "npm publish"),
    (r"(?i)\b(?:twine|pip|python\s+-m\s+twine)\s+.*\bupload\b", "包上传"),
    (r"(?i)\b(?:docker|podman)\s+push\b", "容器镜像推送"),
    (r"(?i)\b(?:gem\s+push|cargo\s+publish|mvn\s+deploy|gradle\s+publish|"
     r"dotnet\s+nuget\s+push)\b", "包发布"),
    (r"(?i)\b(?:kubectl|helm|terraform|ansible)\b.*\b(?:apply|create|delete|patch|replace|"
     r"upgrade|install|uninstall|push)\b", "基础设施写操作"),
    (r"(?i)\b(?:aws|gcloud|az)\b.*\b(?:create|put|delete|update|copy|sync|upload|deploy|"
     r"publish|set|modify|rm|cp|mv)\b", "云平台写操作"),
    (r"(?i)\b(?:scp|rsync|sftp|ftp|telnet|nc|ncat|socat)\b.*(?:[:]\S|\s\S+:\S)", "远程传输"),
    (r"(?i)\bcurl\b.*(?:-X\s*(?:POST|PUT|PATCH|DELETE)|--request\s+(?:POST|PUT|PATCH|DELETE)|"
     r"-d\b|--data(?:-raw|-binary|-urlencode)?\b|-F\b|--form\b|-T\b|--upload-file\b|--json\b)",
     "HTTP 写请求"),
    (r"(?i)\bwget\b.*(?:--post-data|--post-file|--method[= ](?:POST|PUT|PATCH|DELETE)|--body-data)",
     "HTTP 写请求"),
    (r"(?i)(?:^|[;&|]\s*|\s)(?:https?|http)\s+(?:POST|PUT|PATCH|DELETE)\b", "HTTP 写请求"),
    (r"(?i)\bInvoke-(?:WebRequest|RestMethod)\b.*(?:-(?:Method|Body|InFile)\b)", "HTTP 写请求"),
    (r"(?i)\blark-cli\b.*\b(?:send|create|update|delete|write|upload|move|copy)\b", "飞书写操作"),
    (r"(?i)\bssh\s+\S", "ssh"),
    (r"(?i)\b(?:python|python3|node|nodejs)\b.*(?:requests\.(?:post|put|patch|delete)|"
     r"httpx\.(?:post|put|patch|delete|stream)|aiohttp\.|urllib\.request|http\.client|"
     r"socket\.socket|paramiko|urlopen\s*\([^)]*data\s*=|axios\.(?:post|put|patch|delete)|"
     r"fetch\s*\([^)]*method\s*[:=]\s*['\"](?:POST|PUT|PATCH|DELETE))", "脚本网络写请求"),
    (r"(?i)\b(?:mail|sendmail|mailx)\b.*(?:-s\b|--subject)", "邮件发送"),
]
MCP_WRITE_RE = re.compile(
    r"(?i)(?:^|[_-])(?:push|create|update|delete|merge|close|edit|upload|send|write|comment|"
    r"publish|release|add|remove|move|copy|install|run|batch|set|permission|grant|revoke|"
    r"approve|trigger|dispatch|start|stop|kill|rename|chmod|chown|archive|restore|import|"
    r"export|submit|post|put|patch|attach|detach|assign|unassign|invite|join|leave|lock|"
    r"unlock|pin|unpin|star|unstar|fork|sync|deploy)(?:[_-]|$)")
# 只读/本地只读 MCP 能力白名单；未知 MCP 能力默认拒绝。
MCP_SAFE_TOOLS = {
    "mcp__github__issue_read", "mcp__github__pull_request_read",
    "mcp__github__run_secret_scanning", "mcp__web_search__search",
    "mcp__web_search__fetch",
    "mcp__plugin_qoder-qmind_qoder-qmind__retrieve",
    "mcp__plugin_qoder-qmind_qoder-qmind__list_notebooks",
    "mcp__plugin_qoder-qmind_qoder-qmind__list_sources",
    "mcp__plugin_qoder-qmind_qoder-qmind__read_source",
    "mcp__plugin_knowledge-center_repowiki__ListWiki",
    "mcp__plugin_knowledge-center_repowiki__ReadWiki",
    "mcp__plugin_knowledge-center_repowiki__list_wiki",
    "mcp__plugin_knowledge-center_repowiki__read_wiki",
    "mcp__plugin_knowledge-center_repowiki__list_knowledge",
    "mcp__plugin_knowledge-center_repowiki__read_knowledge",
    "mcp__qoder-settings__search_extensions",
}
MCP_SAFE_RE = re.compile(
    r"(?i)^(?:get|list|search|query|read|fetch|view|show|describe|status|help|retrieve|"
    r"take_screenshot|take_snapshot|navigate_page|wait_for|select_page|hover|evaluate_script|"
    r"download_storage_file|list_pages|list_console_messages|list_network_requests)(?:_|$)")
EXTERNAL_READ_TOOLS = {"Read", "Grep", "Glob", "Bash", "Shell", "shell", "run_terminal_cmd"}
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
FORMS = {"知识库", "工程规则", "决策记忆", "技能工作流"}
LAYERS = {"个人级", "项目级", "领域级", "公共级"}
PROVENANCE = {"verified", "source-excerpt", "synthetic"}
STATUSES = {"approved", "deprecated", "superseded", "withdrawn"}
LIFECYCLE = {"pending", "implemented", "installed", "withdrawn", "superseded"}
COMPONENT_TYPES = {"skill", "agent", "hook", "flow", "rule", "memory", "prompt",
                   "gate", "schema", "tool", "doc"}
COMPONENT_STATUS = {"active", "experimental", "test-only", "deprecated", "withdrawn"}
PUBLIC_ENTRY_GLOBS = ("rules/*.md", "skills/*/SKILL.md", "agents/*.md",
                      "flows/*/README.md")


_AUDIT_CTX = {}
_DENY_COUNTS = Path(os.environ.get(
    "AI_GATE_DENY_COUNTS", str(AUDIT_LOG.parent / "deny-counts.json")))


def set_audit_context(**fields):
    _AUDIT_CTX.clear()
    _AUDIT_CTX.update({k: v for k, v in fields.items() if v not in (None, "")})


def audit(event, required=False, **fields):
    """写入结构化审计；返回是否成功。安全关键门禁应传 required=True。"""
    try:
        AUDIT_LOG.parent.mkdir(parents=True, exist_ok=True)
        decision = ("allow" if event.endswith(("allow", "pass"))
                    else "deny" if event.endswith(("deny", "fail")) else "")
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "pid": os.getpid(),
               "session_id": os.environ.get("AI_GATE_SESSION_ID", ""),
               "rule": "", "input_hash": "", "decision": decision,
               **_AUDIT_CTX, "event": event, **fields}
        with open(AUDIT_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return True
    except Exception as e:
        if required:
            print(f"⚠️ 审计日志写入失败: {e}", file=sys.stderr)
        return False


def _bump_deny_count(key):
    try:
        _DENY_COUNTS.parent.mkdir(parents=True, exist_ok=True)
        try:
            data = json.loads(_DENY_COUNTS.read_text(encoding="utf-8"))
        except Exception:
            data = {}
        item = data.get(key) or {"count": 0}
        item["count"] = int(item.get("count", 0)) + 1
        item["updated_at"] = time.time()
        data[key] = item
        _DENY_COUNTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                encoding="utf-8")
        return item["count"]
    except Exception:
        return 1


def _clear_deny_count(key):
    try:
        data = json.loads(_DENY_COUNTS.read_text(encoding="utf-8"))
        if key in data:
            data.pop(key, None)
            _DENY_COUNTS.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                                    encoding="utf-8")
    except Exception:
        pass


def die(msg, code=1):
    print(f"❌ {msg}")
    audit("fail", message=msg)
    sys.exit(code)


def ok(msg):
    print(f"✅ {msg}")
    required = bool(_AUDIT_CTX.get("require_audit"))
    if not audit("pass", required=required, message=msg) and required:
        print("❌ 安全关键门禁无法写审计日志，按失败关闭退出", file=sys.stderr)
        sys.exit(1)


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
    # Git checkout line endings differ by OS; hash canonical LF bytes.
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


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


def valid_date(value):
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+Z-]+)?", text):
        return False
    try:
        datetime.fromisoformat(text.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def schema_dir():
    env = os.environ.get("AI_GATE_SCHEMA_DIR")
    if env:
        return Path(env)
    installed = Path(__file__).resolve().parent / "schemas"
    return installed if installed.is_dir() else REPO / "schemas"


def load_schema(name):
    path = schema_dir() / name
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return None


def validate_schema(value, schema, path="$"):
    """最小 JSON Schema 执行器：覆盖仓库 schema 使用的关键字。

    支持 type/required/properties/additionalProperties/items/enum/const/
    pattern/minLength/minItems/maxItems/oneOf/anyOf。返回错误列表。
    """
    errors = []
    if not isinstance(schema, dict):
        return errors
    if "oneOf" in schema:
        matched = sum(1 for s in schema["oneOf"] if not validate_schema(value, s, path))
        if matched != 1:
            errors.append(f"{path}: oneOf 匹配 {matched} 个分支")
        return errors
    if "anyOf" in schema:
        if not any(not validate_schema(value, s, path) for s in schema["anyOf"]):
            errors.append(f"{path}: anyOf 无匹配分支")
        return errors
    if "const" in schema and value != schema["const"]:
        errors.append(f"{path}: 应为常量 {schema['const']!r}")
    if "enum" in schema and value not in schema["enum"]:
        errors.append(f"{path}: {value!r} 不在枚举 {schema['enum']}")
    typ = schema.get("type")
    if typ:
        types = typ if isinstance(typ, list) else [typ]
        py_types = {"object": dict, "array": list, "string": str, "integer": int,
                    "number": (int, float), "boolean": bool, "null": type(None)}
        if not any(isinstance(value, py_types.get(t, object)) and
                   not (t in ("integer", "number") and isinstance(value, bool)) for t in types):
            errors.append(f"{path}: 类型应为 {typ}，实际 {type(value).__name__}")
            return errors
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append(f"{path}: 长度小于 {schema['minLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], value):
            errors.append(f"{path}: 不匹配 {schema['pattern']}")
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append(f"{path}: 项数少于 {schema['minItems']}")
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append(f"{path}: 项数多于 {schema['maxItems']}")
        if isinstance(schema.get("items"), dict):
            for i, item in enumerate(value):
                errors += validate_schema(item, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: 缺必填 {key}")
        props = schema.get("properties") or {}
        for key, sub in props.items():
            if key in value:
                errors += validate_schema(value[key], sub, f"{path}.{key}")
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(props))
            if extra:
                errors.append(f"{path}: 不允许的额外字段 {extra}")
    return errors


def check_schema(name, instance, label):
    schema = load_schema(name)
    if schema is None:
        die(f"{label}: 找不到 schema {name}（可用 AI_GATE_SCHEMA_DIR 指定）")
    errors = validate_schema(instance, schema)
    if errors:
        die(f"{label} schema 校验失败: {errors}")


def nonempty_items(value):
    return isinstance(value, list) and value and all(
        isinstance(x, str) and not is_placeholder(x) for x in value)


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


def _verify_asset_signature(assets_repo, asset_id, approval, raw):
    signers = Path(assets_repo) / "approvals" / "allowed_signers"
    if not signers.is_file():
        return None
    sig = Path(assets_repo) / "approvals" / f"{asset_id}.sig"
    if not sig.is_file():
        return False
    try:
        r = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(signers),
             "-I", str(approval.get("approver", "")), "-n", "asset-approval",
             "-s", str(sig)], input=raw, capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def verify_record(assets_repo, asset_id, require_distributable=False):
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
    if fm.get("form") not in FORMS:
        die(f"{asset_id}: form 非法 {fm.get('form')!r}")
    if not valid_date(fm.get("approved_date")):
        die(f"{asset_id}: approved_date 不是有效日期")
    if fm.get("ai_form") is None:
        if fm.get("mapping_status") not in ("unmapped", "deferred"):
            die(f"{asset_id}: ai_form 为空时必须声明 mapping_status=unmapped|deferred")
        if not nonempty(fm.get("mapping_reason")):
            die(f"{asset_id}: ai_form 未映射时必须给出非空 mapping_reason")
    elif fm.get("ai_form") not in AI_FORMS:
        die(f"{asset_id}: ai_form 非法")
    if fm.get("provenance_status") not in PROVENANCE:
        die(f"{asset_id}: provenance_status 非法")
    if fm.get("status") not in STATUSES:
        die(f"{asset_id}: status 非法 {fm.get('status')!r}")
    if require_distributable and fm.get("status") != "approved":
        die(f"{asset_id}: status={fm.get('status')}，不可新分发")
    if require_distributable and fm.get("ai_form") not in AI_FORMS:
        die(f"{asset_id}: 未映射 ai_form，不可新分发")
    if require_distributable and str(fm.get("release_channel")) == "test-only":
        die(f"{asset_id}: test-only 资产不可进入生产分发")
    projects = [x for x in as_list(fm.get("projects", fm.get("project"))) if x != "无"]
    if fm.get("layer") == "项目级" and len(projects) != 1:
        die(f"{asset_id}: 项目级必须且只能有一个项目")
    if len(projects) > 1 and fm.get("layer") not in ("领域级", "公共级"):
        die(f"{asset_id}: 多项目资产只能领域级/公共级")
    impl = fm.get("implementation") or {}
    if fm.get("status") == "withdrawn" and impl.get("status") == "installed":
        die(f"{asset_id}: record 已 withdrawn 但 implementation 仍 installed")

    ap = approval_path(assets_repo, asset_id)
    if not ap.is_file():
        die(f"{asset_id}: 缺审批绑定文件 {ap}")
    try:
        raw = ap.read_bytes()
        approval = json.loads(raw.decode("utf-8"))
    except Exception as e:
        die(f"{asset_id}: 审批文件解析失败 {e}")
    for k in ("asset_id", "approver", "approved_at", "decision",
              "content_sha256", "scope"):
        if k not in approval:
            die(f"{asset_id}: 审批文件缺 {k}")
    if approval.get("decision") != "approved":
        die(f"{asset_id}: 审批 decision={approval.get('decision')!r}")
    if approval.get("asset_id") != asset_id:
        die(f"{asset_id}: 审批文件 asset_id 不符")
    if approval.get("binding_scope") == "full-file" and \
            approval.get("record_sha256") != sha256_file(path):
        die(f"{asset_id}: 审批显式绑定全文件但 record hash 不一致")
    if approval.get("content_sha256") != record_content_hash(fm, body):
        die(f"{asset_id}: record 正文/映射 hash 与审批绑定不一致")
    signed = _verify_asset_signature(assets_repo, asset_id, approval, raw)
    if signed is False:
        die(f"{asset_id}: 审批签名缺失或无效")
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
    set_audit_context(rule="asset-record", input_hash=args.asset_id, require_audit=True)
    path, fm, body, approval = verify_record(
        args.assets_repo, args.asset_id, getattr(args, "require_distributable", False))
    ok(f"record {args.asset_id} 完整且审批绑定当前内容（{path.name}）")


def cmd_asset_registry(args):
    repo = Path(args.assets_repo)
    set_audit_context(rule="asset-registry", input_hash=str(repo), require_audit=True)
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
            path, fm, body, approval = verify_record(
                repo, aid, getattr(args, "require_distributable", False))
        except SystemExit:
            errors.append(aid)
            continue
        for key in ("proposal_id", "title", "form", "layer", "ai_form", "owner",
                    "status", "approved_by", "approved_date", "provenance_status",
                    "provenance_note", "release_channel"):
            if e.get(key) != fm.get(key):
                errors.append(f"{aid}.{key}")
        if sorted(as_list(e.get("domains"))) != sorted(as_list(fm.get("domains"))):
            errors.append(f"{aid}.domains")
        rec_projects = sorted(x for x in as_list(fm.get("projects", fm.get("project")))
                              if x != "无")
        if sorted(x for x in as_list(e.get("projects", e.get("project"))) if x != "无") \
                != rec_projects:
            errors.append(f"{aid}.projects")
        if e.get("path") != str(path.relative_to(repo)).replace("\\", "/"):
            errors.append(f"{aid}.path")
        impl = e.get("implementation") or {}
        rec_impl = fm.get("implementation") or {}
        if impl.get("status") and impl["status"] not in LIFECYCLE:
            errors.append(f"{aid}.implementation.status")
        for key in ("status", "package", "ai_infra_repo", "installed", "installed_by"):
            if impl.get(key) != rec_impl.get(key):
                errors.append(f"{aid}.implementation.{key}")
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
    set_audit_context(rule="component-registry", input_hash=str(args.repo), require_audit=True)
    repo = Path(args.repo)
    if not (repo / "registry.json").is_file():
        installed = Path(__file__).resolve().parent / "registry.json"
        if installed.is_file():
            repo = installed.parent
    reg_path = repo / "registry.json"
    if not reg_path.is_file():
        die(f"找不到 registry.json: {reg_path}（安装时需包含 gate-core 的 registry 快照）")
    path_repo = repo
    try:
        manifest = json.load(open(repo.parent / "install-manifest-latest.json",
                                  encoding="utf-8"))
        source_repo = Path(manifest.get("source_repo", ""))
        if source_repo.is_dir():
            path_repo = source_repo
    except Exception:
        pass
    reg = json.load(open(reg_path, encoding="utf-8"))
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
        p = path_repo / c["path"]
        if not p.exists():
            errors.append(f"{name}: path 不存在 {c['path']}（repo={path_repo}）")
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
    registered = []
    for c in comps:
        if isinstance(c, dict) and c.get("path"):
            registered.append((path_repo / c["path"]).resolve())
    for pattern in PUBLIC_ENTRY_GLOBS:
        for entry in path_repo.glob(pattern):
            if not entry.is_file() or entry.name.startswith(".") or entry.name == "README.md":
                continue
            resolved = entry.resolve()
            if not any(resolved == r or r in resolved.parents for r in registered):
                errors.append(f"公共入口未登记 registry: "
                              f"{entry.relative_to(path_repo).as_posix()}")
    if errors:
        die(f"component registry 失败: {errors}")
    ok(f"component registry 一致（{len(comps)} 个组件，七字段/依赖/路径/公共入口覆盖通过）")


def _validate_acceptance_items(items):
    ids = []
    for i, item in enumerate(items or []):
        if isinstance(item, str):
            if is_placeholder(item):
                die(f"计划 acceptance[{i}] 是占位字符串")
            continue
        if not isinstance(item, dict):
            die(f"计划 acceptance[{i}] 必须是字符串或对象")
        for key in ("id", "expected", "check_method", "evidence"):
            if not nonempty(item.get(key)):
                die(f"计划 acceptance[{i}] 缺非空 {key}")
        if item.get("check_method") not in ("manual", "auto"):
            die(f"计划 acceptance[{i}].check_method 非法")
        if item.get("check_method") == "auto" and not nonempty(item.get("check_script")):
            die(f"计划 acceptance[{i}] auto 必须给 check_script")
        ids.append(item["id"])
    if len(ids) != len(set(ids)):
        die("计划 acceptance id 重复")


def cmd_plan(args):
    set_audit_context(rule="plan", input_hash=sha256_raw(Path(args.file)), require_audit=True)
    try:
        p = json.load(open(args.file, encoding="utf-8"))
    except Exception as e:
        die(f"计划解析失败: {e}")
    if not isinstance(p, dict):
        die("计划必须是 JSON 对象")
    check_schema("plan.schema.json", p, "计划")
    for k in ("constraints", "inputs", "outputs", "boundaries", "human_gates"):
        if not nonempty_items(p.get(k)):
            die(f"计划 {k} 必须是非空列表且每项为非占位字符串")
    _validate_acceptance_items(p.get("acceptance"))
    if not nonempty(p.get("goal")):
        die("计划 goal 为空")
    if not nonempty(p.get("version")):
        die("计划 version 为空")
    rc = p.get("requirement_card") or {}
    rc_path = _resolve(Path(args.file).resolve().parent, rc.get("path", ""))
    if not rc_path.is_file():
        die(f"需求卡不存在: {rc_path}")
    if rc.get("sha256") != sha256_raw(rc_path):
        die("需求卡 hash 与 requirement_card.sha256 不一致")
    acc_hash = hashlib.sha256(json.dumps(
        p.get("acceptance"), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
    if p.get("acceptance_criteria_hash") != acc_hash:
        die("acceptance_criteria_hash 与当前验收标准不一致")
    base = {k: v for k, v in p.items() if k not in ("approval", "plan_hash")}
    digest = hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if p.get("plan_hash") not in (None, "") and p.get("plan_hash") != digest:
        die("计划 plan_hash 与当前内容不一致")
    if args.require_approval:
        ap = p.get("approval")
        if not isinstance(ap, dict) or not ap:
            die("计划未经批准（缺 approval）")
        if ap.get("decision") != "approved":
            die(f"计划批准 decision={ap.get('decision')!r}，必须为 approved")
        if ap.get("scope_hash") != digest:
            die("计划批准 scope_hash 与当前计划不一致（计划已变更，需重新确认）")
        if not nonempty(ap.get("approver")) or not valid_date(ap.get("approved_at")):
            die("计划 approval 缺 approver 或 approved_at 不是有效日期")
        if ap.get("approval_ref") is not None and not nonempty(ap.get("approval_ref")):
            die("计划 approval_ref 为空")
    ok(f"计划六要素通过（schema+类型+占位符，scope_hash={digest[:12]}…）")


def _resolve(base, value):
    p = Path(value)
    return p if p.is_absolute() else Path(base) / p


def _check_file_hash(path, expected, label):
    if not path.is_file():
        die(f"{label} 证据不存在: {path}")
    if path.is_dir():
        die(f"{label} 证据不能是目录: {path}")
    actual = sha256_raw(path)
    if expected != actual:
        die(f"{label} 证据 hash 与记录不一致（文件已变更）")


def _concrete_path(value):
    if not nonempty(value) or "<" in str(value) or "回复" in str(value):
        return ""
    text = str(value).strip()
    name = Path(text).name
    return text if ("/" in text or "\\" in text or "." in name) else ""


def _required_artifacts(task):
    oc = task.get("output_contract") or {}
    out = []
    for key in ("required_artifacts", "artifacts"):
        val = oc.get(key)
        if isinstance(val, list):
            for item in val:
                path = item.get("path") if isinstance(item, dict) else item
                p = _concrete_path(path)
                if p:
                    out.append(p)
    primary = oc.get("primary") or {}
    for key in ("path", "location"):
        p = _concrete_path(primary.get(key))
        if p:
            out.append(p)
    return sorted(set(out))


def cmd_acceptance(args):
    set_audit_context(rule="acceptance", input_hash=sha256_raw(Path(args.file)), require_audit=True)
    try:
        d = json.load(open(args.file, encoding="utf-8"))
    except Exception as e:
        die(f"acceptance 解析失败: {e}")
    check_schema("acceptance.schema.json", d, "acceptance")
    base = Path(args.base_dir or Path(args.file).resolve().parent)
    for k in ("task_id", "reviewer", "executor", "reviewer_run_id",
              "executor_run_id", "reviewed_at"):
        if not nonempty(d.get(k)):
            die(f"acceptance.{k} 为空或占位符")
    if not valid_date(d.get("reviewed_at")):
        die("acceptance.reviewed_at 不是有效日期")
    if d.get("independent") is not True:
        die("acceptance 必须 independent: true")
    if d.get("reviewer") == d.get("executor"):
        die("reviewer 与 executor 相同，不是独立复核")
    if d.get("reviewer_run_id") == d.get("executor_run_id"):
        die("reviewer_run_id 与 executor_run_id 相同，不是独立运行")

    # 任务包绑定：AC 集合、命令与契约必须来自原任务包
    tp_rel = d.get("task_package")
    if not nonempty(tp_rel):
        die("acceptance 缺 task_package（必须绑定原任务包）")
    tp_path = _resolve(base, tp_rel)
    if not tp_path.is_file():
        die(f"task_package 不存在: {tp_path}")
    if not nonempty(d.get("task_package_sha256")) or d.get("task_package_sha256") != sha256_raw(tp_path):
        die("task_package_sha256 缺失或与当前任务包不一致")
    try:
        task = json.load(open(tp_path, encoding="utf-8"))
    except Exception as e:
        die(f"task_package 解析失败: {e}")
    if task.get("task_id") != d.get("task_id"):
        die("acceptance.task_id 与任务包不一致")
    task_criteria = {c.get("id"): c for c in task.get("acceptance_criteria") or []
                     if isinstance(c, dict) and c.get("id")}
    crit = d.get("criteria")
    if not isinstance(crit, list) or not crit:
        die("acceptance.criteria 为空")
    ids = [c.get("id") for c in crit if isinstance(c, dict)]
    if len(ids) != len(set(ids)) or any(not nonempty(x) for x in ids):
        die("验收项 id 缺失或重复")
    if set(ids) != set(task_criteria):
        die(f"验收项集合与任务包不一致: 结果={sorted(set(ids))} 任务={sorted(task_criteria)}")
    expected_checklist = hashlib.sha256(json.dumps(
        task.get("acceptance_criteria"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if d.get("checklist_hash") != expected_checklist:
        die("acceptance.checklist_hash 与任务包验收清单不一致")

    required_artifacts = _required_artifacts(task)
    art = d.get("artifact_sha256")
    if not isinstance(art, dict) or not art:
        die("acceptance 缺 artifact_sha256（产物版本绑定）")
    art_norm = {str(Path(k)).replace("\\", "/"): k for k in art}
    missing_art = [p for p in required_artifacts
                   if str(Path(p)).replace("\\", "/") not in art_norm]
    if missing_art:
        die(f"acceptance 缺少任务包必交付产物: {missing_art}")

    reviewer_inputs = d.get("reviewer_inputs")
    if not isinstance(reviewer_inputs, list) or not reviewer_inputs:
        die("acceptance 缺 reviewer_inputs（复核输入清单）")
    review_paths = set()
    for item in reviewer_inputs:
        path = _resolve(base, item["path"])
        _check_file_hash(path, item["sha256"], f"复核输入 {item['path']}")
        review_paths.add(str(path.resolve()))
    if str(tp_path.resolve()) not in review_paths:
        die("reviewer_inputs 未包含任务包（复核未绑定原任务契约）")
    for rel in art:
        if str(_resolve(base, rel).resolve()) not in review_paths:
            die(f"reviewer_inputs 未包含产物 {rel}（复核输入不完整）")

    for c in crit:
        for k in ("expected", "evidence_path", "result", "evidence_sha256"):
            if not c.get(k):
                die(f"验收项 {c.get('id')} 缺 {k}")
        if c["result"] not in ("pass", "fail", "blocked"):
            die(f"验收项 {c.get('id')} result 非法")
        tc = task_criteria.get(c["id"]) or {}
        if c.get("expected") != tc.get("expected"):
            die(f"验收项 {c.get('id')} expected 与任务包不一致")
        if c.get("check_method") != tc.get("check_method"):
            die(f"验收项 {c.get('id')} check_method 与任务包不一致")
        task_evidence = _concrete_path(tc.get("evidence_path"))
        if task_evidence and (str(Path(c["evidence_path"])).replace("\\", "/")
                              != str(Path(task_evidence)).replace("\\", "/")):
            die(f"验收项 {c.get('id')} evidence_path 与任务包指定证据不一致")
        ev = _resolve(base, c["evidence_path"])
        if ev.is_dir():
            die(f"验收项 {c.get('id')} evidence_path 不能是目录")
        _check_file_hash(ev, c["evidence_sha256"], f"验收项 {c.get('id')}")
        if str(ev.resolve()) not in review_paths:
            die(f"reviewer_inputs 未包含验收项 {c.get('id')} 的证据")

    for rel, expected in art.items():
        _check_file_hash(_resolve(base, rel), expected, f"产物 {rel}")

    self_review = d.get("self_review")
    if not isinstance(self_review, dict) or self_review.get("result") != "pass":
        die("acceptance 缺 self_review 或结果非 pass（执行方逐项自查证据）")
    if not nonempty(self_review.get("evidence_path")) or not nonempty(self_review.get("evidence_sha256")):
        die("self_review 缺 evidence_path/evidence_sha256")
    self_path = _resolve(base, self_review["evidence_path"])
    if self_path.is_dir():
        die("self_review evidence_path 不能是目录")
    _check_file_hash(self_path, self_review["evidence_sha256"], "self_review")
    if str(self_path.resolve()) not in review_paths:
        die("reviewer_inputs 未包含自查记录")
    for finding in self_review.get("findings") or []:
        fid = finding.get("id", "?")
        if finding.get("disposition") in (None, "", "open"):
            die(f"自查 finding {fid} 未处置（disposition=open/缺失）")
        if finding.get("disposition") in ("rejected", "deferred") and \
                not nonempty(finding.get("reason")):
            die(f"自查 finding {fid} disposition={finding.get('disposition')} 但缺 reason")

    recomputed = ("fail" if any(c["result"] == "fail" for c in crit)
                  else "blocked" if any(c["result"] == "blocked" for c in crit) else "pass")
    if d.get("verdict") != recomputed:
        die(f"verdict={d.get('verdict')!r} 与逐项结果重算 {recomputed!r} 不一致")
    if recomputed != "pass":
        die(f"验收未通过: {recomputed}")
    ok(f"验收结果与任务包/证据/产物绑定一致（{len(crit)} 项全部 pass，独立复核）")


def _iso_expiry(minutes):
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(time.time() + minutes * 60))


def _approval_key(command=None, tool=None, tool_input=None):
    if tool:
        return "mcp:" + tool + ":" + json.dumps(tool_input or {}, sort_keys=True,
                                                ensure_ascii=False)
    return command or ""


def _approval_path(key):
    digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
    return APPROVAL_DIR / f"{digest}.json"


def _signature_policy():
    """返回 (required, signers_path, error)。显式配置即视为严格模式。"""
    explicit = os.environ.get("AI_GATE_ALLOWED_SIGNERS", "").strip()
    flag = os.environ.get("AI_GATE_REQUIRE_SIGNATURE", "").strip().lower()
    required = flag in ("1", "true", "yes", "required") or bool(explicit)
    signers = Path(explicit) if explicit else APPROVAL_DIR / "allowed_signers"
    if required and not signers.is_file():
        return True, signers, f"严格签名策略已启用但 allowed_signers 不存在: {signers}"
    return required, signers, ""


def _allowed_signers():
    return _signature_policy()[1]


def _verify_signature(ap_path, approval, raw):
    """返回 True/False/None；严格模式缺策略/签名一律 False。"""
    required, signers, _ = _signature_policy()
    if not signers.is_file():
        return False if required else None
    sig = ap_path.with_suffix(".sig")
    if not sig.is_file():
        return False
    principal = str(approval.get("approved_by") or "")
    try:
        r = subprocess.run(
            ["ssh-keygen", "-Y", "verify", "-f", str(signers), "-I", principal,
             "-n", "ai-gate", "-s", str(sig)],
            input=raw, capture_output=True, timeout=15)
        return r.returncode == 0
    except Exception:
        return False


def _approval_valid(key, ap_path):
    if not ap_path.is_file():
        return False, "缺少批准文件"
    required, signers, policy_error = _signature_policy()
    if policy_error:
        return False, policy_error
    try:
        raw = ap_path.read_bytes()
        a = json.loads(raw.decode("utf-8"))
        key_ok = a.get("key") == key if a.get("key") is not None else (
            a.get("command") == key)
        expires = a.get("expires_at")
        if isinstance(expires, str):
            exp_ok = valid_date(expires) and datetime.fromisoformat(
                expires.replace("Z", "+00:00")).timestamp() >= time.time()
        else:
            exp_ok = float(expires or 0) >= time.time()
        signed = _verify_signature(ap_path, a, raw)
        if required and (signed is not True or a.get("approval_method") != "ssh-signature"):
            return False, "严格签名模式要求有效 SSH 签名批准"
        ok = (key_ok and exp_ok and nonempty(a.get("approved_by"))
              and a.get("decision", "approved") == "approved"
              and signed is not False)
        if signed is False:
            return False, "批准签名缺失或无效"
        if not ok:
            return False, "批准内容/有效期/批准人不符合"
        return True, "human-signed" if signed else "human-unsigned-compat"
    except Exception as e:
        return False, f"批准文件解析失败: {e}"


def _emit_external(payload, decision, reason):
    if payload:
        print(json.dumps({"hookSpecificOutput": {
            "hookEventName": "PreToolUse", "permissionDecision": decision,
            "permissionDecisionReason": reason}}))
    else:
        print(("❌ " if decision == "deny" else "✅ ") + reason)
        if decision == "deny":
            sys.exit(2)


def cmd_external_write(args):
    try:
        return _cmd_external_write(args)
    except SystemExit:
        raise
    except Exception as e:
        # 失败关闭：任何解析/IO/异常都必须给出 deny，不能放行
        reason = f"外发门禁内部异常，按失败关闭拒绝: {e}"
        audit("external-write-deny", reason=reason)
        _emit_external({} if args.command else {"_": True}, "deny", reason)
        return


def _mcp_is_safe(tool):
    return tool in MCP_SAFE_TOOLS or bool(MCP_SAFE_RE.match(tool.rsplit("__", 1)[-1]))


def _deny_external(payload, tool, command, key, hit, why, rule="R3/external-write"):
    input_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    session = os.environ.get("AI_GATE_SESSION_ID", "")
    set_audit_context(rule=rule, input_hash=input_hash, session_id=session)
    count = _bump_deny_count(f"{rule}|{session}|{input_hash}")
    escalation = count >= 3
    if tool:
        approval_example = f"--tool {tool} --input-json <json>"
    else:
        approval_example = '--command "' + command + '"'
    reason = (f"外部写动作被 R3 门禁拒绝（{hit}；{why}）。需人工预批准："
              f"python gates/gate.py approve --by <人> --minutes 30 "
              f"{approval_example}")
    if escalation:
        reason += f"。同一输入已连续拒绝 {count} 次，升级人工审批并停止重试"
    audit("external-write-deny", required=True, tool=tool, command=command,
          reason=hit, detail=why, deny_count=count, escalated=escalation)
    _emit_external(payload, "deny", reason)


def _cmd_external_write(args):
    payload = {}
    command = ""
    tool = ""
    tool_input = {}
    if args.command:
        command = args.command.strip()
        if not command:
            _deny_external({}, "", "", "", "命令为空", "缺少可判定的命令文本")
            return
        hit = next((label for pat, label in EXTERNAL_PATTERNS if re.search(pat, command)), None)
        key = _approval_key(command=command)
    else:
        raw = sys.stdin.read().lstrip("\ufeff").strip()
        try:
            payload = json.loads(raw) if raw else {}
        except Exception as e:
            reason = f"PreToolUse 输入不是合法 JSON，按失败关闭拒绝: {e}"
            audit("external-write-deny", required=True, reason=reason)
            _emit_external({"_": True}, "deny", reason)
            return
        if not isinstance(payload, dict):
            _deny_external({}, "", "", "", "事件形状非法", "PreToolUse 输入不是 JSON 对象")
            return
        tool = str(payload.get("tool_name", "")).strip()
        tool_input = payload.get("tool_input")
        if not tool:
            _deny_external(payload, "", "", "", "事件形状非法", "缺少 tool_name，无法判定外部写")
            return
        if not isinstance(tool_input, dict):
            _deny_external(payload, tool, "", "", "事件形状非法", "tool_input 不是对象")
            return
        if tool.startswith("mcp__") or tool.startswith("mcp_"):
            key = _approval_key(tool=tool, tool_input=tool_input)
            if _mcp_is_safe(tool):
                set_audit_context(rule="R3/external-write",
                                  input_hash=hashlib.sha256(key.encode()).hexdigest())
                if not audit("external-write-allow", required=True, tool=tool,
                             reason="MCP 只读白名单"):
                    _deny_external(payload, tool, "", key, "审计不可写", "审计失败关闭")
                    return
                _clear_deny_count(f"R3/external-write|{os.environ.get('AI_GATE_SESSION_ID','')}|"
                                  f"{hashlib.sha256(key.encode()).hexdigest()}")
                _emit_external(payload, "allow", f"MCP 只读能力: {tool}")
                return
            if MCP_WRITE_RE.search(tool.rsplit("__", 1)[-1]):
                hit = f"MCP 写操作 {tool}"
            else:
                _deny_external(payload, tool, "", key, "未知 MCP 能力",
                               "未在只读白名单内，默认拒绝")
                return
        elif tool in ("Bash", "Shell", "shell", "run_terminal_cmd"):
            command = str(tool_input.get("command", "")).strip()
            if not command:
                _deny_external(payload, tool, "", "", "命令为空", "shell 事件缺少 command")
                return
            hit = next((label for pat, label in EXTERNAL_PATTERNS if re.search(pat, command)), None)
            key = _approval_key(command=command)
        else:
            audit("external-write-allow", tool=tool, reason="非 shell/MCP 工具")
            _emit_external(payload, "allow", f"非外部写工具: {tool}")
            return
    input_hash = hashlib.sha256(key.encode("utf-8")).hexdigest()
    set_audit_context(rule="R3/external-write", input_hash=input_hash)
    if not hit:
        if not audit("external-write-allow", required=True, tool=tool, command=command,
                     reason="未命中外部写模式"):
            _deny_external(payload, tool, command, key, "审计不可写", "审计失败关闭")
            return
        _clear_deny_count(f"R3/external-write|{os.environ.get('AI_GATE_SESSION_ID','')}|"
                          f"{input_hash}")
        _emit_external(payload, "allow", "未命中外部写模式")
        return
    approved, why = _approval_valid(key, _approval_path(key))
    if approved:
        if not audit("external-write-allow", required=True, tool=tool, command=command,
                     reason=why, approval=str(_approval_path(key))):
            _deny_external(payload, tool, command, key, "审计不可写", "审计失败关闭")
            return
        _clear_deny_count(f"R3/external-write|{os.environ.get('AI_GATE_SESSION_ID','')}|"
                          f"{input_hash}")
        _emit_external(payload, "allow", f"外部写已有人工预批准（{why}）")
        return
    _deny_external(payload, tool, command, key, hit, why)


def cmd_approve(args):
    tool = getattr(args, "tool", None)
    tool_input = {}
    if tool:
        try:
            tool_input = json.loads(args.input_json or "{}")
        except Exception as e:
            die(f"--input-json 解析失败: {e}")
    key = _approval_key(command=args.command, tool=tool, tool_input=tool_input)
    if not key:
        die("必须提供 --command 或 --tool")
    required, signers, policy_error = _signature_policy()
    if policy_error:
        die(policy_error)
    rec = {"schema_version": "1", "key": key,
           "command": args.command or "", "tool": tool or "",
           "approved_by": args.by,
           "approved_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "expires_at": _iso_expiry(args.minutes),
           "decision": "approved", "approval_method": "unsigned"}
    APPROVAL_DIR.mkdir(parents=True, exist_ok=True)
    ap = _approval_path(key)
    raw = json.dumps(rec, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    if signers.is_file():
        key_file = Path(os.environ.get("AI_GATE_APPROVAL_KEY",
                                       str(Path.home() / ".claude" / "gates" / "approval_key")))
        if not key_file.is_file():
            die(f"已启用签名批准但找不到私钥 {key_file}；"
                "请由人运行 ssh-keygen -t ed25519 -f <key> 并把公钥写入 "
                f"{signers}（principal={args.by}）")
        rec["approval_method"] = "ssh-signature"
        raw = json.dumps(rec, sort_keys=True, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
        tmp = ap.with_suffix(".unsigned.tmp")
        tmp.write_bytes(raw)
        sig = tmp.with_suffix(".tmp.sig")
        try:
            r = subprocess.run(["ssh-keygen", "-Y", "sign", "-f", str(key_file),
                                "-n", "ai-gate", str(tmp)],
                               input=b"", capture_output=True, timeout=120)
        except Exception as e:
            tmp.unlink(missing_ok=True)
            die(f"签名调用失败: {e}")
        if r.returncode != 0:
            tmp.unlink(missing_ok=True)
            die("签名失败（私钥可能带口令但当前无交互终端）："
                f"{(r.stderr or b'').decode('utf-8', 'replace')[:300]}")
        ap.write_bytes(raw)
        if sig.is_file():
            ap.with_suffix(".sig").write_bytes(sig.read_bytes())
            sig.unlink(missing_ok=True)
        tmp.unlink(missing_ok=True)
        if not _verify_signature(ap, rec, raw):
            ap.unlink(missing_ok=True); ap.with_suffix(".sig").unlink(missing_ok=True)
            die("签名自检失败，批准未写入")
    else:
        ap.write_bytes(raw)
        ap.with_suffix(".sig").unlink(missing_ok=True)
    audit("external-write-approve", key=key, approver=args.by,
          expires_in_minutes=args.minutes, signed=signers.is_file())
    ok(f"已写入人工预批准（{args.minutes} 分钟内有效，"
       f"{'签名' if signers.is_file() else '未配置签名/allowed_signers，兼容模式'}）: {ap}")


def cmd_security_status(args):
    required, signers, policy_error = _signature_policy()
    print(f"allowed_signers: {signers} ({'已配置' if signers.is_file() else '未配置'})")
    print(f"approval_dir: {APPROVAL_DIR}")
    if policy_error:
        print(f"模式: 严格签名（策略缺失，所有外发批准失败关闭）")
        print(f"错误: {policy_error}")
        sys.exit(1)
    print(f"模式: {'严格签名（required，执行方无法伪造批准）' if required else '兼容模式（同权进程可伪造批准）'}")


def cmd_memory(args):
    set_audit_context(rule="memory", input_hash=sha256_raw(Path(args.file)), require_audit=True)
    text = Path(args.file).read_text(encoding="utf-8", errors="replace")
    raw = sum(1 for line in text.splitlines() if any(p.search(line) for p in RAW_PATTERNS))
    if any(len(line) > 160 and re.search(r"\b(?:DEBUG|TRACE)\b", line, re.I)
           for line in text.splitlines()):
        raw += 2
    if re.search(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}", text) and \
            re.search(r"(?i)(?:Speaker\s*[A-Z0-9]+|说话人|发言人)\s*[:：]", text):
        raw += 2
    if raw >= 2:
        die(f"{args.file}: 疑似原始记录（{raw} 行时间戳/发言人），不得写入长期记忆")
    for p in SECRET_PATTERNS:
        if p.search(text):
            die(f"{args.file}: 疑似秘密/凭据，不得写入长期记忆")
    if args.require_provenance:
        fm, _ = split_frontmatter(text)
        if not fm:
            die(f"{args.file}: 长期记忆缺 frontmatter")
        if fm.get("provenance_status") not in PROVENANCE:
            die(f"{args.file}: provenance_status 非法或缺失")
        if not nonempty(fm.get("owner")):
            die(f"{args.file}: 长期记忆缺 owner")
        if not (nonempty(fm.get("source")) or nonempty(fm.get("source_record"))):
            die(f"{args.file}: 长期记忆缺 source/source_record")
        if not (nonempty(fm.get("scope")) or nonempty(fm.get("layer"))):
            die(f"{args.file}: 长期记忆缺 scope/layer")
    ok(f"memory 检查通过（{args.file}）")


def cmd_promotion(args):
    set_audit_context(rule="promotion", input_hash=sha256_raw(Path(args.file)), require_audit=True)
    try:
        d = json.load(open(args.file, encoding="utf-8"))
    except Exception as e:
        die(f"晋升记录解析失败: {e}")
    check_schema("promotion.schema.json", d, "promotion")
    sessions = d.get("session_ids") or []
    if len(sessions) != len(set(sessions)):
        die("session_ids 重复")
    if d.get("status") != "proposed":
        die(f"晋升记录 status={d.get('status')!r}，只接受 proposed 进入人工审批")
    base = Path(args.file).resolve().parent
    for ev in d.get("evidence") or []:
        path = _resolve(base, ev["path"])
        _check_file_hash(path, ev["sha256"], f"晋升证据 {ev['path']}")
    for mode in d.get("failure_modes") or []:
        if is_placeholder(mode):
            die("failure_modes 含空占位项")
    target = Path(d["target_path"])
    if target.is_absolute() or ".." in target.parts:
        die("target_path 必须是仓库内相对路径")
    scope = d.get("scope") or {}
    if scope.get("type") not in COMPONENT_TYPES:
        die(f"scope.type 非法: {scope.get('type')!r}")
    if Path(scope.get("path", "")).is_absolute() or ".." in Path(scope.get("path", "")).parts:
        die("scope.path 必须是仓库内相对路径")
    git = d.get("git") or {}
    repo = Path(git.get("repo", ""))
    if not repo.is_dir():
        die(f"git.repo 不存在: {repo}")
    try:
        head = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"],
                              capture_output=True, text=True, timeout=15).stdout.strip()
        status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"],
                                capture_output=True, text=True, timeout=15).stdout.strip()
    except Exception as e:
        die(f"git 检查失败: {e}")
    if not head.startswith(git.get("commit", "")):
        die(f"git.commit={git.get('commit')} 与当前 HEAD={head[:12]} 不一致")
    if status:
        die("git 工作树不干净，晋升检查要求 clean=true")
    if not (repo / scope["path"]).exists():
        die(f"scope.path 不存在: {scope['path']}")
    if not nonempty(d.get("owner")):
        die("晋升记录缺 owner")
    ok("晋升检查通过（仅检查字段/hash/证据/git/范围，不自动批准）")


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


def sha256_raw(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def cmd_install(args):
    set_audit_context(rule="install", input_hash=sha256_raw(Path(args.manifest)),
                      require_audit=True)
    try:
        m = json.load(open(args.manifest, encoding="utf-8"))
    except Exception as e:
        die(f"install manifest 解析失败: {e}")
    check_schema("install-manifest.schema.json", m, "install manifest")
    root = Path(m["target_root"]).resolve()
    backup_root = Path(m["backup_root"])
    seen = {}
    for c in m.get("components") or []:
        name = c.get("name")
        targets = c.get("targets") or []
        hashes = c.get("hashes") or {}
        actions = c.get("actions") or {}
        if len(targets) != len(set(targets)):
            die(f"install 组件 {name} 目标重复")
        if set(hashes) != set(targets):
            die(f"install 组件 {name} hashes 与 targets 不一一对应")
        if set(actions) != set(targets):
            die(f"install 组件 {name} actions 与 targets 不一一对应")
        if args.repo and not (Path(args.repo) / c["source"]).exists():
            die(f"install 组件 {name} source 不存在: {c['source']}")
        for rel in targets:
            p = Path(rel)
            if p.is_absolute() or ".." in p.parts:
                die(f"install 组件 {name} 目标路径非法: {rel}")
            if rel in seen:
                die(f"install 目标重复（{seen[rel]} / {name}）: {rel}")
            seen[rel] = name
            dst = root / rel
            if not dst.is_file():
                die(f"install 目标不存在: {dst}")
            actual = sha256_raw(dst)
            if actual != hashes.get(rel):
                die(f"install 目标内容与 manifest 不一致（被篡改或安装不完整）: {rel}")
            action = actions.get(rel)
            if action not in ("created", "replaced", "unchanged"):
                die(f"install 目标 {rel} action 非法: {action!r}")
            if action == "replaced" and not (backup_root / rel).is_file():
                die(f"install 目标 {rel} 标记 replaced 但缺备份: {backup_root / rel}")
            if c.get("status") == "test-only" and not rel.startswith("test-sandbox/"):
                die(f"test-only 组件 {name} 不得安装到生产载入点: {rel}")
    ok(f"install manifest 与实际文件/hash/唯一目标/范围一致"
       f"（{len(m.get('components') or [])} 个组件，{len(seen)} 个目标）")


def build_parser():
    ap = argparse.ArgumentParser(description="确定性门禁（失败关闭）")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("record")
    p.add_argument("--assets-repo", required=True)
    p.add_argument("--asset-id", required=True)
    p.add_argument("--require-distributable", action="store_true")
    p.set_defaults(func=cmd_record)

    p = sub.add_parser("asset-registry")
    p.add_argument("--assets-repo", required=True)
    p.add_argument("--require-distributable", action="store_true",
                   help="同时要求每条资产可新分发；默认只校验账册合法性")
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
    p.add_argument("--command")
    p.add_argument("--tool")
    p.add_argument("--input-json")
    p.add_argument("--by", required=True)
    p.add_argument("--minutes", type=int, default=30)
    p.set_defaults(func=cmd_approve)

    p = sub.add_parser("security-status")
    p.set_defaults(func=cmd_security_status)

    p = sub.add_parser("memory")
    p.add_argument("--file", required=True)
    p.add_argument("--require-provenance", action="store_true")
    p.set_defaults(func=cmd_memory)

    p = sub.add_parser("promotion")
    p.add_argument("--file", required=True)
    p.set_defaults(func=cmd_promotion)

    p = sub.add_parser("task-package")
    p.add_argument("--file", required=True)
    p.add_argument("--strict", action="store_true")
    p.add_argument("--tasks-dir")
    p.set_defaults(func=cmd_task_package)

    p = sub.add_parser("install")
    p.add_argument("--manifest", required=True)
    p.add_argument("--repo", help="源码仓库根，用于核对组件 source 路径")
    p.set_defaults(func=cmd_install)
    return ap


def main():
    args = build_parser().parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
