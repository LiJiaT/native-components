#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""assetize（技能A）proposal package 确定性校验

用法:
    python -X utf8 validate.py <proposal-dir> [--strict]

设计原则：脚本只裁决可确定性判定的部分（结构、类型、枚举、非空、占位符、
来源指针、原始记录/敏感信息模式），语义有效性仍由 owner 评审。脚本通过
不等于内容正确，只表示"没有已知的机器可判缺陷"。

exit 0 = 全部通过; exit 1 = 有失败项（--strict 时警告也失败）
exit 2 = 缺少 pyyaml 等运行依赖
"""
import sys, os, re, json, argparse
from datetime import datetime

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

FORMS = {"知识库", "工程规则", "决策记忆", "技能工作流"}
DOMAINS = {"架构", "设计", "验证", "时序", "DFT", "后仿", "Firmware", "模拟", "后端"}
PROJECTS = {"LPDDR6", "HBM"}
LAYERS = {"个人级", "项目级", "领域级", "公共级"}
AI_FORMS = {"Memory", "Rule", "Skill", "Workflow", "Hook", "Prompt"}
MAPPING_STATUS = {"mapped", "unmapped", "deferred"}
PROVENANCE = {"verified", "source-excerpt", "synthetic"}
REQUIRED_FIELDS = ["id", "title", "form", "secondary_tags", "domains",
                   "layer", "ai_form", "source", "suggested_owner"]
PROPOSAL_SECTIONS = ["资产清单", "已过滤区|已过滤|过滤区", "入库申请", "审批区"]
INTAKE_REQUIRED = ["资产 ID", "来源提案", "层级", "领域", "项目", "owner",
                   "变更内容", "验收清单", "回滚"]
PLACEHOLDERS = {"", "-", "--", "...", "…", "待填", "待定", "待补充", "待确认",
                "todo", "tbd", "n/a", "na", "xxx", "示例", "<待填>"}

SECRET_PATTERNS = [
    (re.compile(r"\b(ghp|gho|ghs|github_pat)_[A-Za-z0-9_]{16,}"), "GitHub 令牌"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{16,}"), "API key（sk-）"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS AK"),
    (re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._\-]{20,}"), "Bearer 令牌"),
    (re.compile(r"(?i)(password|passwd|pwd|api[_-]?key|secret|token)\s*[:=]\s*\S{6,}"),
     "密码/密钥赋值"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "私钥"),
]
EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")

RAW_LOG_PATTERNS = [
    re.compile(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+"
               r"(?:DEBUG|TRACE|INFO|WARN(?:ING)?|ERROR|FATAL)\b", re.I),
    re.compile(r"^\s*\[\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\]\s+"
               r"(?:DEBUG|TRACE|INFO|WARN(?:ING)?|ERROR)\b", re.I),
    re.compile(r"^\s*(?:DEBUG|TRACE|INFO|WARN(?:ING)?|ERROR|FATAL)\s+"
               r"\d{4}-\d{2}-\d{2}", re.I),
]
RAW_TRANSCRIPT_PATTERNS = [
    re.compile(r"^\s*(?:Speaker\s*[A-Z0-9]+|说话人\s*[A-Z0-9一二三四五六七八九十]+|"
               r"发言人\s*[A-Z0-9一二三四五六七八九十]+)\s*[:：]", re.I),
    re.compile(r"^\s*\d{1,2}:\d{2}(?::\d{2})?\s+(?:Speaker|说话人|发言人)", re.I),
    re.compile(r"^\s*\[(?:上午|下午)?\s*\d{1,2}:\d{2}(?::\d{2})?\]\s*", re.I),
    # 旧格式：完整日期时间前缀 + Speaker/说话人
    re.compile(r"^\s*\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}:\d{2}(?:[.,]\d+)?\s+"
               r"(?:Speaker|说话人|发言人)\b", re.I),
]


def split_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        return None, text
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}, ""


def extract_section(text, heading):
    """取 `## <heading>` 到下一个同级/更高级标题之间的正文；heading 可含 | 别名。"""
    m = re.search(rf"^##+\s*(?:{heading})\b.*$", text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    n = re.search(r"^##+\s", rest, re.M)
    return rest[:n.start()] if n else rest


def extract_label_value(text, label):
    """取 `**label**：value` 或 `- label：value`；冒号后为空时取后续第一个非空块。"""
    m = re.search(rf"(?m)^[^\n]*{re.escape(label)}[^\n]*?[:：]\s*(.*)$", text)
    if not m:
        m = re.search(rf"(?m)^[^\n]*{re.escape(label)}[^\n]*\*\*\s*$", text)
        if not m:
            return None
        rest = text[m.end():]
    else:
        rest = m.group(1) + "\n" + text[m.end():]
    lines = rest.splitlines()
    collected = []
    for line in lines:
        s = line.strip()
        if not s:
            if collected:
                break
            continue
        if re.match(r"^\*\*[^*]+\*\*\s*[:：]?$", s) or re.match(r"^##", s):
            break
        collected.append(s)
        if len(collected) >= 8:
            break
    return "\n".join(collected).strip() or None


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


def is_placeholder(value):
    if value is None:
        return True
    text = str(value).strip()
    if text.lower() in PLACEHOLDERS:
        return True
    if re.fullmatch(r"<[^>]*>", text):
        return True
    if re.fullmatch(r"[（(]\s*待[^）)]*[）)]", text):
        return True
    return False


def require_text(value, field, r, name, min_len=1):
    if is_placeholder(value):
        r.fail("V2", f"{name} {field} 为空或占位符")
        return False
    if not isinstance(value, str):
        r.fail("V2", f"{name} {field} 必须是字符串，实际 {type(value).__name__}")
        return False
    if len(value.strip()) < min_len:
        r.fail("V2", f"{name} {field} 过短（{len(value.strip())} < {min_len}）")
        return False
    return True


def normalize_projects(fm):
    """返回 (projects, error)。projects 必须是列表；project 可单值或列表。"""
    if "projects" in fm and not isinstance(fm.get("projects"), list):
        return [], "projects 必须是列表（单项目请用 project 或单元素列表）"
    raw = fm.get("projects") if fm.get("projects") not in (None, "") else fm.get("project")
    if raw is None:
        return [], "缺 project/projects"
    vals = as_list(raw)
    if not vals:
        return [], "project/projects 为空"
    out = []
    for v in vals:
        if not isinstance(v, str):
            return [], f"project 元素必须是字符串，实际 {type(v).__name__}"
        v = v.strip()
        if v == "无":
            continue
        if v not in PROJECTS:
            return [], f"project 非法: {v}（合法: {sorted(PROJECTS)} 或 无）"
        out.append(v)
    if len(out) != len(set(out)):
        return [], f"project 重复: {out}"
    if "无" in [str(x).strip() for x in vals] and len(vals) > 1:
        return [], "project 取值为『无』时不能同时列其他项目"
    return out, None


def scan_body(body):
    """返回 (errors, warnings)。只做确定性模式检查，不做语义裁决。"""
    errors, warns = [], []
    raw_hits = 0
    for line in body.splitlines():
        log_hit = any(p.search(line) for p in RAW_LOG_PATTERNS)
        if log_hit:
            raw_hits += 1
            # 单行超长 DEBUG 也是原始日志；不能因为只有一行就放行
            if len(line.strip()) > 160:
                raw_hits += 1
        if any(p.search(line) for p in RAW_TRANSCRIPT_PATTERNS):
            raw_hits += 1
    if raw_hits >= 2:
        errors.append(f"检测到 {raw_hits} 处原始日志/逐字稿特征（时间戳+级别/长单行或发言人），"
                      "请提炼为结论后再入库")
    for pat, label in SECRET_PATTERNS:
        if pat.search(body):
            errors.append(f"疑似含敏感信息（{label}）")
    if EMAIL_RE.search(body):
        warns.append("疑似含邮箱地址，确认非个人敏感信息")
    return errors, warns


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


def validate(pdir):
    r = Report()
    print(f"[validate] proposal 目录: {pdir}")

    # V1 结构
    ppath = os.path.join(pdir, "proposal.md")
    adir = os.path.join(pdir, "assets")
    mpath = os.path.join(pdir, "manifest.json")
    if not os.path.isfile(ppath):
        r.fail("V1", "缺少 proposal.md"); return r
    if not os.path.isdir(adir):
        r.fail("V1", "缺少 assets/ 目录"); return r
    if not os.path.isfile(mpath):
        r.fail("V1", "缺少 manifest.json"); return r
    afiles = sorted(f for f in os.listdir(adir) if f.endswith(".md"))
    if not afiles:
        r.fail("V1", "assets/ 下没有任何 .md（全过滤时应输出空 proposal 说明）"); return r
    r.ok(f"V1 目录结构（assets={len(afiles)}）")

    # V2/V3 资产文件
    assets = {}
    for f in afiles:
        fm, body = split_frontmatter(open(os.path.join(adir, f), encoding="utf-8").read())
        name = f"assets/{f}"
        if fm is None or "__parse_error__" in fm:
            r.fail("V2", f"{name} frontmatter 缺失或 YAML 解析失败"); continue
        missing = [k for k in REQUIRED_FIELDS if k not in fm]
        if "project" not in fm and "projects" not in fm:
            missing.append("project/projects")
        if missing:
            r.fail("V2", f"{name} 缺必填字段: {missing}"); continue

        # 非空 / 类型 / 占位符
        field_ok = True
        field_ok &= require_text(fm.get("id"), "id", r, name, 2)
        field_ok &= require_text(fm.get("title"), "title", r, name, 4)
        field_ok &= require_text(fm.get("source"), "source", r, name, 4)
        field_ok &= require_text(fm.get("suggested_owner"), "suggested_owner", r, name, 2)
        if not isinstance(fm.get("secondary_tags"), list):
            r.fail("V2", f"{name} secondary_tags 必须是列表"); field_ok = False
        if fm.get("layer") not in LAYERS:
            r.fail("V2", f"{name} layer 非法: {fm.get('layer')}"); field_ok = False
        if fm.get("form") not in FORMS and fm.get("form") != "上下文":
            r.fail("V2", f"{name} form 非法: {fm.get('form')}"); field_ok = False
        if len(str(fm.get("title", ""))) > 80:
            r.fail("V2", f"{name} title 超过 80 字"); field_ok = False
        if not field_ok:
            continue

        # V3 枚举与组合
        if fm["form"] == "上下文":
            r.fail("V3", f"{name} form=上下文——此类单元不成案，应进 proposal 的已过滤区")
        for t in as_list(fm.get("secondary_tags")):
            if t == "上下文":
                r.fail("V3", f"{name} 副标签含上下文——上下文不成案，应进已过滤区")
            elif t not in FORMS:
                r.fail("V3", f"{name} 副标签非法: {t}")
        if not isinstance(fm.get("domains"), list):
            r.fail("V3", f"{name} domains 必须是列表")
        domains = as_list(fm.get("domains"))
        if len(domains) > 3:
            r.fail("V3", f"{name} 领域多选超过 3 个")
        for d in domains:
            if d not in DOMAINS:
                r.fail("V3", f"{name} 领域非法: {d}（合法: {sorted(DOMAINS)}）")
        if not domains and fm["layer"] != "公共级":
            r.fail("V3", f"{name} domains 为空但 layer={fm['layer']}——仅公共级资产可不标领域")

        projects, perr = normalize_projects(fm)
        if perr:
            r.fail("V3", f"{name} {perr}")
        if fm["layer"] == "项目级" and len(projects) != 1:
            r.fail("V3", f"{name} 层级=项目级 必须且只能有一个具体项目，实际 {projects}")
        if fm["layer"] in ("个人级",) and projects:
            r.fail("V3", f"{name} 层级=个人级 不应绑定项目")
        if len(projects) > 1 and fm["layer"] not in ("领域级", "公共级"):
            r.fail("V3", f"{name} 多项目资产（{projects}）只能标领域级或公共级")

        ai_form = fm.get("ai_form")
        mapping_status = fm.get("mapping_status", "mapped")
        if mapping_status not in MAPPING_STATUS:
            r.fail("V3", f"{name} mapping_status 非法: {mapping_status}")
        if ai_form is None:
            if mapping_status not in ("unmapped", "deferred"):
                r.fail("V3", f"{name} ai_form 为空时必须声明 mapping_status=unmapped|deferred")
            if is_placeholder(fm.get("mapping_reason")):
                r.fail("V3", f"{name} ai_form 未映射时必须给出非空 mapping_reason")
        else:
            if ai_form not in AI_FORMS:
                r.fail("V3", f"{name} ai_form 非法: {ai_form}（合法: {sorted(AI_FORMS)}）")
            if mapping_status != "mapped":
                r.fail("V3", f"{name} 声明了 ai_form 时 mapping_status 必须为 mapped")

        if fm.get("provenance_status") is not None and fm.get("provenance_status") not in PROVENANCE:
            r.fail("V3", f"{name} provenance_status 非法（proposal 阶段可留空）")

        # V7 正文长度 / 原始记录 / 敏感信息
        body_clean = re.sub(r"\s", "", body)
        if len(body_clean) < 40:
            r.fail("V7", f"{name} 正文过短（{len(body_clean)} 字），疑似未提炼或空壳")
        body_errors, body_warns = scan_body(body)
        for e in body_errors:
            r.fail("V7", f"{name} {e}")
        for w in body_warns:
            r.warn("V7", f"{name} {w}")
        if len(body_clean) >= 40 and not body_errors:
            r.ok(f"V7 {name} 正文长度 / 原始记录 / 敏感信息检查（{len(body_clean)} 字）")

        # V8 决策记忆五要素（失败而非警告）
        if fm["form"] == "决策记忆":
            missing_dec = [k for k in ("背景", "选项", "取舍", "证据", "日期") if k not in body]
            has_date = re.search(r"\b20\d{2}[-/年]\d{1,2}([-/月]\d{1,2})?", body)
            if missing_dec or not has_date:
                r.fail("V8", f"{name} 决策记忆缺要素: {missing_dec or []}"
                             f"{'（未找到日期）' if not has_date else ''}")
            else:
                r.ok(f"V8 {name} 决策记忆五要素")

        assets[fm["id"]] = {"file": f, "fm": fm, "projects": projects}
    if assets and not any(x.startswith(("V2", "V3", "V7", "V8")) for x in r.fails):
        r.ok(f"V2/V3/V7/V8 资产字段、枚举与正文（{len(assets)} 个资产）")

    # V4 manifest 对账
    try:
        manifest = json.load(open(mpath, encoding="utf-8"))
        m_assets = manifest.get("assets", [])
        if not isinstance(m_assets, list):
            r.fail("V4", "manifest.assets 必须是列表")
            m_assets = []
        m_ids = [a.get("id") for a in m_assets if isinstance(a, dict)]
        if sorted(m_ids) != sorted(assets.keys()):
            r.fail("V4", f"manifest 资产清单与 assets/ 不一致: "
                         f"manifest={sorted(m_ids)} 实际={sorted(assets.keys())}")
        else:
            mismatch = []
            for a in m_assets:
                fm = assets.get(a.get("id"), {}).get("fm") if isinstance(a, dict) else None
                if not fm:
                    continue
                for key in ("title", "form", "ai_form", "layer", "domains",
                            "project", "suggested_owner"):
                    if key == "project":
                        left = a.get("projects", a.get("project"))
                        left_norm = [x for x in as_list(left) if x != "无"]
                        right = normalize_projects(fm)[0]
                        if left_norm != right:
                            mismatch.append(f"{a.get('id')}.{key}")
                    elif a.get(key) != fm.get(key):
                        mismatch.append(f"{a.get('id')}.{key}")
            if mismatch:
                r.fail("V4", f"manifest 与资产 frontmatter 不一致: {mismatch}")
            else:
                r.ok(f"V4 manifest 对账（{len(m_ids)} 资产，字段一致）")
        for key in ("proposal_id", "date", "source_material"):
            if is_placeholder(manifest.get(key)):
                r.fail("V4", f"manifest 缺 {key} 或值为占位符")
        proposal_id = manifest.get("proposal_id")
        dirname = os.path.basename(os.path.normpath(os.path.abspath(pdir)))
        if proposal_id and dirname != proposal_id:
            r.warn("V4", f"目录名({dirname})与 proposal_id({proposal_id})不一致，建议保持一致")
        if not isinstance(manifest.get("filtered"), list):
            r.fail("V4", "manifest 缺 filtered 列表（过滤区对账，可为空列表）")
    except Exception as e:
        r.fail("V4", f"manifest.json 解析失败: {e}")

    # V5 proposal.md 结构 / 覆盖 / 入库申请
    ptext = open(ppath, encoding="utf-8").read()
    for sec in PROPOSAL_SECTIONS:
        if extract_section(ptext, sec) is None:
            r.fail("V5", f"proposal.md 缺『## {sec}』节")
    pids = set(re.findall(r"\bA\d+\b", ptext))
    for aid in assets:
        if aid not in pids:
            r.fail("V5", f"proposal.md 未覆盖资产 {aid}")
    for pid in pids - set(assets):
        r.fail("V5", f"proposal.md 出现了不存在的资产 id: {pid}")
    if not any(x.startswith("V5") for x in r.fails):
        r.ok("V5 proposal.md 四节结构与汇总覆盖")
    intake = extract_section(ptext, "入库申请")
    if intake is None:
        r.fail("V5", "proposal.md 缺『## 入库申请』节")
    else:
        intake_missing = []
        for key in INTAKE_REQUIRED:
            if key == "验收清单":
                lines = list(re.finditer(r"(?m)^[^\n]*验收清单[^\n]*$", intake))
                if not lines:
                    intake_missing.append(key)
                    continue
                block = intake[lines[-1].end():]
                block = re.split(r"\n\s*\*\*[^*]+\*\*|\n##", block)[0]
                items = re.findall(r"^\s*[-*]\s*(?:\[[ xX]\]\s*)?(.+)$", block, re.M)
                items = [x for x in items if not is_placeholder(x)]
                if len(items) < 2:
                    intake_missing.append("验收清单(至少2项且非空)")
                continue
            search_key = "owner" if key == "owner" else key
            value = extract_label_value(intake, search_key)
            if key == "回滚" and value is None:
                value = extract_label_value(intake, "回滚方式")
            if value is None or is_placeholder(value):
                intake_missing.append(f"{key}(空值)")
        if intake_missing:
            r.fail("V5", f"入库申请节缺要素: {intake_missing}")
        else:
            r.ok("V5 入库申请节要素齐全且值非空")

    # V6 id 唯一（proposal 内）
    if len(assets) != len(afiles):
        r.fail("V6", f"资产 id 疑似重复: {len(afiles)} 文件但只解析出 {len(assets)} 个 id")
    if not any(x.startswith("V6") for x in r.fails):
        r.ok("V6 id 唯一性")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("proposal_dir")
    ap.add_argument("--strict", action="store_true", help="警告也视为失败")
    args = ap.parse_args()
    r = validate(args.proposal_dir)
    print(f"\n[validate] 检查 {r.checks} 项: 通过 {r.checks - len(r.fails) - len(r.warns)} / "
          f"失败 {len(r.fails)} / 警告 {len(r.warns)}")
    if r.fails:
        print("[validate] ❌ 校验未通过，按 R6 不得 propose")
        sys.exit(1)
    if r.warns and args.strict:
        print("[validate] ❌ strict 模式: 警告视为失败")
        sys.exit(1)
    print("[validate] ✅ 确定性校验通过（语义有效性仍需 owner 评审）")
    sys.exit(0)


if __name__ == "__main__":
    main()
