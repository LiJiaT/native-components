#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""asset-ai-ize（技能B）implementation package 确定性校验
（确定性优先原则：模型不独自裁决通过与不通过）

用法:
    python -X utf8 validate_build.py <build-dir> [--assets-repo <path>]

校验项（全部确定性）:
  B1  目录结构: implementation.md / build-manifest.json / artifacts/ / tests/ /
      review.md / install.md 齐全，artifacts 与 tests 非空
      （mapping_issue 分支: mapping-issue.md + build-manifest.json）
  B2  build-manifest 字段: type/asset_id/proposal_id/ai_form/artifacts/tests
      齐全且与目录对账（artifacts/tests 按相对路径比较）
  B3  record 校验: asset_id 在资产 repo 中唯一存在、status=approved、
      proposal_id 与 ai_form 和 manifest 一致
  B4  artifact 引用: .md/.yaml artifact 的 frontmatter 含 asset_id；
      .py 建议在文件头用 `# asset_id: <id>` 注释
  B5  语义保持: implementation.md 含语义保持对照节
  B6  敏感信息: 所有文本 artifact 无密钥/令牌模式（邮箱仅警告）
  B7  原始记录混入: artifact 不含 record 原文结构（## 出处与理由 标题）

exit 0 = 全部通过; exit 1 = 有失败项（2 = 缺 pyyaml）
"""
import sys, os, re, json, argparse, glob

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

DEFAULT_ASSETS_REPO = r"D:\Project\native-assets"

# (pattern, label, severity: fail|warn)
SENSITIVE_PATTERNS = [
    (re.compile(r"(ghp|gho|ghs|github_pat)_[A-Za-z0-9]{16,}"), "GitHub 令牌", "fail"),
    (re.compile(r"\bsk-[A-Za-z0-9]{16,}"), "API key（sk-）", "fail"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "AWS AK", "fail"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}"), "Bearer 令牌", "fail"),
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.(com|cn|org|net)\b"),
     "邮箱地址", "warn"),
]
TEXT_EXTS = {".md", ".yaml", ".yml", ".py", ".json", ".sh", ".txt"}
DOC_EXTS = {".md", ".yaml", ".yml"}


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
    out = []
    for root, _, files in os.walk(d):
        out += [os.path.join(root, f) for f in files if not f.startswith(".")]
    return out


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


def find_records(assets_repo, asset_id):
    """在资产 repo 的 assets/ 下按 frontmatter.asset_id 查找 record（可能多条）。"""
    hits = []
    for f in glob.glob(os.path.join(assets_repo, "assets", "**", "*.md"), recursive=True):
        try:
            fm, _ = split_frontmatter(open(f, encoding="utf-8").read())
        except Exception:
            continue
        if fm and fm.get("asset_id") == asset_id:
            hits.append((f, fm))
    return hits


def check_record(r, assets_repo, manifest, ai_form_required=True):
    """B3：record 唯一、approved、proposal_id / ai_form 与 manifest 一致。"""
    asset_id = manifest.get("asset_id", "")
    if not os.path.isdir(assets_repo):
        r.fail("B3", f"资产 repo 路径不存在: {assets_repo}（用 --assets-repo 指定）")
        return
    hits = find_records(assets_repo, asset_id)
    if not hits:
        r.fail("B3", f"资产 repo 中找不到 asset_id={asset_id} 的 record")
        return
    if len(hits) > 1:
        r.fail("B3", f"asset_id={asset_id} 在资产 repo 中出现 {len(hits)} 次（必须唯一）: "
                     f"{[os.path.relpath(h[0], assets_repo) for h in hits]}")
        return
    rf, rfm = hits[0]
    if rfm.get("status") != "approved":
        r.fail("B3", f"record {asset_id} status={rfm.get('status')}，仅可消费 approved")
        return
    if rfm.get("proposal_id") != manifest.get("proposal_id"):
        r.fail("B3", f"proposal_id 不一致: record={rfm.get('proposal_id')} "
                     f"manifest={manifest.get('proposal_id')}")
        return
    if ai_form_required and rfm.get("ai_form") != manifest.get("ai_form"):
        r.fail("B3", f"ai_form 不一致: record={rfm.get('ai_form')} "
                     f"manifest={manifest.get('ai_form')}（B 不得改映射）")
        return
    r.ok(f"B3 record 校验（{asset_id} approved，proposal_id/ai_form 一致）")


def validate(bdir, assets_repo):
    r = Report()
    print(f"[validate_build] build 目录: {bdir}")
    print(f"[validate_build] 资产 repo: {assets_repo}")

    mpath = os.path.join(bdir, "build-manifest.json")
    if not os.path.isfile(mpath):
        r.fail("B1", "缺少 build-manifest.json"); return r
    try:
        manifest = json.load(open(mpath, encoding="utf-8"))
    except Exception as e:
        r.fail("B2", f"build-manifest.json 解析失败: {e}"); return r

    mtype = manifest.get("type", "implementation")
    if mtype not in ("implementation", "mapping_issue"):
        r.fail("B2", f"type 非法: {mtype}")

    # ---------- mapping_issue 分支 ----------
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
        for k in ("asset_id", "proposal_id", "ai_form"):
            if not manifest.get(k):
                r.fail("B2", f"manifest 缺 {k}")
        if manifest.get("ai_form") not in ("Memory", "Rule", "Skill", "Workflow", "Hook", "Prompt"):
            r.fail("B2", f"ai_form 非法: {manifest.get('ai_form')}")
        if not any(x.startswith("B2") for x in r.fails):
            r.ok("B2 manifest 字段（mapping_issue）")
        check_record(r, assets_repo, manifest)
        return r

    # ---------- implementation 分支 ----------
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
    if r.fails:
        return r
    afiles = list_files(adir)
    tfiles = list_files(tdir)
    if not afiles:
        r.fail("B1", "artifacts/ 下没有任何文件"); return r
    if not tfiles:
        r.fail("B1", "tests/ 下没有任何文件（验收测试不得为空）"); return r
    r.ok(f"B1 目录结构（artifacts={len(afiles)}, tests={len(tfiles)}）")

    # B2 manifest 字段与对账
    for k in ("asset_id", "proposal_id", "ai_form", "artifacts", "tests"):
        if not manifest.get(k):
            r.fail("B2", f"manifest 缺 {k}")
    if manifest.get("ai_form") not in ("Memory", "Rule", "Skill", "Workflow", "Hook", "Prompt"):
        r.fail("B2", f"ai_form 非法: {manifest.get('ai_form')}")
    declared_a = [strip_prefix(norm_rel(a), "artifacts/") for a in manifest.get("artifacts", [])]
    actual_a = [norm_rel(os.path.relpath(f, adir)) for f in afiles]
    if sorted(declared_a) != sorted(actual_a):
        r.fail("B2", f"manifest.artifacts 与 artifacts/ 不一致: {declared_a} vs {actual_a}")
    declared_t = [strip_prefix(norm_rel(t), "tests/") for t in manifest.get("tests", [])]
    actual_t = [norm_rel(os.path.relpath(f, tdir)) for f in tfiles]
    if sorted(declared_t) != sorted(actual_t):
        r.fail("B2", f"manifest.tests 与 tests/ 不一致: {declared_t} vs {actual_t}")
    if not any(x.startswith("B2") for x in r.fails):
        r.ok(f"B2 manifest 字段与对账（artifacts={len(actual_a)}, tests={len(actual_t)}）")

    # B3 record 校验
    check_record(r, assets_repo, manifest)

    # B4/B6/B7 artifact 检查
    asset_id = manifest.get("asset_id", "")
    for f in afiles:
        rel = norm_rel(os.path.relpath(f, adir))
        ext = os.path.splitext(f)[1].lower()
        text = open(f, encoding="utf-8", errors="replace").read()
        # B4 artifact 引用
        if ext in DOC_EXTS:
            fm, _ = split_frontmatter(text)
            if fm is None or "__parse_error__" in fm:
                r.warn("B4", f"{rel} 无 frontmatter（组件文档建议带 asset_id）")
            elif fm.get("asset_id") != asset_id:
                r.fail("B4", f"{rel} frontmatter asset_id={fm.get('asset_id')!r}，应为 {asset_id}")
        elif ext == ".py":
            m = re.search(r"^#\s*asset_id:\s*(\S+)", text, re.M)
            if not m:
                r.warn("B4", f"{rel} 缺 `# asset_id: {asset_id}` 文件头注释")
            elif m.group(1) != asset_id:
                r.fail("B4", f"{rel} 文件头 asset_id={m.group(1)!r}，应为 {asset_id}")
        # B6 敏感信息（所有文本 artifact）
        if ext in TEXT_EXTS:
            for pat, label, severity in SENSITIVE_PATTERNS:
                if pat.search(text):
                    if severity == "fail":
                        r.fail("B6", f"{rel} 疑似含敏感信息（{label}）")
                    else:
                        r.warn("B6", f"{rel} 疑似含{label}，确认非敏感后再合入")
        # B7 原始记录混入
        if ext in DOC_EXTS and "## 出处与理由" in text:
            r.fail("B7", f"{rel} 含 record 原文结构（## 出处与理由）——实现物不得粘贴 record 原文")
    if not any(x.startswith(("B4", "B6", "B7")) for x in r.fails):
        r.ok("B4/B6/B7 artifact 引用 / 敏感信息 / 原始记录检查")

    # B5 语义保持
    itext = open(ipath, encoding="utf-8").read()
    if "语义保持" not in itext:
        r.fail("B5", "implementation.md 缺『语义保持』对照节")
    elif "对照" not in itext:
        r.warn("B5", "implementation.md 语义保持节建议为对照表（statement 结论 → 承载位置）")
    else:
        r.ok("B5 语义保持对照节")
    return r


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("build_dir")
    ap.add_argument("--assets-repo", default=DEFAULT_ASSETS_REPO,
                    help="资产 repo 本地 clone 路径（默认 %(default)s）")
    args = ap.parse_args()
    r = validate(args.build_dir, args.assets_repo)
    print(f"\n[validate_build] 检查 {r.checks} 项: 通过 {r.checks - len(r.fails) - len(r.warns)} / "
          f"失败 {len(r.fails)} / 警告 {len(r.warns)}")
    if r.fails:
        print("[validate_build] ❌ 校验未通过，按 R6 不得生成实现申请")
        sys.exit(1)
    print("[validate_build] ✅ 校验通过")
    sys.exit(0)


if __name__ == "__main__":
    main()
