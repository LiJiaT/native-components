#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""asset-ai-ize（技能B）implementation package 确定性校验

用法:
    python -X utf8 validate_build.py <build-dir> --assets-repo <path> [--release]

两层校验：
  结构层（默认）：目录、manifest、record 身份、artifact 元数据、敏感信息、
                 原始记录、Hook 语法、tests 显式 FAIL 标记。
  发布层（--release）：额外要求 tests/results.json、review.json、
                 产物 hash、独立 reviewer、安装范围与 record 层级一致。

边界：脚本不裁决语义是否正确；语义保持仍由独立 reviewer 复核。发布层通过
表示"机器可判的交接条件齐全"，不等于内容已被业务验收。

exit 0 = 通过; exit 1 = 失败; exit 2 = 缺少依赖
"""
import sys, os, re, json, argparse, glob, hashlib, subprocess, shlex
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        try:
            _stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

try:
    import yaml
except ImportError:
    print("[FATAL] 需要 pyyaml: python -m pip install pyyaml")
    sys.exit(2)

DEFAULT_ASSETS_REPO = os.environ.get("ENG_ASSETS_REPO", r"D:\Project\eng-knowledge-assets")

AI_FORMS = {"Memory", "Rule", "Skill", "Workflow", "Hook", "Prompt"}
LAYERS = {"个人级", "项目级", "领域级", "公共级"}
PROVENANCE = {"verified", "source-excerpt", "synthetic"}
INSTALL_TARGETS = {"user-global", "user-domain", "project", "personal", "test-sandbox"}
RELEASE_CHANNELS = {"component-library", "personal", "test-only"}
MANIFEST_REQUIRED = [
    "schema_version", "package_version", "asset_id", "proposal_id", "ai_form",
    "asset_type", "layer", "projects", "domains", "owner", "provenance_status",
    "provenance_note", "install_target", "release_channel", "source_record",
    "source_record_sha256", "source_content_sha256", "artifacts", "tests",
    "producer", "generated_by", "review", "validation",
]
RECORD_REQUIRED = [
    "asset_id", "proposal_id", "title", "form", "secondary_tags", "domains",
    "layer", "ai_form", "source", "owner", "status", "approved_by",
    "approved_date", "provenance_status", "provenance_note",
]
RECORD_REQUIRED_NONEMPTY = [
    "asset_id", "proposal_id", "title", "form", "layer", "ai_form", "source",
    "owner", "approved_by", "approved_date", "provenance_status", "provenance_note",
]
PLACEHOLDERS = {"", "-", "--", "...", "…", "待填", "待定", "待补充", "todo", "tbd",
                "n/a", "na", "xxx", "<待填>"}

SENSITIVE_PATTERNS = [
    (re.compile(r"\b(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{16,}"), "GitHub 令牌", "fail"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "API key（sk-）", "fail"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS AK", "fail"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}"), "Bearer 令牌", "fail"),
    (re.compile(r"(?i)(password|passwd|pwd|api[_-]?key|secret|token)\s*[:=]\s*\S{6,}"),
     "密码/密钥赋值", "fail"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥", "fail"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"), "邮箱地址", "warn"),
]
RAW_LOG_PATTERNS = [
    re.compile(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+"
               r"(?:DEBUG|TRACE|INFO|WARN(?:ING)?|ERROR|FATAL)\b", re.I),
    re.compile(r"^\s*\[\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\]\s+"
               r"(?:DEBUG|TRACE|INFO|WARN(?:ING)?|ERROR)\b", re.I),
]
RAW_TRANSCRIPT_PATTERNS = [
    re.compile(r"^\s*(?:Speaker\s*[A-Z0-9]+|说话人\s*[A-Z0-9一二三四五六七八九十]+|"
               r"发言人\s*[A-Z0-9一二三四五六七八九十]+)\s*[:：]", re.I),
    re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s+(?:Speaker|说话人|发言人)", re.I),
]
TEXT_EXTS = {".md", ".yaml", ".yml", ".py", ".json", ".sh", ".txt", ".cmd", ".ps1", ".toml", ".ini", ".cfg"}
DOC_EXTS = {".md", ".yaml", ".yml"}
SECRET_NAME = re.compile(r"(?i)(password|passwd|pwd|token|secret|api[_-]?key|auth|credential)")


def split_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        return None, text
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}, ""


def norm_rel(p):
    p = str(p).replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def strip_prefix(p, prefix):
    return p[len(prefix):] if p.startswith(prefix) else p


def list_files(d):
    """包含隐藏文件；隐藏文件本身会在校验中单独拒绝，不能静默忽略。"""
    out = []
    for root, dirs, files in os.walk(d):
        dirs[:] = [x for x in dirs if x not in (".git", "__pycache__")]
        out += [os.path.join(root, f) for f in files]
    return out


def sha256_file(path):
    # Git checkout line endings differ by OS; hash canonical LF bytes.
    data = Path(path).read_bytes().replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def record_content_hash(fm, body):
    """对除 implementation 之外的全部 record 内容做稳定 hash。"""
    payload = {k: v for k, v in fm.items() if k != "implementation"}
    raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str) + "\n---\n" + body
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def is_placeholder(value):
    return value is None or str(value).strip().lower() in PLACEHOLDERS


def nonempty_text(value):
    return isinstance(value, str) and not is_placeholder(value)


def as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def scan_text(text):
    errors, warns = [], []
    raw = 0
    for line in text.splitlines():
        if any(p.search(line) for p in RAW_LOG_PATTERNS + RAW_TRANSCRIPT_PATTERNS):
            raw += 1
    if raw >= 2:
        errors.append(f"疑似原始日志/逐字稿（{raw} 行时间戳/发言人特征），应提炼后写入")
    for pat, label, severity in SENSITIVE_PATTERNS:
        if pat.search(text):
            (errors if severity == "fail" else warns).append(f"疑似{label}")
    return errors, warns


def check_python_syntax(path):
    try:
        src = open(path, encoding="utf-8", errors="replace").read()
        compile(src, path, "exec")
        return None
    except SyntaxError as e:
        return f"{e.msg} (line {e.lineno})"


def check_shell_syntax(path):
    try:
        r = subprocess.run(["bash", "-n", path], capture_output=True, text=True, timeout=20)
        return None if r.returncode == 0 else (r.stderr.strip() or "bash -n failed")
    except Exception as e:
        return str(e)


class Report:
    def __init__(self):
        self.fails, self.warns, self.checks = [], [], 0

    def ok(self, name):
        self.checks += 1
        print(f"  ✅ {name}")

    def fail(self, name, detail):
        self.checks += 1
        self.fails.append(f"{name}: {detail}")
        print(f"  ❌ {name}: {detail}")

    def warn(self, name, detail):
        self.checks += 1
        self.warns.append(f"{name}: {detail}")
        print(f"  ⚠️  {name}: {detail}")


def find_records(assets_repo, asset_id):
    hits = []
    for f in glob.glob(os.path.join(assets_repo, "assets", "**", "*.md"), recursive=True):
        try:
            fm, body = split_frontmatter(open(f, encoding="utf-8").read())
        except Exception:
            continue
        if fm and fm.get("asset_id") == asset_id:
            hits.append((f, fm, body))
    return hits


def check_record(r, assets_repo, manifest, need_ai_form=True):
    asset_id = manifest.get("asset_id", "")
    if not os.path.isdir(assets_repo):
        r.fail("B3", f"资产 repo 路径不存在: {assets_repo}（用 --assets-repo 指定）")
        return None
    hits = find_records(assets_repo, asset_id)
    if not hits:
        r.fail("B3", f"资产 repo 中找不到 asset_id={asset_id} 的 record")
        return None
    if len(hits) > 1:
        r.fail("B3", f"asset_id={asset_id} 在资产 repo 中出现 {len(hits)} 次（必须唯一）")
        return None
    rf, rfm, body = hits[0]
    rel = norm_rel(os.path.relpath(rf, assets_repo))
    if rfm.get("status") != "approved":
        r.fail("B3", f"record {asset_id} status={rfm.get('status')}，仅可消费 approved")
        return None
    missing = [k for k in RECORD_REQUIRED if k not in rfm]
    empty = [k for k in RECORD_REQUIRED_NONEMPTY if not nonempty_text(rfm.get(k))]
    if missing or empty:
        r.fail("B3", f"record 字段不完整: 缺 {missing}，空/占位 {empty}")
        return None
    if not re.fullmatch(r"EA-\d{8}-\d{2,}", str(rfm.get("asset_id"))):
        r.fail("B3", f"asset_id 格式非法: {rfm.get('asset_id')}")
    if rfm.get("provenance_status") not in PROVENANCE:
        r.fail("B3", f"provenance_status 非法: {rfm.get('provenance_status')}")
    if rfm.get("layer") not in LAYERS:
        r.fail("B3", f"record layer 非法: {rfm.get('layer')}")
    if not isinstance(rfm.get("domains"), list):
        r.fail("B3", "record domains 必须是列表")
    if not as_list(rfm.get("projects", rfm.get("project"))):
        # project=无 是合法的，用空列表表达
        pass
    if rfm.get("proposal_id") != manifest.get("proposal_id"):
        r.fail("B3", f"proposal_id 不一致: record={rfm.get('proposal_id')} "
                     f"manifest={manifest.get('proposal_id')}")
        return None
    if need_ai_form and rfm.get("ai_form") != manifest.get("ai_form"):
        r.fail("B3", f"ai_form 不一致: record={rfm.get('ai_form')} "
                     f"manifest={manifest.get('ai_form')}（B 不得改映射）")
        return None
    if rfm.get("layer") != manifest.get("layer"):
        r.fail("B3", f"layer 不一致: record={rfm.get('layer')} manifest={manifest.get('layer')}")
    rec_projects = [x for x in as_list(rfm.get("projects", rfm.get("project"))) if x != "无"]
    man_projects = [x for x in as_list(manifest.get("projects")) if x != "无"]
    if sorted(rec_projects) != sorted(man_projects):
        r.fail("B3", f"projects 不一致: record={rec_projects} manifest={man_projects}")
    if sorted(as_list(rfm.get("domains"))) != sorted(as_list(manifest.get("domains"))):
        r.fail("B3", f"domains 不一致: record={rfm.get('domains')} manifest={manifest.get('domains')}")
    if rfm.get("owner") != manifest.get("owner"):
        r.fail("B3", f"owner 不一致: record={rfm.get('owner')} manifest={manifest.get('owner')}（B 不得扩大批准范围）")
    if rfm.get("provenance_status") != manifest.get("provenance_status"):
        r.fail("B3", "provenance_status 与 record 不一致")
    if rfm.get("provenance_note") != manifest.get("provenance_note"):
        r.fail("B3", "provenance_note 与 record 不一致")

    # 来源指针必须存在、位于资产 repo 内、且 asset_id 对得上
    src = manifest.get("source_record")
    if not nonempty_text(src):
        r.fail("B3", "manifest.source_record 为空")
    else:
        # source_record 相对资产 repo 根；也接受绝对路径，但必须仍在 repo 内
        src_abs = os.path.normpath(src if os.path.isabs(src) else os.path.join(assets_repo, src))
        if not os.path.isfile(src_abs):
            r.fail("B3", f"source_record 不存在: {src}")
        else:
            try:
                common = os.path.commonpath([os.path.abspath(src_abs), os.path.abspath(assets_repo)])
            except ValueError:
                common = ""
            if common != os.path.abspath(assets_repo):
                r.fail("B3", f"source_record 不在资产 repo 内: {src}")
            if norm_rel(os.path.relpath(src_abs, assets_repo)) != rel:
                r.fail("B3", f"source_record 指向 {rel} 之外的文件: {src}")
            if manifest.get("source_record_sha256") != sha256_file(src_abs):
                r.fail("B3", "source_record_sha256 与当前 record 文件不一致（record 已被修改或 hash 未更新）")
            if manifest.get("source_content_sha256") != record_content_hash(rfm, body):
                r.fail("B3", "source_content_sha256 与 record 不可变正文不一致（statement/evidence/mapping 被修改）")
    r.ok(f"B3 record 完整性（{asset_id} approved，字段/范围/来源/hash 一致）")
    return rfm


def check_scope(r, manifest, rfm):
    layer = rfm.get("layer")
    target = manifest.get("install_target")
    channel = manifest.get("release_channel")
    if target not in INSTALL_TARGETS:
        r.fail("B8", f"install_target 非法: {target}（合法: {sorted(INSTALL_TARGETS)}）")
        return
    if channel not in RELEASE_CHANNELS:
        r.fail("B8", f"release_channel 非法: {channel}（合法: {sorted(RELEASE_CHANNELS)}）")
        return
    if manifest.get("provenance_status") == "synthetic":
        if target != "test-sandbox" or channel != "test-only":
            r.fail("B8", "synthetic 资产只能用于 test-sandbox / test-only，"
                         "不得进入生产安装或组件库发布")
        return
    allowed = {
        "个人级": ({"personal"}, {"personal"}),
        "项目级": ({"project"}, {"component-library"}),
        "领域级": ({"user-domain", "project"}, {"component-library"}),
        "公共级": ({"user-global"}, {"component-library"}),
    }
    targets, channels = allowed[layer]
    if target not in targets:
        r.fail("B8", f"层级={layer} 不允许 install_target={target}（允许: {sorted(targets)}）")
    if channel not in channels:
        r.fail("B8", f"层级={layer} 不允许 release_channel={channel}（允许: {sorted(channels)}）")
    if layer == "个人级" and channel == "component-library":
        r.fail("B8", "个人级资产不得进入公共组件库")


def validate(bdir, assets_repo, release=False):
    r = Report()
    print(f"[validate_build] build 目录: {bdir}")
    print(f"[validate_build] 资产 repo: {assets_repo}")
    print(f"[validate_build] 模式: {'release' if release else 'structure'}")

    mpath = os.path.join(bdir, "build-manifest.json")
    if not os.path.isfile(mpath):
        r.fail("B1", "缺少 build-manifest.json"); return r
    try:
        manifest = json.load(open(mpath, encoding="utf-8"))
    except Exception as e:
        r.fail("B2", f"build-manifest.json 解析失败: {e}"); return r
    manifest["__dir__"] = bdir
    mtype = manifest.get("type", "implementation")
    if mtype not in ("implementation", "mapping_issue"):
        r.fail("B2", f"type 非法: {mtype}")
        return r

    missing = [k for k in MANIFEST_REQUIRED if k not in manifest]
    if missing:
        r.fail("B2", f"manifest 缺必填字段: {missing}")
    if manifest.get("schema_version") != "2":
        r.fail("B2", f"schema_version 必须为 '2'，实际 {manifest.get('schema_version')!r}")
    if not re.fullmatch(r"\d+\.\d+\.\d+", str(manifest.get("package_version", ""))):
        r.fail("B2", f"package_version 必须是 x.y.z，实际 {manifest.get('package_version')!r}")
    if not nonempty_text(manifest.get("producer")):
        r.fail("B2", "manifest.producer 为空（必须写明生产者/责任团队）")
    if not nonempty_text(manifest.get("generated_by")):
        r.fail("B2", "manifest.generated_by 为空（script/model/manual 及版本）")

    if mtype == "mapping_issue":
        mi = os.path.join(bdir, "mapping-issue.md")
        if not os.path.isfile(mi):
            r.fail("B1", "mapping_issue 分支缺 mapping-issue.md"); return r
        text = open(mi, encoding="utf-8").read()
        missing = [k for k in ("不可行原因", "影响", "建议动作") if k not in text]
        if missing:
            r.fail("B1", f"mapping-issue.md 缺要素: {missing}")
        else:
            r.ok("B1 mapping-issue 结构（原因/影响/建议动作）")
        check_record(r, assets_repo, manifest, need_ai_form=True)
        return r

    # B1 结构
    ipath = os.path.join(bdir, "implementation.md")
    adir = os.path.join(bdir, "artifacts")
    tdir = os.path.join(bdir, "tests")
    inst = os.path.join(bdir, "install.md")
    review = os.path.join(bdir, "review.md")
    for p, label, kind in [(ipath, "implementation.md", "file"),
                           (adir, "artifacts/", "dir"),
                           (tdir, "tests/", "dir"),
                           (inst, "install.md", "file"),
                           (review, "review.md", "file")]:
        if kind == "file" and not os.path.isfile(p):
            r.fail("B1", f"缺少 {label}")
        elif kind == "dir" and not os.path.isdir(p):
            r.fail("B1", f"缺少 {label}")
    if any(x.startswith("B1") for x in r.fails):
        return r
    for p, label in [(ipath, "implementation.md"), (inst, "install.md"), (review, "review.md")]:
        if os.path.getsize(p) < 80:
            r.fail("B1", f"{label} 内容过短（<80 bytes），疑似空壳")
    afiles = list_files(adir)
    tfiles = list_files(tdir)
    if not afiles:
        r.fail("B1", "artifacts/ 下没有任何文件"); return r
    if not tfiles:
        r.fail("B1", "tests/ 下没有任何文件（验收测试不得为空）"); return r
    r.ok(f"B1 目录结构（artifacts={len(afiles)}, tests={len(tfiles)}）")

    # B2 manifest 对账（含隐藏文件）
    declared_a = [strip_prefix(norm_rel(a), "artifacts/") for a in as_list(manifest.get("artifacts"))]
    actual_a = [norm_rel(os.path.relpath(f, adir)) for f in afiles]
    if sorted(declared_a) != sorted(actual_a):
        r.fail("B2", f"manifest.artifacts 与 artifacts/ 不一致: {sorted(declared_a)} vs {sorted(actual_a)}")
    declared_t = [strip_prefix(norm_rel(t), "tests/") for t in as_list(manifest.get("tests"))]
    actual_t = [norm_rel(os.path.relpath(f, tdir)) for f in tfiles]
    if sorted(declared_t) != sorted(actual_t):
        r.fail("B2", f"manifest.tests 与 tests/ 不一致: {sorted(declared_t)} vs {sorted(actual_t)}")
    for f in afiles:
        rel = norm_rel(os.path.relpath(f, adir))
        if os.path.basename(f).startswith("."):
            r.fail("B2", f"artifacts 含隐藏文件 {rel}：隐藏文件不得绕过清单与扫描")
        if "__pycache__" in rel or rel.endswith(".pyc"):
            r.fail("B2", f"artifacts 含运行产物 {rel}")
    if not any(x.startswith("B2") for x in r.fails):
        r.ok(f"B2 manifest 字段与对账（artifacts={len(actual_a)}, tests={len(actual_t)}）")

    # B3/B8 record 与范围
    rfm = check_record(r, assets_repo, manifest)
    if rfm:
        check_scope(r, manifest, rfm)

    # B4/B6/B7/B9 artifact 检查
    asset_id = manifest.get("asset_id", "")
    prov = manifest.get("provenance_status")
    expected_channel = manifest.get("release_channel")
    for f in afiles:
        rel = norm_rel(os.path.relpath(f, adir))
        ext = os.path.splitext(f)[1].lower()
        text = open(f, encoding="utf-8", errors="replace").read() if ext in TEXT_EXTS else ""
        if ext in DOC_EXTS:
            fm, _ = split_frontmatter(text)
            if fm is None or "__parse_error__" in fm:
                r.fail("B4", f"{rel} frontmatter 缺失或 YAML 解析失败（不再降级为警告）")
            else:
                for key in ("asset_id", "provenance_status", "provenance_note", "release_channel"):
                    if key not in fm:
                        r.fail("B4", f"{rel} frontmatter 缺 {key}")
                if fm.get("asset_id") != asset_id:
                    r.fail("B4", f"{rel} frontmatter asset_id={fm.get('asset_id')!r}，应为 {asset_id}")
                if fm.get("provenance_status") != prov:
                    r.fail("B4", f"{rel} provenance_status={fm.get('provenance_status')!r}，"
                                 f"record/manifest 为 {prov!r}")
                if fm.get("release_channel") != expected_channel:
                    r.fail("B4", f"{rel} release_channel={fm.get('release_channel')!r}，"
                                 f"manifest 为 {expected_channel!r}")
        elif ext == ".py":
            m = re.search(r"^#\s*asset_id:\s*(\S+)", text, re.M)
            if not m:
                r.fail("B4", f"{rel} 缺 `# asset_id: {asset_id}` 文件头注释")
            elif m.group(1) != asset_id:
                r.fail("B4", f"{rel} 文件头 asset_id={m.group(1)!r}，应为 {asset_id}")
            err = check_python_syntax(f)
            if err:
                r.fail("B9", f"{rel} Python 语法错误: {err}")
        elif ext == ".sh":
            m = re.search(r"^#\s*asset_id:\s*(\S+)", text, re.M)
            if not m:
                r.fail("B4", f"{rel} 缺 `# asset_id: {asset_id}` 文件头注释")
            err = check_shell_syntax(f)
            if err:
                r.fail("B9", f"{rel} shell 语法错误: {err}")
        if ext in TEXT_EXTS:
            errors, warns = scan_text(text)
            for e in errors:
                r.fail("B6/B7", f"{rel} {e}")
            for w in warns:
                r.warn("B6", f"{rel} {w}")
    if not any(x.startswith(("B4", "B6", "B7", "B9")) for x in r.fails):
        r.ok("B4/B6/B7/B9 artifact 元数据 / 敏感信息 / 原始记录 / 语法检查")

    # B5 语义保持
    itext = open(ipath, encoding="utf-8").read()
    if "语义保持" not in itext:
        r.fail("B5", "implementation.md 缺『语义保持』对照节")
    elif "对照" not in itext:
        r.warn("B5", "implementation.md 语义保持节建议为对照表（statement 结论 → 承载位置）")
    else:
        r.ok("B5 语义保持对照节")

    # B10 tests 显式失败标记（结构层即可判定）
    for f in tfiles:
        if os.path.splitext(f)[1].lower() not in TEXT_EXTS:
            continue
        text = open(f, encoding="utf-8", errors="replace").read()
        if re.search(r"(?im)^\s*(?:[-*]\s*)?(?:FAIL|FAILED)\s*[:：]", text):
            r.fail("B10", f"{norm_rel(os.path.relpath(f, tdir))} 含显式 FAIL 记录；"
                          "测试未通过不得声明实现完成")

    # B11 发布层证据
    if release:
        check_release_evidence(r, bdir, manifest, afiles, adir, rfm)
    else:
        if not os.path.isfile(os.path.join(tdir, "results.json")):
            r.warn("B11", "tests/results.json 缺失；结构层可过，发布层（--release）将失败")
    return r


def check_release_evidence(r, bdir, manifest, afiles, adir, rfm):
    if rfm is None:
        return
    # tests/results.json
    rp = os.path.join(bdir, "tests", "results.json")
    if not os.path.isfile(rp):
        r.fail("B11", "发布层缺 tests/results.json（机器可核验的测试结果）")
    else:
        try:
            res = json.load(open(rp, encoding="utf-8"))
        except Exception as e:
            r.fail("B11", f"tests/results.json 解析失败: {e}")
            res = {}
        if res.get("result") != "pass":
            r.fail("B11", f"tests/results.json result={res.get('result')!r}，发布要求 pass")
        cmds = res.get("commands")
        if not isinstance(cmds, list) or not cmds:
            r.fail("B11", "tests/results.json 缺 commands（命令、exit_code 逐项记录）")
        else:
            bad = [c for c in cmds if not isinstance(c, dict) or c.get("exit_code") != 0]
            if bad:
                r.fail("B11", f"tests/results.json 存在非零 exit_code 命令: {bad}")
        if not nonempty_text(res.get("tested_at")) or not nonempty_text(res.get("tested_by")):
            r.fail("B11", "tests/results.json 缺 tested_at/tested_by")
        actual_hashes = {norm_rel(os.path.relpath(f, adir)): sha256_file(f) for f in afiles}
        if res.get("artifact_sha256") != actual_hashes:
            r.fail("B11", "tests/results.json artifact_sha256 与当前 artifacts 不一致（测试对象已变）")

    # review.json：独立复核身份与逐项结论
    rv = os.path.join(bdir, "review.json")
    if not os.path.isfile(rv):
        r.fail("B11", "发布层缺 review.json（独立复核记录）")
    else:
        try:
            rev = json.load(open(rv, encoding="utf-8"))
        except Exception as e:
            r.fail("B11", f"review.json 解析失败: {e}")
            rev = {}
        for key in ("reviewer", "executor", "decision", "reviewed_at", "checklist"):
            if key not in rev:
                r.fail("B11", f"review.json 缺 {key}")
        if rev.get("decision") != "approved":
            r.fail("B11", f"review.json decision={rev.get('decision')!r}，发布要求 approved")
        if rev.get("reviewer") and rev.get("reviewer") == rev.get("executor"):
            r.fail("B11", "reviewer 与 executor 相同：独立复核不得由执行者自审")
        if rev.get("independent") is not True:
            r.fail("B11", "review.json 必须显式 independent: true")
        checklist = rev.get("checklist")
        if not isinstance(checklist, list) or not checklist:
            r.fail("B11", "review.json checklist 为空")
        else:
            bad = [x for x in checklist if not isinstance(x, dict) or x.get("result") != "pass"]
            if bad:
                r.fail("B11", f"review.json 存在未通过/缺结果的检查项: {bad}")
        if rev.get("artifact_sha256") != {norm_rel(os.path.relpath(f, adir)): sha256_file(f) for f in afiles}:
            r.fail("B11", "review.json artifact_sha256 与当前 artifacts 不一致")

    # install.md 必须写明范围与回滚
    itext = open(os.path.join(bdir, "install.md"), encoding="utf-8").read()
    if manifest.get("install_target") not in itext:
        r.fail("B11", f"install.md 未写明 install_target={manifest.get('install_target')}")
    if "回滚" not in itext:
        r.fail("B11", "install.md 缺回滚步骤")
    if not any(x.startswith("B11") for x in r.fails):
        r.ok("B11 发布证据（tests/results.json / review.json / install 范围与回滚）")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build_dir")
    ap.add_argument("--assets-repo", default=DEFAULT_ASSETS_REPO,
                    help="资产 repo 本地 clone 路径（默认 %(default)s）")
    ap.add_argument("--release", action="store_true",
                    help="发布层校验：要求测试结果、独立复核、产物 hash 与范围绑定")
    args = ap.parse_args()
    r = validate(args.build_dir, args.assets_repo, release=args.release)
    print(f"\n[validate_build] 检查 {r.checks} 项: 通过 {r.checks - len(r.fails) - len(r.warns)} / "
          f"失败 {len(r.fails)} / 警告 {len(r.warns)}")
    if r.fails:
        print("[validate_build] ❌ 校验未通过，按 R6 不得生成实现申请")
        sys.exit(1)
    print("[validate_build] ✅ 校验通过" + ("（发布层）" if args.release else "（结构层）"))
    sys.exit(0)


if __name__ == "__main__":
    main()
