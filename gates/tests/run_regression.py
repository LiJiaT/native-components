#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""审计修复回归测试（合成数据，不调用真实模型、不发送、不安装）。

覆盖审计报告中的关键负例：A 空值/原始日志/空申请、B 最小 record/正文篡改/
来源失真/范围扩大/synthetic 进生产/隐藏文件/逐字稿/坏 YAML/空评审、任务包
七类假通过、入队 eval/Windows 路径/空格 JSON/单行多工具、worker 失败保留/
dry-run/陈旧锁/非法候选/去重、反馈脱敏、extract 截断标记、计划/验收/外发门禁。
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

REPO = Path(__file__).resolve().parents[2]
PY = sys.executable
TMP = Path(tempfile.mkdtemp(prefix="ai-native-regression-"))
PASS = FAIL = 0


def run(cmd, env=None, input_text=None, cwd=None):
    e = os.environ.copy()
    if env:
        e.update(env)
    return subprocess.run(cmd, input=input_text, capture_output=True, text=True,
                          encoding="utf-8", errors="replace", env=e,
                          cwd=str(cwd) if cwd else None)


def check(name, cond, detail=""):
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name} {detail}")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes().replace(b"\r\n", b"\n")).hexdigest()


def sha_raw(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def dump_yaml(fm, body):
    import yaml
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).rstrip() + "\n---\n" + body


def write(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def queue_jobs(home):
    q = Path(home) / ".claude/self-evolve/queue"
    jobs = []
    if (q / "jobs.jsonl").exists():
        for line in (q / "jobs.jsonl").read_text(encoding="utf-8").splitlines():
            if line.strip():
                jobs.append(json.loads(line))
    if (q / "inbox").exists():
        for p in sorted((q / "inbox").glob("*.json")):
            jobs.append(json.loads(p.read_text(encoding="utf-8")))
    return jobs


def clear_queue(home):
    q = Path(home) / ".claude/self-evolve/queue"
    if (q / "jobs.jsonl").exists():
        (q / "jobs.jsonl").unlink()
    if (q / "inbox").exists():
        for p in (q / "inbox").glob("*.json"):
            p.unlink()


# ---------------------------------------------------------------- assets fixture
ASSET_ID = "EA-20261022-99"

def make_assets_repo(root):
    rec = root / "assets" / "prop" / f"{ASSET_ID}-test.md"
    body = ("## 内容\n\n这是一个用于回归测试的稳定结论，正文足够长以满足最小长度要求。\n\n"
            "## 出处与理由\n\n- 来源：合成测试材料\n")
    fm = {
        "asset_id": ASSET_ID, "proposal_id": "prop", "title": "测试资产",
        "form": "知识库", "secondary_tags": [], "domains": [], "project": "无",
        "layer": "公共级", "ai_form": "Memory", "source": "合成测试 2026-10-24",
        "owner": "测试 owner", "status": "approved", "approved_by": "Tester",
        "approved_date": "2026-10-22", "provenance_status": "source-excerpt",
        "provenance_note": "合成测试来源，仅用于回归",
        "release_channel": "component-library",
    }
    write(rec, dump_yaml(fm, body))
    content_hash = hashlib.sha256((json.dumps(fm, sort_keys=True, ensure_ascii=False,
                                              default=str) + "\n---\n" + body).encode()).hexdigest()
    ap = {"schema_version": "1", "asset_id": ASSET_ID, "proposal_id": "prop",
          "record_path": rec.relative_to(root).as_posix(), "record_sha256": sha(rec),
          "content_sha256": content_hash, "approver": "Tester", "decision": "approved",
          "approved_at": "2026-10-22", "release_channel": "component-library",
          "scope": {"layer": "公共级", "projects": [], "domains": [], "ai_form": "Memory",
                    "owner": "测试 owner", "provenance_status": "source-excerpt",
                    "release_channel": "component-library"}}
    write(root / "approvals" / f"{ASSET_ID}.json", json.dumps(ap, ensure_ascii=False, indent=2))
    return rec, ap


def make_build(root, assets_repo, synthetic=False):
    b = root / "build"
    asset_rel = f"assets/prop/{ASSET_ID}-test.md"
    fm = {
        "asset_id": ASSET_ID, "proposal_id": "prop", "ai_form": "Memory",
        "asset_type": "memory", "title": "测试资产", "owner": "测试 owner",
        "layer": "公共级", "projects": [], "domains": [],
        "schema_version": "2", "package_version": "1.0.0",
        "provenance_status": "synthetic" if synthetic else "source-excerpt",
        "provenance_note": "合成测试来源，仅用于回归",
        "install_target": "test-sandbox" if synthetic else "user-global",
        "release_channel": "test-only" if synthetic else "component-library",
        "source_record": asset_rel, "source_record_sha256": sha(assets_repo / asset_rel),
        "source_content_sha256": "",
        "artifacts": ["memory.md"], "tests": ["trigger.md"],
        "producer": "测试团队",
        "generated_by": "pytest fixture 2026-10-24",
        "review": {"file": "review.md", "reviewer": "Tester", "decision": "approved"},
        "validation": {"validator": "validate_build.py", "result": "pass"},
    }
    import yaml
    rfm, rbody = None, None
    text = (assets_repo / asset_rel).read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.S)
    rfm = yaml.safe_load(m.group(1)); rbody = m.group(2)
    fm["source_content_sha256"] = hashlib.sha256((json.dumps(
        {k: v for k, v in rfm.items() if k != "implementation"}, sort_keys=True,
        ensure_ascii=False, default=str) + "\n---\n" + rbody).encode()).hexdigest()
    write(b / "build-manifest.json", json.dumps(fm, ensure_ascii=False, indent=2))
    ch = fm["release_channel"]
    write(b / "artifacts" / "memory.md",
          dump_yaml({"asset_id": ASSET_ID, "ai_form": "Memory", "asset_type": "memory",
                     "provenance_status": fm["provenance_status"],
                     "provenance_note": fm["provenance_note"], "release_channel": ch,
                     "source_record": asset_rel},
                    "# 测试实现\n\n这是实现正文，足够长。\n"))
    write(b / "tests" / "trigger.md", "# 测试\n\nPASS: 合成触发样例。\n")
    write(b / "implementation.md", "# 实现说明\n\n## 语义保持 对照\n\n| statement | 位置 |\n|---|---|\n| 结论 | memory.md |\n")
    write(b / "review.md", "# 评审\n\n评审清单：record 绑定、范围、语义保持、敏感信息、测试。\n")
    write(b / "install.md", f"# 安装\n\n- install_target: `{fm['install_target']}`\n- 回滚：删除目标文件并恢复备份。\n")
    return b, fm


def run_b(b, assets_repo, release=False):
    cmd = [PY, "-X", "utf8", str(REPO / "skills/asset-ai-ize/scripts/validate_build.py"),
           str(b), "--assets-repo", str(assets_repo)]
    if release:
        cmd.append("--release")
    return run(cmd)


