#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""assetize（技能A）proposal package 确定性校验
（确定性优先原则：模型不独自裁决通过与不通过）

用法:
    python -X utf8 validate.py <proposal-dir> [--strict]

校验项（全部确定性）:
  V1  目录结构: proposal.md / assets/ / manifest.json 齐全，assets 至少 1 个文件
  V2  资产 frontmatter: 必填字段齐全
  V3  枚举一致性: form/layer/project/domains/ai_form 合法组合（项目级↔project 等）
  V4  manifest 对账: manifest.assets 与 assets/ 文件 id 一一对应，无缺无余
  V5  proposal.md 汇总表: 覆盖所有资产 id，无多余 id；含入库申请七要素节
  V6  id 唯一: proposal 内部无重复
  V7  正文提炼检查: 资产正文非空且 >= 40 字（拦截原文裸贴/空壳）
  V8  决策记忆完整度: form=决策记忆 的正文须含 背景/取舍 关键段（宽松提示级）

exit 0 = 全部通过; exit 1 = 有失败项（V8 警告不阻断）
"""
import sys, os, re, json, argparse

# Windows GBK 控制台兼容：✅/❌/⚠️ 在 GBK 下抛 UnicodeEncodeError，
# 会被误读为"校验不通过"。统一重配 stdout/stderr 为 UTF-8。
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
PROJECTS = {"LPDDR6", "HBM", "无"}
LAYERS = {"个人级", "项目级", "领域级", "公共级"}
AI_FORMS = {"Memory", "Rule", "Skill", "Workflow", "Hook", "Prompt"}
REQUIRED_FIELDS = ["id", "title", "form", "secondary_tags", "domains", "project",
                   "layer", "ai_form", "source", "suggested_owner"]
INTAKE_REQUIRED = ["资产 ID", "来源提案", "层级", "领域",
                   "变更内容", "验收清单", "回滚"]  # 入库申请节必含要素（宽松关键词；owner 单独按字段名匹配）


def split_frontmatter(text):
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    if not m:
        return None, text
    try:
        return yaml.safe_load(m.group(1)) or {}, m.group(2)
    except yaml.YAMLError as e:
        return {"__parse_error__": str(e)}, ""


def extract_section(text, heading):
    """取 `## <heading>` 到下一个同级/更高级标题之间的正文；不存在返回 None。"""
    m = re.search(rf"^##+\s*{re.escape(heading)}.*$", text, re.M)
    if not m:
        return None
    rest = text[m.end():]
    n = re.search(r"^##+\s", rest, re.M)
    return rest[:n.start()] if n else rest


def as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return v
    return [v]


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
        print(f"  ⚠️ {name}: {detail}")


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

    # V2/V3/V7/V8 资产文件
    assets = {}
    for f in afiles:
        fm, body = split_frontmatter(open(os.path.join(adir, f), encoding="utf-8").read())
        name = f"assets/{f}"
        if fm is None or "__parse_error__" in fm:
            r.fail("V2", f"{name} frontmatter 缺失或 YAML 解析失败"); continue
        missing = [k for k in REQUIRED_FIELDS if k not in fm]
        if missing:
            r.fail("V2", f"{name} 缺必填字段: {missing}"); continue
        # V3 枚举与组合
        if fm["form"] == "上下文":
            r.fail("V3", f"{name} form=上下文——此类单元不成案，应进 proposal 的已过滤区")
        elif fm["form"] not in FORMS:
            r.fail("V3", f"{name} form 非法: {fm['form']}")
        for t in as_list(fm.get("secondary_tags")):
            if t == "上下文":
                r.fail("V3", f"{name} 副标签含上下文——上下文不成案，应进已过滤区")
            elif t not in FORMS:
                r.fail("V3", f"{name} 副标签非法: {t}")
        for d in as_list(fm.get("domains")):
            if d not in DOMAINS:
                r.fail("V3", f"{name} 领域非法: {d}（合法: {sorted(DOMAINS)}）")
        if len(as_list(fm.get("domains"))) > 3:
            r.fail("V3", f"{name} 领域多选超过 3 个")
        if not as_list(fm.get("domains")) and fm["layer"] != "公共级":
            r.fail("V3", f"{name} domains 为空但 layer={fm['layer']}——仅公共级（跨领域通用）资产可不标领域")
        if fm["project"] not in PROJECTS:
            r.fail("V3", f"{name} project 非法: {fm['project']}")
        if fm["layer"] not in LAYERS:
            r.fail("V3", f"{name} layer 非法: {fm['layer']}")
        if fm["ai_form"] not in AI_FORMS:
            r.fail("V3", f"{name} ai_form 非法: {fm['ai_form']}（合法: {sorted(AI_FORMS)}）")
        if fm["layer"] == "项目级" and fm["project"] == "无":
            r.fail("V3", f"{name} 层级=项目级 但 project=无，组合矛盾")
        r.checks += 1
        # V7 提炼度
        body_clean = re.sub(r"\s", "", body)
        if len(body_clean) < 40:
            r.fail("V7", f"{name} 正文过短（{len(body_clean)} 字），疑似未提炼或空壳")
        else:
            r.ok(f"V7 {name} 正文提炼度（{len(body_clean)} 字）")
        # V8 决策记忆完整度（提示级）
        if fm["form"] == "决策记忆":
            has_all = all(k in body for k in ("背景", "取舍"))
            if not has_all:
                r.warn("V8", f"{name} 决策记忆建议含『背景/选项/取舍/证据/日期』结构段")
        assets[fm["id"]] = {"file": f, "fm": fm}
    r.ok(f"V2/V3 资产字段与枚举（{len(assets)} 个资产）") if assets and not any(
        x.startswith("V2") or x.startswith("V3") for x in r.fails) else None

    # V4 manifest 对账
    try:
        manifest = json.load(open(mpath, encoding="utf-8"))
        m_assets = manifest.get("assets", [])
        m_ids = [a.get("id") for a in m_assets]
        if sorted(m_ids) != sorted(assets.keys()):
            r.fail("V4", f"manifest 资产清单与 assets/ 不一致: "
                         f"manifest={sorted(m_ids)} 实际={sorted(assets.keys())}")
        else:
            # manifest 内每条的标注字段与资产文件一致
            mismatch = []
            for a in m_assets:
                fm = assets.get(a["id"], {}).get("fm")
                if not fm:
                    continue
                for key in ("title", "form", "ai_form", "layer", "domains",
                            "project", "suggested_owner"):
                    if a.get(key) != fm.get(key):
                        mismatch.append(f"{a['id']}.{key}")
            if mismatch:
                r.fail("V4", f"manifest 与资产 frontmatter 不一致: {mismatch}")
            else:
                r.ok(f"V4 manifest 对账（{len(m_ids)} 资产，字段一致）")
        for key in ("proposal_id", "date", "source_material"):
            if not manifest.get(key):
                r.fail("V4", f"manifest 缺 {key}")
        proposal_id = manifest.get("proposal_id")
        dirname = os.path.basename(os.path.normpath(os.path.abspath(pdir)))
        if proposal_id and dirname != proposal_id:
            r.warn("V4", f"目录名({dirname})与 proposal_id({proposal_id})不一致，建议保持一致")
        if not isinstance(manifest.get("filtered"), list):
            r.warn("V4", "manifest 缺 filtered 列表（过滤区对账）")
    except Exception as e:
        r.fail("V4", f"manifest.json 解析失败: {e}")

    # V5 proposal.md 覆盖 + 入库申请节
    ptext = open(ppath, encoding="utf-8").read()
    pids = set(re.findall(r"\bA\d+\b", ptext))
    for aid in assets:
        if aid not in pids:
            r.fail("V5", f"proposal.md 未覆盖资产 {aid}")
    for pid in pids - set(assets):
        r.fail("V5", f"proposal.md 出现了不存在的资产 id: {pid}")
    if not any(x.startswith("V5") for x in r.fails):
        r.ok("V5 proposal.md 汇总覆盖")
    intake = extract_section(ptext, "入库申请")
    if intake is None:
        r.fail("V5", "proposal.md 缺『## 入库申请』节")
    else:
        intake_missing = [k for k in INTAKE_REQUIRED if k not in intake]
        if not re.search(r"(?<![A-Za-z_])owner\s*[:：]", intake):
            intake_missing.append("owner")
        if intake_missing:
            r.fail("V5", f"入库申请节缺要素: {intake_missing}"
                         f"（资产ID/来源提案/层级/领域/owner/变更内容/验收清单/回滚方式）")
        else:
            r.ok("V5 入库申请节要素齐全")

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
    print("[validate] ✅ 校验通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
