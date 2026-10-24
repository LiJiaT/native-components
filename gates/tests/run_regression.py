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


def dump_yaml(fm, body):
    import yaml
    return "---\n" + yaml.safe_dump(fm, allow_unicode=True, sort_keys=False).rstrip() + "\n---\n" + body


def write(p, text):
    p = Path(p)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


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
          "approved_at": "2026-10-22",
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
          dump_yaml({"asset_id": ASSET_ID, "provenance_status": fm["provenance_status"],
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
    m["tests"].append("results.json")
    write(bd / "build-manifest.json", json.dumps(m, ensure_ascii=False, indent=2))
    hashes = {p.name: sha(p) for p in (bd / "artifacts").glob("*")}
    write(bd / "tests" / "results.json", json.dumps({
        "result": "pass", "tested_at": "2026-10-24T10:00:00+08:00", "tested_by": "tester",
        "commands": [{"command": "true", "exit_code": 0}], "artifact_sha256": hashes},
        ensure_ascii=False, indent=2))
    write(bd / "review.json", json.dumps({
        "reviewer": "reviewer", "executor": "executor", "independent": True,
        "decision": "approved", "reviewed_at": "2026-10-24", "artifact_sha256": hashes,
        "checklist": [{"id": "x", "result": "pass"}]}, ensure_ascii=False, indent=2))
    r = run_b(bd, assets_repo, release=True)
    check("B/release-complete-accepted", r.returncode == 0, r.stdout[-400:])

    print("[3] 任务包 strict")
    sys.path.insert(0, str(REPO / "skills/orchestrator/scripts"))
    import task_packager as tp
    base = tp.create_task_package("t", "d", "script")
    base["execution"]["target"] = str(REPO / "skills/orchestrator/scripts/task_packager.py")
    base["acceptance_criteria"][0].update({"expected": "ok", "evidence_path": "out.log",
                                           "independent_review": True})
    def tp_check(name, mutate, expect_ok=False):
        pkg = json.loads(json.dumps(base)); mutate(pkg)
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
    jobs = (home / ".claude/self-evolve/queue/jobs.jsonl")
    enq_ok = False
    if jobs.exists():
        for line in jobs.read_text(encoding="utf-8").splitlines():
            try:
                enq_ok = Path(json.loads(line)["transcript_path"]).resolve() == tr.resolve()
            except Exception:
                pass
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
    check("enqueue/edits-only-qualifies", "s2" in jobs.read_text(encoding="utf-8"))

    # worker stubs
    stub_ok = TMP / "stub_ok.py"; write(stub_ok, "import sys\nprint('[]')\n")
    stub_fail = TMP / "stub_fail.py"; write(stub_fail, "import sys\nprint('[]')\nsys.stderr.write('ERR')\nsys.exit(7)\n")
    stub_bad = TMP / "stub_bad.py"; write(stub_bad, "import sys\nprint('[{\"lane\":\"BAD\",\"title\":\"\",\"content\":\"password=SYNTHETIC\",\"reason\":\"\"}]')\n")
    q = home / ".claude/self-evolve/queue"
    # reset queue to one job
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
    plan = {"goal": "完成一个可验证的测试目标", "constraints": ["c"], "inputs": ["i"],
            "outputs": ["o"], "boundaries": ["b"], "acceptance": ["a"],
            "human_gates": ["h"], "version": "1"}
    pfile = TMP / "plan.json"; write(pfile, json.dumps(plan, ensure_ascii=False))
    r = run(g + ["plan", "--file", str(pfile), "--require-approval"])
    check("gate/plan-without-approval-rejected", r.returncode != 0)
    base = {k: v for k, v in plan.items()}
    digest = hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    plan["approval"] = {"approver": "Tester", "approved_at": "2026-10-24", "scope_hash": digest}
    write(pfile, json.dumps(plan, ensure_ascii=False))
    r = run(g + ["plan", "--file", str(pfile), "--require-approval"])
    check("gate/plan-hash-bound", r.returncode == 0, r.stdout[-300:])
    plan["goal"] = "变更后的目标，应该使旧批准失效"
    write(pfile, json.dumps(plan, ensure_ascii=False))
    r = run(g + ["plan", "--file", str(pfile), "--require-approval"])
    check("gate/plan-change-invalidates-approval", r.returncode != 0)
    acc = {"task_id": "T1", "criteria": [{"id": "AC-1", "expected": "x",
            "evidence_path": "plan.json", "result": "pass"}], "verdict": "pass",
           "reviewer": "same", "executor": "same", "independent": True, "reviewed_at": "2026-10-24"}
    afile = TMP / "acceptance.json"; write(afile, json.dumps(acc, ensure_ascii=False))
    r = run(g + ["acceptance", "--file", str(afile), "--base-dir", str(TMP)])
    check("gate/acceptance-self-review-rejected", r.returncode != 0)
    acc["reviewer"] = "other"
    write(afile, json.dumps(acc, ensure_ascii=False))
    r = run(g + ["acceptance", "--file", str(afile), "--base-dir", str(TMP)])
    check("gate/acceptance-independent-pass", r.returncode == 0, r.stdout[-300:])
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

    print(f"\n结果: PASS={PASS} FAIL={FAIL}  (fixtures: {TMP})")
    if FAIL:
        print("保留 fixtures 供排查")
        return 1
    shutil.rmtree(TMP, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