# ---------------------------------------------------------------- A fixture
def make_proposal(root, variant="valid"):
    d = root / "proposal"
    fm = {"id": "A1", "title": "测试资产", "form": "知识库", "secondary_tags": [],
          "domains": [], "project": "无", "layer": "公共级", "ai_form": "Memory",
          "source": "合成测试 2026-10-24", "suggested_owner": "测试 owner"}
    body = "## 内容\n\n这是一个可独立成立的测试结论，长度足够通过最小长度检查。\n\n## 出处与理由\n\n合成材料。\n"
    if variant == "blank":
        fm["title"] = ""
    if variant == "raw":
        body = ("## 内容\n\n2026-10-20 12:00:00 DEBUG starting run\n"
                "2026-10-20 12:00:01 DEBUG command output repeated\n"
                "2026-10-20 12:00:02 DEBUG done\n")
    if variant == "multi":
        fm.update({"project": ["LPDDR6", "HBM"], "layer": "领域级", "domains": ["DFT"]})
    if variant == "dup_project":
        fm.update({"projects": ["HBM", "HBM"], "layer": "领域级", "domains": ["DFT"]})
    if variant == "domains_scalar":
        fm["domains"] = "DFT"
    if variant == "raw_long":
        body = ("## 内容\n\n2026-10-20 12:00:00 DEBUG " + "x" * 200 + "\n")
    if variant == "raw_date_speaker":
        body = ("## 内容\n\n2026-10-20 10:00:00 Speaker A: hello\n"
                "2026-10-20 10:00:05 Speaker B: hi\n")
    if variant == "unmapped":
        fm.update({"ai_form": None, "mapping_status": "deferred",
                   "mapping_reason": "当前阶段不 AI 化，留给领域 owner 决定"})
    if variant == "decision":
        fm["form"] = "决策记忆"
        body = "## 内容\n\n背景：测试。取舍：选 A。\n\n## 出处与理由\n\n合成。\n"
    write(d / "assets" / "A1-test.md", dump_yaml(fm, body))
    manifest = {"proposal_id": "prop-test", "date": "2026-10-24",
                "source_material": "合成测试", "assets": [dict(fm, project=fm["project"])],
                "filtered": []}
    write(d / "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    intake_values = {
        "资产 ID": "A1", "来源提案": "prop-test", "目标层级": "公共级",
        "领域": "无", "项目": "无", "owner": "测试 owner",
        "变更内容": "新增测试资产", "验收清单": "- [ ] 检查 A\n- [ ] 检查 B",
        "回滚方式": "revert 对应 commit",
    }
    if variant == "empty_intake":
        for k in ("资产 ID", "来源提案", "owner", "变更内容", "回滚方式"):
            intake_values[k] = ""
        intake_values["验收清单"] = "- [ ] "
    lines = ["# 测试提案", "", "## 资产清单", "", "| # | 标题 |", "|---|---|", "| A1 | 测试资产 |", "",
             "## 已过滤区", "", "无。", "", "## 入库申请", ""]
    lines += [f"- {k}：{v}" for k, v in intake_values.items()]
    lines += ["", "## 审批区", "", "| 项 | 内容 |", "|---|---|", "| 审批结论 | 待审批 |"]
    write(d / "proposal.md", "\n".join(lines) + "\n")
    return d


def main():
    print("[1] 技能 A 校验")
    assets_repo = TMP / "assets-repo"
    assets_repo.mkdir()
    make_assets_repo(assets_repo)
    for variant, expect in [("valid", 0), ("blank", 1), ("raw", 1), ("empty_intake", 1),
                            ("multi", 0), ("unmapped", 0), ("decision", 1)]:
        d = make_proposal(TMP / f"p-{variant}", variant)
        r = run([PY, "-X", "utf8", str(REPO / "skills/assetize/scripts/validate.py"), str(d)])
        check(f"A/{variant}", r.returncode == expect,
              f"exit={r.returncode} expected={expect}\n{r.stdout[-500:]}")

    print("[2] 技能 B 校验")
    b, bm = make_build(TMP / "b-ok", assets_repo)
    r = run_b(b, assets_repo)
    check("B/valid-structure", r.returncode == 0, r.stdout[-500:])

    # 最小 approved record（只有四个字段）
    bad_repo = TMP / "assets-min"; bad_repo.mkdir()
    rec = bad_repo / "assets" / "prop" / f"{ASSET_ID}-test.md"
    write(rec, dump_yaml({"asset_id": ASSET_ID, "proposal_id": "prop", "ai_form": "Memory",
                          "status": "approved"}, "## 内容\n\n短\n"))
    bmin, _ = make_build(TMP / "b-min", assets_repo)
    r = run_b(bmin, bad_repo)
    check("B/minimal-record-rejected", r.returncode != 0, r.stdout[-300:])

    # 正文被篡改
    mutated = assets_repo / f"assets/prop/{ASSET_ID}-test.md"
    original = mutated.read_text(encoding="utf-8")
    write(mutated, original.replace("稳定结论", "相反结论"))
    r = run_b(b, assets_repo)
    check("B/statement-mutation-rejected", r.returncode != 0, r.stdout[-300:])
    write(mutated, original)

    # source_record 不存在
    m2 = json.loads((b / "build-manifest.json").read_text(encoding="utf-8"))
    m2["source_record"] = "../../outside/nonexistent.md"
    write(b / "build-manifest.json", json.dumps(m2, ensure_ascii=False, indent=2))
    r = run_b(b, assets_repo)
    check("B/wrong-source-record-rejected", r.returncode != 0, r.stdout[-300:])
    write(b / "build-manifest.json", json.dumps(bm, ensure_ascii=False, indent=2))

    # 范围扩大：项目级 -> 公共目标
    m3 = dict(bm); m3["layer"] = "项目级"; m3["projects"] = ["HBM"]; m3["install_target"] = "user-global"
    write(b / "build-manifest.json", json.dumps(m3, ensure_ascii=False, indent=2))
    r = run_b(b, assets_repo)
    check("B/project-to-public-rejected", r.returncode != 0, r.stdout[-300:])
    write(b / "build-manifest.json", json.dumps(bm, ensure_ascii=False, indent=2))

    # synthetic 进生产
    bs, bsm = make_build(TMP / "b-synth", assets_repo, synthetic=True)
    bsm["install_target"] = "user-global"; bsm["release_channel"] = "component-library"
    write(bs / "build-manifest.json", json.dumps(bsm, ensure_ascii=False, indent=2))
    r = run_b(bs, assets_repo)
    check("B/synthetic-production-rejected", r.returncode != 0, r.stdout[-300:])

    # 隐藏文件 / 缺 provenance / 坏 YAML / 原始逐字稿 / 空评审+FAIL
    for name, mutate in [
        ("hidden-file", lambda b: write(b / "artifacts" / ".env", "ghp_" + "A" * 30)),
        ("missing-provenance", lambda b: write(b / "artifacts" / "memory.md", "# no frontmatter\n")),
        ("malformed-yaml", lambda b: write(b / "artifacts" / "memory.md", "---\nasset_id: [\n---\n# x\n")),
        ("raw-transcript", lambda b: write(
            b / "artifacts" / "memory.md",
            dump_yaml({"asset_id": ASSET_ID, "provenance_status": "source-excerpt",
                       "provenance_note": "测试来源说明", "release_channel": "component-library"},
                      "2026-10-20 12:00:00 DEBUG x\nSpeaker A: hello\nSpeaker B: hi\n"))),
        ("empty-review-fail-test", lambda b: (
            write(b / "review.md", ""), write(b / "install.md", ""),
            write(b / "tests" / "trigger.md", "FAIL: every criterion unsatisfied\n"))),
    ]:
        bd, _ = make_build(TMP / f"b-{name}", assets_repo)
        mutate(bd)
        r = run_b(bd, assets_repo)
        check(f"B/{name}-rejected", r.returncode != 0, r.stdout[-300:])

    # 发布层缺证据
    bd, _ = make_build(TMP / "b-release-missing", assets_repo)
    r = run_b(bd, assets_repo, release=True)
    check("B/release-without-evidence-rejected", r.returncode != 0, r.stdout[-300:])

    # 发布层完整
    bd, m = make_build(TMP / "b-release-ok", assets_repo)
    m["tests"] += ["results.json", "consumer.py"]
    write(bd / "build-manifest.json", json.dumps(m, ensure_ascii=False, indent=2))
    hashes = {p.name: sha(p) for p in (bd / "artifacts").glob("*")}
    evidence = bd / "tests" / "trigger.md"
    write(bd / "tests" / "consumer.py", "print('ok')\n")
    write(bd / "tests" / "results.json", json.dumps({
        "asset_id": ASSET_ID,
        "source_record_sha256": m["source_record_sha256"],
        "source_content_sha256": m["source_content_sha256"],
        "result": "pass", "tested_at": "2026-10-24T10:00:00+08:00", "tested_by": "tester",
        "commands": [{"command": "true", "exit_code": 0}],
        "consumer_test": {"command": "true", "exit_code": 0,
                          "executed_at": "2026-10-24T10:00:00+08:00",
                          "script_path": "tests/consumer.py",
                          "script_sha256": sha(bd / "tests" / "consumer.py"),
                          "evidence_path": "tests/trigger.md",
                          "evidence_sha256": sha(evidence)},
        "artifact_sha256": hashes}, ensure_ascii=False, indent=2))
    write(bd / "review.json", json.dumps({
        "reviewer": "reviewer", "executor": "executor", "independent": True,
        "decision": "approved", "reviewed_at": "2026-10-24", "artifact_sha256": hashes,
        "source_record_sha256": m["source_record_sha256"],
        "source_content_sha256": m["source_content_sha256"],
        "checklist": [{"id": x, "result": "pass", "note": "ok"} for x in
                      ("record-binding", "manifest-schema", "artifact-provenance",
                       "sensitive-scan", "syntax", "semantic-preservation", "consumer-test")]},
        ensure_ascii=False, indent=2))
    r = run_b(bd, assets_repo, release=True)
    check("B/release-complete-accepted", r.returncode == 0, r.stdout[-400:])
    write(bd / "tests" / "consumer.py", "import sys\nsys.exit(19)\n")
    r = run_b(bd, assets_repo, release=True)
    check("B/stale-consumer-script-rejected", r.returncode != 0, r.stdout[-300:])

    # B/G 对非法 form/date 的跨入口拒绝
    bad_assets = TMP / "assets-bad-schema"
    shutil.copytree(assets_repo, bad_assets)
    rec = bad_assets / f"assets/prop/{ASSET_ID}-test.md"
    mtext = rec.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", mtext, re.S)
    import yaml as _yaml
    rfm = _yaml.safe_load(m.group(1)); rbody = m.group(2)
    rfm.update({"form": "NOT_A_FORM", "approved_date": "NOT_A_DATE"})
    rec.write_text("---\n" + _yaml.safe_dump(rfm, allow_unicode=True,
                    sort_keys=False).rstrip() + "\n---\n" + rbody, encoding="utf-8")
    ap = bad_assets / "approvals" / f"{ASSET_ID}.json"
    a = json.loads(ap.read_text(encoding="utf-8"))
    a["content_sha256"] = hashlib.sha256((json.dumps(
        {k: v for k, v in rfm.items() if k != "implementation"}, sort_keys=True,
        ensure_ascii=False, default=str) + "\n---\n" + rbody).encode()).hexdigest()
    a["record_sha256"] = sha(rec)
    ap.write_text(json.dumps(a, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    bd_bad, _ = make_build(TMP / "b-bad-schema", bad_assets)
    r = run_b(bd_bad, bad_assets)
    check("B/invalid-form-date-rejected", r.returncode != 0, r.stdout[-300:])
    r = run([PY, "-X", "utf8", str(REPO / "gates/gate.py"), "record",
             "--assets-repo", str(bad_assets), "--asset-id", ASSET_ID])
    check("G/invalid-form-date-rejected", r.returncode != 0, r.stdout[-300:])

    # G 账册允许 deferred；K/G/B 在 allowed_signers 启用时都要求签名
    def_assets = TMP / "assets-deferred"
    shutil.copytree(assets_repo, def_assets)
    drec = def_assets / f"assets/prop/{ASSET_ID}-test.md"
    dtext = drec.read_text(encoding="utf-8")
    dm = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", dtext, re.S)
    dfm = _yaml.safe_load(dm.group(1)); dbody = dm.group(2)
    dfm.update({"ai_form": None, "mapping_status": "deferred",
                "mapping_reason": "当前阶段不 AI 化，等待领域 owner"})
    drec.write_text("---\n" + _yaml.safe_dump(dfm, allow_unicode=True,
                    sort_keys=False).rstrip() + "\n---\n" + dbody, encoding="utf-8")
    dap = def_assets / "approvals" / f"{ASSET_ID}.json"
    da = json.loads(dap.read_text(encoding="utf-8"))
    da["content_sha256"] = hashlib.sha256((json.dumps(
        {k: v for k, v in dfm.items() if k != "implementation"}, sort_keys=True,
        ensure_ascii=False, default=str) + "\n---\n" + dbody).encode()).hexdigest()
    da["record_sha256"] = sha(drec)
    da["scope"]["ai_form"] = None
    dap.write_text(json.dumps(da, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    r = run([PY, "-X", "utf8", str(REPO / "gates/gate.py"), "record",
             "--assets-repo", str(def_assets), "--asset-id", ASSET_ID])
    check("G/deferred-ledger-accepted", r.returncode == 0, r.stdout[-300:])

    sig_assets = TMP / "assets-signers"
    shutil.copytree(assets_repo, sig_assets)
    if shutil.which("ssh-keygen"):
        key = TMP / "sig-key"
        run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key), "-q"])
        pub = Path(str(key) + ".pub").read_text(encoding="utf-8").strip()
        a0 = json.loads((sig_assets / "approvals" / f"{ASSET_ID}.json").read_text(
            encoding="utf-8"))
        (sig_assets / "approvals" / "allowed_signers").write_text(
            f"{a0.get('approver')} {pub}\n", encoding="utf-8")
        r = run([PY, "-X", "utf8", str(REPO / "gates/gate.py"), "record",
                 "--assets-repo", str(sig_assets), "--asset-id", ASSET_ID])
        check("G/signature-policy-shared-rejected", r.returncode != 0, r.stdout[-300:])
        bd_sig, _ = make_build(TMP / "b-signers", sig_assets)
        r = run_b(bd_sig, sig_assets)
        check("B/signature-policy-shared-rejected", r.returncode != 0, r.stdout[-300:])

    print("[3] 任务包 strict")
    sys.path.insert(0, str(REPO / "skills/orchestrator/scripts"))
    import task_packager as tp
    tp_base = tp.create_task_package("t", "d", "script")
    tp_base["execution"]["target"] = str(REPO / "skills/orchestrator/scripts/task_packager.py")
    tp_base["acceptance_criteria"][0].update({"expected": "ok", "evidence_path": "out.log",
                                           "independent_review": True})
    def tp_check(name, mutate, expect_ok=False):
        pkg = json.loads(json.dumps(tp_base)); mutate(pkg)
        p = TMP / f"tp-{name}.json"; write(p, json.dumps(pkg, ensure_ascii=False))
        ok = tp.validate_task_package(str(p), strict=True)
        check(f"task/{name}", ok == expect_ok)
    tp_check("empty-ac", lambda p: p.update({"acceptance_criteria": [{}]}))
    tp_check("self-dep", lambda p: p.update({"dependencies": [p["task_id"]]}))
    tp_check("bad-types", lambda p: p.update({"input": 17}))
    tp_check("unknown-method", lambda p: p["acceptance_criteria"][0].update({"check_method": "anything"}))
    tp_check("self-same", lambda p: p.update({"execution": {"type": "self", "target": "orchestrator",
                                                             "verifier": "same-run", "timeout_seconds": 60}}))
    tp_check("fake-python", lambda p: p["acceptance_criteria"][0].update(
        {"check_method": "auto", "check_script": "pythonMISSING_DOES_NOT_EXIST.py"}))
    tp_check("valid", lambda p: None, expect_ok=True)

    print("[4] 自进化入队 / worker")
    home = TMP / "home"; (home / ".claude/self-evolve/queue").mkdir(parents=True)
    env = {"HOME": str(home), "USERPROFILE": str(home)}
    tr = TMP / "dir with space" / "t.jsonl"; tr.parent.mkdir()
    lines = [json.dumps({"type": "user", "message": {"content": "do it"}})]
    lines += [json.dumps({"type": "assistant", "message": {"content": [
        {"type": "tool_use", "name": "Read", "input": {}}] * 40}})]
    write(tr, "\n".join(lines) + "\n")
    r = run([PY, "-X", "utf8", str(REPO / "hooks/self-evolve/enqueue.py")], env=env,
            input_text=json.dumps({"session_id": "s1", "transcript_path": str(tr)}))
    enq_ok = any(Path(j["transcript_path"]).resolve() == tr.resolve()
                 for j in queue_jobs(home))
    check("enqueue/windows-space-path", enq_ok, r.stderr[-300:])
    marker = TMP / "eval-marker.txt"
    r = run([PY, "-X", "utf8", str(REPO / "hooks/self-evolve/enqueue.py")], env=env,
            input_text=json.dumps({"session_id": f"safe; printf X > {marker}",
                                   "transcript_path": str(tr)}))
    check("enqueue/no-eval", not marker.exists(), "marker created")
    # 3 edits only should qualify
    tr2 = TMP / "edits.jsonl"
    write(tr2, "\n".join([json.dumps({"type": "user", "message": {"content": "e"}})] +
                         [json.dumps({"type": "assistant", "message": {"content": [
                             {"type": "tool_use", "name": "Edit", "input": {}}]}}) for _ in range(3)]) + "\n")
    r = run([PY, "-X", "utf8", str(REPO / "hooks/self-evolve/enqueue.py")], env=env,
            input_text=json.dumps({"session_id": "s2", "transcript_path": str(tr2)}))
    check("enqueue/edits-only-qualifies",
          any(j.get("session_id") == "s2" for j in queue_jobs(home)))

    # worker stubs
    stub_ok = TMP / "stub_ok.py"; write(stub_ok, "import sys\nprint('[]')\n")
    stub_fail = TMP / "stub_fail.py"; write(stub_fail, "import sys\nprint('[]')\nsys.stderr.write('ERR')\nsys.exit(7)\n")
    stub_bad = TMP / "stub_bad.py"; write(stub_bad, "import sys\nprint('[{\"lane\":\"BAD\",\"title\":\"\",\"content\":\"password=SYNTHETIC\",\"reason\":\"\"}]')\n")
    q = home / ".claude/self-evolve/queue"
    # reset queue to one job
    clear_queue(home)
    write(q / "jobs.jsonl", json.dumps({"session_id": "s1", "transcript_path": str(tr), "enqueued_at": 1}) + "\n")
    r = run([PY, "-X", "utf8", str(REPO / "skills/session-distiller/scripts/worker.py")],
            env={**env, "DISTILLER_CMD": str(stub_fail)})
    check("worker/failure-retains-job", (q / "jobs.jsonl").exists() and
          "s1" in (q / "jobs.jsonl").read_text(encoding="utf-8"), r.stderr[-200:])
    r = run([PY, "-X", "utf8", str(REPO / "skills/session-distiller/scripts/worker.py")],
            env={**env, "DISTILLER_CMD": str(stub_ok)})
    check("worker/success-clears-job", not (q / "jobs.jsonl").read_text(encoding="utf-8").strip())
    # dry-run doesn't consume
    write(q / "jobs.jsonl", json.dumps({"session_id": "s3", "transcript_path": str(tr2), "enqueued_at": 3}) + "\n")
    run([PY, "-X", "utf8", str(REPO / "skills/session-distiller/scripts/worker.py")],
        env={**env, "WORKER_DRY_RUN": "1", "DISTILLER_CMD": str(stub_ok)})
    check("worker/dry-run-keeps-job", "s3" in (q / "jobs.jsonl").read_text(encoding="utf-8"))
    # invalid lane + secret rejected
    run([PY, "-X", "utf8", str(REPO / "skills/session-distiller/scripts/worker.py")],
        env={**env, "DISTILLER_CMD": str(stub_bad)})
    staging = home / ".claude/self-evolve/staging"
    check("worker/invalid-secret-candidate-not-staged",
          not staging.exists() or not list(staging.glob("cand-*.md")))
    # stale lock recovery
    lock = q / ".worker.lock"; lock.mkdir(exist_ok=True)
    write(lock / "owner.json", json.dumps({"pid": 999999, "host": "other", "started_at": 0}))
    write(q / "jobs.jsonl", json.dumps({"session_id": "s4", "transcript_path": str(tr2), "enqueued_at": 4}) + "\n")
    r = run([PY, "-X", "utf8", str(REPO / "skills/session-distiller/scripts/worker.py")],
            env={**env, "DISTILLER_CMD": str(stub_ok)})
    check("worker/stale-lock-recovered", not (q / "jobs.jsonl").read_text(encoding="utf-8").strip())

    print("[5] 反馈脱敏 / extract 截断")
    sys.path.insert(0, str(REPO / "skills/ai-infra-feedback/scripts"))
    import collections
    import feedback
    hits = collections.Counter()
    out = feedback.redact_obj({"extra": {"API_KEY": "SYNTHETIC_OPAQUE"},
                               "text": 'password="two word synthetic" github_pat_' + "A" * 30,
                               "token_count": 3}, hits)
    check("feedback/key-redacted", out["extra"]["API_KEY"] == "[REDACTED:secret]")
    check("feedback/quoted-password-redacted", "two word synthetic" not in out["text"])
    check("feedback/github-pat-redacted", "github_pat_" not in out["text"])
    check("feedback/token-count-not-false-positive", out["token_count"] == 3)
    ex_home = TMP / "ex-home"; pdir = ex_home / ".claude/projects/proj"; pdir.mkdir(parents=True)
    big_in = "A" * 4100 + "TAIL_INPUT"; big_out = "B" * 20100 + "TAIL_RESULT"
    write(pdir / "sess.jsonl", "\n".join([
        json.dumps({"type": "assistant", "message": {"content": [
            {"type": "tool_use", "id": "toolu_x", "name": "Bash", "input": {"command": big_in}}]}}),
        json.dumps({"type": "user", "message": {"content": [
            {"type": "tool_result", "tool_use_id": "toolu_x", "content": big_out}]}})]) + "\n")
    r = run(["bash", str(REPO / "skills/session-distiller/scripts/extract.sh"), "sess",
             "--level", "3", "--tool-id", "toolu_x"], env={"HOME": str(ex_home), "USERPROFILE": str(ex_home)})
    check("extract/truncation-marker", "TRUNCATED input:" in r.stdout and "TRUNCATED result:" in r.stdout)

    print("[6] 门禁")
    g = [PY, "-X", "utf8", str(REPO / "gates/gate.py")]
    r = run(g + ["record", "--assets-repo", str(assets_repo), "--asset-id", ASSET_ID])
    check("gate/record-binding", r.returncode == 0, r.stdout[-300:])
    write(TMP / "req.md", "requirement card\n")
    plan = {"goal": "完成一个可验证的测试目标", "constraints": ["c"], "inputs": ["i"],
            "outputs": ["o"], "boundaries": ["b"], "acceptance": ["a"],
            "human_gates": ["h"], "version": "1",
            "requirement_card": {"path": "req.md", "sha256": sha_raw(TMP / "req.md")},
            "acceptance_criteria_hash": hashlib.sha256(json.dumps(
                ["a"], sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    pfile = TMP / "plan.json"; write(pfile, json.dumps(plan, ensure_ascii=False))
    r = run(g + ["plan", "--file", str(pfile), "--require-approval"])
    check("gate/plan-without-approval-rejected", r.returncode != 0)
    base = {k: v for k, v in plan.items()}
    digest = hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    plan["approval"] = {"approver": "Tester", "approved_at": "2026-10-24",
                        "scope_hash": digest, "decision": "approved"}
    write(pfile, json.dumps(plan, ensure_ascii=False))
    r = run(g + ["plan", "--file", str(pfile), "--require-approval"])
    check("gate/plan-hash-bound", r.returncode == 0, r.stdout[-300:])
    plan["goal"] = "变更后的目标，应该使旧批准失效"
    write(pfile, json.dumps(plan, ensure_ascii=False))
    r = run(g + ["plan", "--file", str(pfile), "--require-approval"])
    check("gate/plan-change-invalidates-approval", r.returncode != 0)
    task = {"task_id": "T1", "acceptance_criteria": [
        {"id": "AC-1", "description": "d", "expected": "x", "evidence_path": "plan.json",
         "check_method": "manual", "check_script": "", "independent_review": True,
         "severity": "major"}]}
    tfile = TMP / "task.json"; write(tfile, json.dumps(task, ensure_ascii=False))
    write(TMP / "self.txt", "self review\n")
    write(TMP / "art.txt", "artifact\n")
    checklist = hashlib.sha256(json.dumps(task["acceptance_criteria"], sort_keys=True,
                                           ensure_ascii=False).encode()).hexdigest()
    acc = {"task_id": "T1", "task_package": "task.json",
           "task_package_sha256": sha_raw(tfile), "checklist_hash": checklist,
           "criteria": [{"id": "AC-1", "expected": "x", "check_method": "manual",
                         "evidence_path": "plan.json", "evidence_sha256": sha_raw(pfile),
                         "result": "pass"}], "verdict": "pass",
           "reviewer": "same", "executor": "same", "independent": True,
           "reviewer_run_id": "run-r", "executor_run_id": "run-e",
           "reviewed_at": "2026-10-24",
           "reviewer_inputs": [{"path": name, "sha256": sha_raw(TMP / name)}
                               for name in ("task.json", "plan.json", "self.txt", "art.txt")],
           "self_review": {"result": "pass", "evidence_path": "self.txt",
                           "evidence_sha256": sha_raw(TMP / "self.txt")},
           "artifact_sha256": {"art.txt": sha_raw(TMP / "art.txt")}}
    afile = TMP / "acceptance.json"; write(afile, json.dumps(acc, ensure_ascii=False))
    r = run(g + ["acceptance", "--file", str(afile), "--base-dir", str(TMP)])
    check("gate/acceptance-self-review-rejected", r.returncode != 0)
    acc["reviewer"] = "other"
    write(afile, json.dumps(acc, ensure_ascii=False))
    r = run(g + ["acceptance", "--file", str(afile), "--base-dir", str(TMP)])
    check("gate/acceptance-independent-pass", r.returncode == 0, r.stdout[-300:])
    write(TMP / "plan.json", "changed\n")
    r = run(g + ["acceptance", "--file", str(afile), "--base-dir", str(TMP)])
    check("gate/acceptance-stale-evidence-rejected", r.returncode != 0)
    write(pfile, json.dumps(plan, ensure_ascii=False))
    # external-write deny then approve
    env_ap = {"AI_GATE_APPROVAL_DIR": str(TMP / "approvals"),
              "AI_GATE_AUDIT_LOG": str(TMP / "audit.jsonl")}
    hook_in = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}})
    r = run(g + ["external-write"], env=env_ap, input_text=hook_in)
    check("gate/external-write-deny", '"permissionDecision": "deny"' in r.stdout, r.stdout)
    r = run(g + ["approve", "--command", "git push origin main", "--by", "Tester", "--minutes", "30"],
            env=env_ap)
    r = run(g + ["external-write"], env=env_ap, input_text=hook_in)
    check("gate/external-write-approved", '"permissionDecision": "allow"' in r.stdout, r.stdout)
    r = run(g + ["component-registry", "--repo", str(REPO)])
    check("gate/component-registry", r.returncode == 0, r.stdout[-300:])

    print("[7] 复审 R01–R25 回归")
    # R01/R03 外发覆盖与失败关闭
    for cmd, expect_deny in [
        ("git -C /tmp/x push origin main", True),
        ("curl --data x https://example.com", True),
        ("python -c \"import requests; requests.post('http://x')\"", True),
        ("curl https://example.com", False),
    ]:
        r = run(g + ["external-write", "--command", cmd], env=env_ap)
        check(f"gate/external/{cmd[:18]}", (r.returncode != 0) == expect_deny,
              f"exit={r.returncode}")
    mcp = json.dumps({"tool_name": "mcp__github__push_files", "tool_input": {"x": 1}})
    r = run(g + ["external-write"], env=env_ap, input_text=mcp)
    check("gate/external/mcp-write-denied", '"permissionDecision": "deny"' in r.stdout)
    r = run(g + ["external-write"], env=env_ap, input_text="{invalid")
    check("gate/external/bad-json-fail-closed",
          '"permissionDecision": "deny"' in r.stdout and r.returncode == 0, r.stdout)

    # R02 签名批准（临时 key；生产由人持口令私钥）
    apdir = TMP / "signed-approvals"; apdir.mkdir()
    key = TMP / "approval_key"
    import shutil as _sh
    if _sh.which("ssh-keygen"):
        run(["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(key), "-q"])
        pub = Path(str(key) + ".pub").read_text(encoding="utf-8").strip()
        (apdir / "allowed_signers").write_text(f"tester {pub}\n", encoding="utf-8")
        env_sig = {"AI_GATE_APPROVAL_DIR": str(apdir),
                   "AI_GATE_APPROVAL_KEY": str(key),
                   "AI_GATE_ALLOWED_SIGNERS": str(apdir / "allowed_signers"),
                   "AI_GATE_AUDIT_LOG": str(TMP / "audit-sig.jsonl")}
        hook = json.dumps({"tool_name": "Bash", "tool_input": {"command": "git push origin main"}})
        r = run(g + ["approve", "--command", "git push origin main", "--by", "tester",
                     "--minutes", "5"], env=env_sig)
        check("gate/approve-signed", r.returncode == 0, r.stdout[-200:])
        r = run(g + ["external-write"], env=env_sig, input_text=hook)
        check("gate/signed-approval-allows", '"permissionDecision": "allow"' in r.stdout)
        ap = next(apdir.glob("*.json"))
        ap.write_text(ap.read_text(encoding="utf-8").replace("tester", "mallory", 1),
                      encoding="utf-8")
        r = run(g + ["external-write"], env=env_sig, input_text=hook)
        check("gate/tampered-approval-denied", '"permissionDecision": "deny"' in r.stdout)

    # R04 计划占位/拒绝批准
    badplan = {"goal": "完成一个可验证的测试目标", "constraints": [None], "inputs": ["i"],
               "outputs": ["o"], "boundaries": ["b"], "acceptance": ["a"],
               "human_gates": ["h"], "version": "1"}
    write(TMP / "badplan.json", json.dumps(badplan, ensure_ascii=False))
    r = run(g + ["plan", "--file", str(TMP / "badplan.json")])
    check("gate/plan-null-items-rejected", r.returncode != 0)
    reject = dict(plan); reject["approval"] = {"approver": "Tester", "approved_at": "2026-10-24",
        "scope_hash": hashlib.sha256(json.dumps({k: v for k, v in reject.items() if k != "approval"},
        sort_keys=True, ensure_ascii=False).encode()).hexdigest(), "decision": "rejected"}
    write(TMP / "rejectplan.json", json.dumps(reject, ensure_ascii=False))
    r = run(g + ["plan", "--file", str(TMP / "rejectplan.json"), "--require-approval"])
    check("gate/plan-rejected-approval-rejected", r.returncode != 0)

    # R05 验收与任务包/证据绑定
    acc2 = json.loads(json.dumps(acc)); acc2["criteria"][0]["id"] = "AC-OTHER"
    write(TMP / "acc2.json", json.dumps(acc2, ensure_ascii=False))
    r = run(g + ["acceptance", "--file", str(TMP / "acc2.json"), "--base-dir", str(TMP)])
    check("gate/acceptance-wrong-ac-rejected", r.returncode != 0)
    acc3 = json.loads(json.dumps(acc)); acc3["reviewer"] = ""
    write(TMP / "acc3.json", json.dumps(acc3, ensure_ascii=False))
    r = run(g + ["acceptance", "--file", str(TMP / "acc3.json"), "--base-dir", str(TMP)])
    check("gate/acceptance-empty-reviewer-rejected", r.returncode != 0)

    # R08 A 重复项目/domains 标量；R10 长单行/日期+Speaker
    for variant, expect in [("dup_project", 1), ("domains_scalar", 1),
                            ("raw_long", 1), ("raw_date_speaker", 1)]:
        d = make_proposal(TMP / f"p2-{variant}", variant)
        r = run([PY, "-X", "utf8", str(REPO / "skills/assetize/scripts/validate.py"), str(d)])
        check(f"A/reaudit/{variant}", r.returncode == expect,
              f"exit={r.returncode} expected={expect}\n{r.stdout[-300:]}")

    # R06/R09 B 审批、分类与来源
    ar2 = TMP / "assets-repo2"; ar2.mkdir()
    make_assets_repo(ar2)
    b2, m2 = make_build(TMP / "b2", ar2)
    ap2 = ar2 / "approvals" / f"{ASSET_ID}.json"
    bak = ap2.read_text(encoding="utf-8")
    ap2.unlink()
    r = run_b(b2, ar2, release=True)
    check("B/reaudit/no-approval-rejected", r.returncode != 0)
    a2 = json.loads(bak); a2["decision"] = "rejected"
    write(ap2, json.dumps(a2, ensure_ascii=False, indent=2))
    r = run_b(b2, ar2, release=True)
    check("B/reaudit/rejected-approval-rejected", r.returncode != 0)
    a2["decision"] = "approved"; write(ap2, json.dumps(a2, ensure_ascii=False, indent=2))
    m3 = json.loads(json.dumps(m2)); m3["asset_type"] = "hook"
    write(b2 / "build-manifest.json", json.dumps(m3, ensure_ascii=False, indent=2))
    r = run_b(b2, ar2)
    check("B/reaudit/classification-mismatch-rejected", r.returncode != 0)
    write(b2 / "build-manifest.json", json.dumps(m2, ensure_ascii=False, indent=2))
    art = b2 / "artifacts" / "memory.md"
    art.write_text(art.read_text(encoding="utf-8").replace(
        "这是实现正文，足够长。", "2026-10-20 12:00:00 DEBUG " + "x" * 200), encoding="utf-8")
    r = run_b(b2, ar2)
    check("B/reaudit/raw-long-line-rejected", r.returncode != 0)
    art.write_text(art.read_text(encoding="utf-8").replace(
        "2026-10-20 12:00:00 DEBUG " + "x" * 200,
        "2026-10-20 10:00:00 Speaker A: hello\n2026-10-20 10:00:05 Speaker B: hi"),
        encoding="utf-8")
    r = run_b(b2, ar2)
    check("B/reaudit/raw-date-speaker-rejected", r.returncode != 0)

    # R11 任务依赖/独立复核
    sys.path.insert(0, str(REPO / "skills/orchestrator/scripts"))
    import task_packager as tp2
    td = TMP / "tasks2"; td.mkdir()
    main = tp2.create_task_package("m", "d", "script")
    main["execution"]["target"] = str(REPO / "skills/orchestrator/scripts/task_packager.py")
    main["acceptance_criteria"][0].update({"expected": "ok", "evidence_path": "o",
                                           "independent_review": True})
    main["dependencies"] = ["T-DEP"]
    dep = json.loads(json.dumps(main)); dep["task_id"] = "T-DEP"; dep["dependencies"] = []
    dep["metadata"]["status"] = "blocked"
    write(td / "main.json", json.dumps(main, ensure_ascii=False))
    write(td / "dep.json", json.dumps(dep, ensure_ascii=False))
    r = run([PY, "-X", "utf8", str(REPO / "skills/orchestrator/scripts/task_packager.py"),
             "validate", str(td / "main.json"), "--strict", "--tasks-dir", str(td)])
    check("task/reaudit/blocked-dependency-rejected", r.returncode != 0)
    dep["metadata"]["status"] = "done"; write(td / "dep.json", json.dumps(dep, ensure_ascii=False))
    r = run([PY, "-X", "utf8", str(REPO / "skills/orchestrator/scripts/task_packager.py"),
             "validate", str(td / "main.json"), "--strict", "--tasks-dir", str(td)])
    check("task/reaudit/done-dependency-accepted", r.returncode == 0, r.stdout[-300:])
    noind = json.loads(json.dumps(main)); noind["dependencies"] = []
    noind["task_id"] = "T-NOIND"
    noind["acceptance_criteria"][0].update({"independent_review": False, "severity": "major"})
    write(td / "noind.json", json.dumps(noind, ensure_ascii=False))
    r = run([PY, "-X", "utf8", str(REPO / "skills/orchestrator/scripts/task_packager.py"),
             "validate", str(td / "noind.json"), "--strict"])
    check("task/reaudit/no-independent-review-rejected", r.returncode != 0)

    # R17 producer 在锁被占用时仍不丢任务
    q2 = home / ".claude/self-evolve/queue"; clear_queue(home)
    hold_script = TMP / "hold_lock.py"
    write(hold_script, (
        "import os,sys,time\n"
        "p=sys.argv[1]\n"
        "f=open(p,'a+')\n"
        "if os.name=='nt':\n"
        " import msvcrt; f.seek(0); msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)\n"
        "else:\n"
        " import fcntl; fcntl.flock(f.fileno(), fcntl.LOCK_EX|fcntl.LOCK_NB)\n"
        "print('locked', flush=True)\n"
        "time.sleep(6)\n"))
    holder = subprocess.Popen([PY, "-X", "utf8", str(hold_script), str(q2 / ".queue.lock")],
                              stdout=subprocess.PIPE, text=True)
    holder.stdout.readline()
    r = run([PY, "-X", "utf8", str(REPO / "hooks/self-evolve/enqueue.py")], env=env,
            input_text=json.dumps({"session_id": "s-lock", "transcript_path": str(tr)}))
    holder.terminate()
    try:
        holder.wait(timeout=5)
    except Exception:
        holder.kill()
    check("enqueue/reaudit/lock-held-task-not-lost",
          any(j.get("session_id") == "s-lock" for j in queue_jobs(home)))

    # R18/R21 引号/JSON 秘密与非法 lane
    clear_queue(home)
    for name, payload in [
        ("quoted", '[{"lane":"rules","title":"t","content":"password=\\"two word synthetic\\"","reason":"r"}]'),
        ("json", '[{"lane":"rules","title":"t","content":"{\\"api_key\\":\\"SYNTHETIC_VALUE\\"}","reason":"r"}]'),
        ("lane", '[{"lane":[],"title":"t","content":"a sufficiently long content body","reason":"r"}]'),
    ]:
        stub = TMP / f"stub_{name}.py"
        write(stub, "print(" + repr(payload) + ")\n")
        write(q2 / "jobs.jsonl", json.dumps({"session_id": f"s-{name}",
              "transcript_path": str(tr), "enqueued_at": 10}) + "\n")
        r = run([PY, "-X", "utf8", str(REPO / "skills/session-distiller/scripts/worker.py")],
                env={**env, "DISTILLER_CMD": str(stub), "MAX_JOBS_PER_DAY": "100"})
        staged = list((home / ".claude/self-evolve/staging").glob("cand-*.md"))
        check(f"worker/reaudit/{name}-not-staged", not staged and r.returncode == 0,
              f"exit={r.returncode} staged={staged}")

    # R19 处理期间追加 tail 不确认完成
    clear_queue(home)
    tail_stub = TMP / "stub_tail.py"
    write(tail_stub, (
        "import json,os\n"
        "from pathlib import Path\n"
        "p=Path(os.environ['TAIL_FILE'])\n"
        "p.write_text(p.read_text(encoding='utf-8')+'\\n'+json.dumps({'type':'user','message':{'content':'TAIL'}})+'\\n',encoding='utf-8')\n"
        "print('[]')\n"))
    write(q2 / "jobs.jsonl", json.dumps({"session_id": "s-tail", "transcript_path": str(tr),
                                          "enqueued_at": 11}) + "\n")
    cursor = home / ".claude/self-evolve/distill-state/s-tail.json"
    cursor.unlink(missing_ok=True)
    r = run([PY, "-X", "utf8", str(REPO / "skills/session-distiller/scripts/worker.py")],
            env={**env, "DISTILLER_CMD": str(tail_stub), "TAIL_FILE": str(tr),
                 "MAX_JOBS_PER_DAY": "100"})
    cur = json.load(open(cursor, encoding="utf-8")) if cursor.exists() else {}
    check("worker/reaudit/tail-not-marked-done",
          cur.get("status") == "stale-input" and
          any(j.get("session_id") == "s-tail" for j in queue_jobs(home)),
          f"cursor={cur.get('status')}")

    # R20 嵌套 environment 脱敏
    sys.path.insert(0, str(REPO / "skills/ai-infra-feedback/scripts"))
    import importlib
    import feedback as fb
    importlib.reload(fb)
    hits = collections.Counter()
    nested = fb.redact_obj({"environment": {"nested": {"token": "SYNTHETIC_TOKEN"}}}, hits)
    check("feedback/reaudit/nested-secret-redacted",
          "SYNTHETIC_TOKEN" not in json.dumps(nested), nested)

    # R22 extract --max-input=N
    r = run(["bash", str(REPO / "skills/session-distiller/scripts/extract.sh"), "sess",
             "--level", "3", "--tool-id", "toolu_x", "--max-input=50000",
             "--max-result=50000"], env={"HOME": str(ex_home), "USERPROFILE": str(ex_home)})
    check("extract/reaudit/equals-max-args", "TRUNCATED" not in r.stdout, r.stdout[-200:])

    print("[8] 第三轮 T01–T14 回归")
    # T01 未知 MCP/脚本 HTTP 默认拒绝，只读 MCP 放行
    for name, hook_obj, want_allow in [
        ("batch-update", {"tool_name": "mcp__github__batch_update", "tool_input": {"x": 1}}, False),
        ("set-permissions", {"tool_name": "mcp__github__set_permissions", "tool_input": {"x": 1}}, False),
        ("unknown-mcp", {"tool_name": "mcp__vendor__frobnicate", "tool_input": {"x": 1}}, False),
        ("read-mcp", {"tool_name": "mcp__github__get_file_contents",
                      "tool_input": {"path": "a"}}, True),
        ("missing-command", {"tool_name": "Bash", "tool_input": {}}, False),
        ("missing-tool", {"tool_input": {"command": "echo hi"}}, False),
    ]:
        r = run(g + ["external-write"], env=env_ap,
                input_text=json.dumps(hook_obj, ensure_ascii=False))
        got = '"permissionDecision": "allow"' in r.stdout
        check(f"gate/external3/{name}", got == want_allow, r.stdout[-300:])
    r = run(g + ["external-write", "--command",
                 "python -c \"import httpx; httpx.post('http://x')\""], env=env_ap)
    check("gate/external3/httpx-denied", r.returncode != 0, r.stdout[-200:])

    # T02 显式签名策略缺失时失败关闭
    env_missing = {"AI_GATE_APPROVAL_DIR": str(TMP / "ap-missing"),
                   "AI_GATE_ALLOWED_SIGNERS": str(TMP / "missing-signers"),
                   "AI_GATE_AUDIT_LOG": str(TMP / "audit-missing.jsonl")}
    r = run(g + ["approve", "--command", "git push origin main", "--by", "tester"],
            env=env_missing)
    check("gate/signature3/missing-policy-approve-denied", r.returncode != 0, r.stdout[-200:])
    r = run(g + ["external-write"], env=env_missing, input_text=hook_in)
    check("gate/signature3/missing-policy-deny", '"permissionDecision": "deny"' in r.stdout,
          r.stdout[-300:])
    r = run(g + ["security-status"], env=env_missing)
    check("gate/signature3/status-fails", r.returncode != 0, r.stdout[-200:])

    # T03/T04 验收指定证据、必交付、finding 与 run 身份
    adir = TMP / "acc3"; adir.mkdir()
    task3 = {"task_id": "T3",
             "output_contract": {"primary": {"type": "file", "location": "required.txt"}},
             "acceptance_criteria": [{"id": "AC-1", "expected": "ok", "evidence_path": "ev.txt",
                                      "check_method": "manual", "independent_review": True,
                                      "severity": "major"}]}
    write(adir / "task.json", json.dumps(task3, ensure_ascii=False))
    write(adir / "ev.txt", "evidence\n"); write(adir / "other.txt", "other\n")
    write(adir / "self.txt", "self\n"); write(adir / "required.txt", "required\n")
    def acc3(evidence="ev.txt", extra_artifact=None, findings=None, same_run=False):
        return {"task_id": "T3", "task_package": "task.json",
                "task_package_sha256": sha_raw(adir / "task.json"),
                "checklist_hash": hashlib.sha256(json.dumps(
                    task3["acceptance_criteria"], sort_keys=True,
                    ensure_ascii=False).encode()).hexdigest(),
                "criteria": [{"id": "AC-1", "expected": "ok", "check_method": "manual",
                              "evidence_path": evidence,
                              "evidence_sha256": sha_raw(adir / evidence),
                              "result": "pass"}],
                "verdict": "pass", "reviewer": "rev", "executor": "exec",
                "reviewer_run_id": "run-r" if not same_run else "run-e",
                "executor_run_id": "run-e", "independent": True,
                "reviewed_at": "2026-10-24",
                "reviewer_inputs": [{"path": p, "sha256": sha_raw(adir / p)}
                                    for p in ("task.json", "ev.txt", "self.txt",
                                              "required.txt", "other.txt")],
                "self_review": {"result": "pass", "evidence_path": "self.txt",
                                "evidence_sha256": sha_raw(adir / "self.txt"),
                                "findings": findings or []},
                "artifact_sha256": {"required.txt": sha_raw(adir / "required.txt")}
                if extra_artifact is None else {"other.txt": sha_raw(adir / "other.txt")}}
    def run_acc(obj, name):
        p = adir / name; write(p, json.dumps(obj, ensure_ascii=False))
        return run(g + ["acceptance", "--file", str(p), "--base-dir", str(adir)])
    r = run_acc(acc3(), "ok.json")
    check("gate/acceptance3/control-pass", r.returncode == 0, r.stdout[-300:])
    r = run_acc(acc3(evidence="other.txt"), "swap-evidence.json")
    check("gate/acceptance3/replace-evidence-rejected", r.returncode != 0, r.stdout[-200:])
    r = run_acc(acc3(extra_artifact=True), "omit-artifact.json")
    check("gate/acceptance3/omit-required-artifact-rejected", r.returncode != 0, r.stdout[-200:])
    r = run_acc(acc3(findings=[{"id": "F1", "severity": "major",
                                "disposition": "open"}]), "open-finding.json")
    check("gate/acceptance3/open-finding-rejected", r.returncode != 0, r.stdout[-200:])
    r = run_acc(acc3(same_run=True), "same-run.json")
    check("gate/acceptance3/same-run-rejected", r.returncode != 0, r.stdout[-200:])

    # T05 结构化计划 AC + 需求卡 hash
    req3 = TMP / "req3.md"; write(req3, "requirement card 3\n")
    acc_items = [{"id": "AC-1", "check_method": "manual", "expected": "ok",
                  "evidence": "ev.txt"}]
    plan3 = {"goal": "第三轮计划门禁测试目标", "constraints": ["c"], "inputs": ["i"],
             "outputs": ["o"], "boundaries": ["b"], "acceptance": acc_items,
             "human_gates": ["h"], "version": "3",
             "requirement_card": {"path": "req3.md", "sha256": sha_raw(req3)},
             "acceptance_criteria_hash": hashlib.sha256(json.dumps(
                 acc_items, sort_keys=True, ensure_ascii=False).encode()).hexdigest()}
    p3 = TMP / "plan3.json"; write(p3, json.dumps(plan3, ensure_ascii=False))
    r = run(g + ["plan", "--file", str(p3)])
    check("gate/plan3/structured-accepted", r.returncode == 0, r.stdout[-300:])
    bad3 = json.loads(json.dumps(plan3)); bad3["acceptance_criteria_hash"] = "0" * 64
    write(p3, json.dumps(bad3, ensure_ascii=False))
    r = run(g + ["plan", "--file", str(p3)])
    check("gate/plan3/criteria-hash-mismatch-rejected", r.returncode != 0)

    # T06 Memory provenance/owner/raw
    mem = TMP / "mem3.md"
    write(mem, "---\nprovenance_status: totally-invalid\n---\n结论正文\n")
    r = run(g + ["memory", "--file", str(mem), "--require-provenance"], env=env_ap)
    check("gate/memory3/invalid-provenance-rejected", r.returncode != 0)
    write(mem, "---\nprovenance_status: verified\nowner: tester\nsource: doc\nlayer: 项目级\n---\n结论正文\n")
    r = run(g + ["memory", "--file", str(mem), "--require-provenance"], env=env_ap)
    check("gate/memory3/valid-accepted", r.returncode == 0, r.stdout[-200:])
    write(mem, "---\nprovenance_status: verified\nowner: tester\nsource: doc\nlayer: 项目级\n---\n"
              "2026-10-20 10:00:00 Speaker A: hello\n")
    r = run(g + ["memory", "--file", str(mem), "--require-provenance"], env=env_ap)
    check("gate/memory3/raw-rejected", r.returncode != 0)

    # T11 公共入口漏登记
    gcopy = TMP / "gcopy"
    shutil.copytree(REPO, gcopy, ignore=shutil.ignore_patterns(".git", "__pycache__"))
    write(gcopy / "rules" / "zz-unregistered.md",
          "---\nname: zz\n---\n# unregistered\n")
    r = run([PY, "-X", "utf8", str(gcopy / "gates/gate.py"), "component-registry",
             "--repo", str(gcopy)])
    check("gate/registry3/unregistered-public-rule-rejected", r.returncode != 0,
          r.stdout[-300:])

    # E01 promotion 检查
    prepo = TMP / "promo-repo"; (prepo / "rules").mkdir(parents=True)
    write(prepo / "rules" / "x.md", "# x\n")
    run(["git", "-C", str(prepo), "init", "-q"])
    run(["git", "-C", str(prepo), "-c", "user.email=t@x", "-c", "user.name=t",
         "add", "."])
    run(["git", "-C", str(prepo), "-c", "user.email=t@x", "-c", "user.name=t",
         "commit", "-q", "-m", "init"])
    head = subprocess.run(["git", "-C", str(prepo), "rev-parse", "HEAD"],
                          capture_output=True, text=True).stdout.strip()
    ev3 = TMP / "promo-ev.txt"; write(ev3, "evidence\n")
    promo = {"schema_version": "1", "candidate_id": "cand-1",
             "session_ids": ["s1", "s2"],
             "evidence": [{"path": str(ev3), "sha256": sha_raw(ev3)}],
             "failure_modes": ["重复踩坑"], "owner": "tester",
             "scope": {"type": "rule", "path": "rules/x.md"},
             "git": {"repo": str(prepo), "commit": head, "clean": True},
             "target_path": "rules/x.md", "status": "proposed"}
    pf = TMP / "promotion.json"; write(pf, json.dumps(promo, ensure_ascii=False))
    r = run(g + ["promotion", "--file", str(pf)], env=env_ap)
    check("gate/promotion3/valid-accepted", r.returncode == 0, r.stdout[-300:])
    write(prepo / "dirty.txt", "dirty\n")
    r = run(g + ["promotion", "--file", str(pf)], env=env_ap)
    check("gate/promotion3/dirty-git-rejected", r.returncode != 0, r.stdout[-200:])

    # T12/T13 Skill 语义任务与 blocker-only 独立复核
    pkg = json.loads(json.dumps(tp_base))
    pkg["execution"] = {"type": "skill", "target": "grill-me-with-doc",
                        "timeout_seconds": 60, "model": "GLM-5.3"}
    pkg["metadata"]["task_class"] = "judgment"
    pfile2 = TMP / "tp-skill.json"; write(pfile2, json.dumps(pkg, ensure_ascii=False))
    check("task/routing3/skill-judgment-accepted",
          tp.validate_task_package(str(pfile2), strict=True))
    pkg2 = json.loads(json.dumps(tp_base))
    pkg2["acceptance_criteria"][0]["severity"] = "blocker"
    pkg2["acceptance_criteria"][0]["independent_review"] = True
    pfile3 = TMP / "tp-blocker.json"; write(pfile3, json.dumps(pkg2, ensure_ascii=False))
    check("task/routing3/blocker-only-independent-accepted",
          tp.validate_task_package(str(pfile3), strict=True))

    # P01/P02 timeout 持久化 + 空输出 dead-letter
    clear_queue(home)
    slow = TMP / "slow_model.py"
    write(slow, "import time\ntime.sleep(5)\nprint('[]')\n")
    calls = TMP / "calls.txt"
    fast = TMP / "fast_model.py"
    write(fast, "import os\nopen(os.environ['CALLS'],'a').write('1')\nprint('[]')\n")
    write(q2 / "jobs.jsonl", json.dumps({"session_id": "s-timeout",
          "transcript_path": str(tr), "enqueued_at": 20}) + "\n")
    run([PY, "-X", "utf8", str(REPO / "skills/session-distiller/scripts/worker.py"),
         "--timeout", "1"], env={**env, "DISTILLER_CMD": str(slow),
                                 "MAX_JOBS_PER_DAY": "100"})
    state = json.load(open(home / ".claude/self-evolve/queue/worker-state.json",
                           encoding="utf-8")) if (home / ".claude/self-evolve/queue/worker-state.json").exists() else {}
    # state 实际路径由 worker 决定，改用 cursor 检查
    cur = home / ".claude/self-evolve/distill-state/s-timeout.json"
    check("worker/timeout3/state-failed",
          cur.exists() and json.load(open(cur, encoding="utf-8")).get("status") == "failed",
          cur)
    run([PY, "-X", "utf8", str(REPO / "skills/session-distiller/scripts/worker.py")],
        env={**env, "DISTILLER_CMD": str(fast), "CALLS": str(calls),
             "MAX_JOBS_PER_DAY": "100"})
    check("worker/timeout3/immediate-retry-calls-model",
          calls.exists() and calls.read_text() == "1", calls)

    clear_queue(home)
    empty = TMP / "empty_model.py"; write(empty, "print('')\n")
    write(q2 / "jobs.jsonl", json.dumps({"session_id": "s-empty",
          "transcript_path": str(tr), "enqueued_at": 21}) + "\n")
    for i in range(3):
        run([PY, "-X", "utf8", str(REPO / "skills/session-distiller/scripts/worker.py")],
            env={**env, "DISTILLER_CMD": str(empty), "MAX_JOBS_PER_DAY": "100"})
    dl = q2 / "dead-letter.jsonl"
    check("worker/empty3/dead-letter-after-3",
          dl.exists() and "s-empty" in dl.read_text(encoding="utf-8"), dl)

    # T14 审计关联字段、连续拒绝升级与审计写失败失败关闭
    esc_cmd = "git push origin main"
    env_esc = {**env_ap, "AI_GATE_SESSION_ID": "sess-esc",
               "AI_GATE_AUDIT_LOG": str(TMP / "audit-esc.jsonl"),
               "AI_GATE_APPROVAL_DIR": str(TMP / "ap-esc")}
    outs = [run(g + ["external-write", "--command", esc_cmd], env=env_esc).stdout
            for _ in range(3)]
    check("gate/audit3/third-deny-escalates", "升级" in outs[2], outs[2][-300:])
    esc_lines = [json.loads(x) for x in
                 (TMP / "audit-esc.jsonl").read_text(encoding="utf-8").splitlines()
                 if x.strip()]
    last = esc_lines[-1] if esc_lines else {}
    check("gate/audit3/fields-present",
          all(k in last for k in ("session_id", "rule", "input_hash", "decision"))
          and last.get("session_id") == "sess-esc" and last.get("decision") == "deny",
          str(last)[-300:])
    blocked = TMP / "audit-blocked"; blocked.mkdir()
    r = run(g + ["record", "--assets-repo", str(assets_repo),
                 "--asset-id", "EA-20261022-99"],
            env={**env_ap, "AI_GATE_AUDIT_LOG": str(blocked)})
    check("gate/audit3/write-failure-fails-closed",
          r.returncode != 0 and "审计日志写入失败" in (r.stdout + r.stderr),
          (r.stdout + r.stderr)[-300:])

    print(f"\n结果: PASS={PASS} FAIL={FAIL}  (fixtures: {TMP})")
    if FAIL:
        print("保留 fixtures 供排查")
        return 1
    shutil.rmtree(TMP, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
