#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ark.py — 火山引擎方舟 Agent Plan LLM 调用 CLI

所有端点均经过实测验证（2026-09）。用 `endpoints` 子命令查看已验证/待探索能力清单，
用 `raw` 子命令对新端点做实验。仅依赖 Python 标准库。
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

BASE_URL = "https://ark.cn-beijing.volces.com/api/plan"
ZSHRC = os.path.expanduser("~/.zshrc")
DEFAULT_MODEL = "GLM-5.3-Flash"

# 实测确认可用的模型（全部为强制思考模型，思考不可关闭）
# 括号内为 Agent Plan AFP 抵扣系数（每百万 token 输入/输出，2026-09 查官方文档）
MODELS = {
    "GLM-5.3":          "智谱旗舰，质量最高（4.5/4.5）（Claude Code 中映射 Opus 档）",
    "GLM-5.3-Flash":    "智谱快速版，原生多模态支持图片输入，默认首选（0.5/0.5）",
    "GLM-5.3-Air":      "智谱轻量版（官方系数表未列出）",
    "GLM-5.2":          "智谱上一代旗舰（官方系数表未列出）",
    "MiniMax-M3":       "MiniMax 旗舰（2.5/2.5）（Sonnet 档）",
    "MiniMax-M3-Flash": "MiniMax 快速版（官方系数表未列出）",
    "Kimi-K3":          "月之暗面旗舰（10/10，套餐内最贵）",
    "Kimi-K3-Flash":    "月之暗面快速版（官方系数表未列出）",
    "Kimi-K2.8-preview": "月之暗面进阶（8/8，限时 4.8 至 09-30）",
    "Kimi-K2.7-code":   "月之暗面代码向（4.5/4.5，256k 窗口）",
    "DeepSeek-V4.1-Flash": "DeepSeek 快速版，原生视觉理解可图片输入（2.5/2.5，限时 1.25 至 09-28）",
    "DeepSeek-V4-Flash":   "DeepSeek 标准（0.5/0.5）",
    "DeepSeek-V4-Pro":     "DeepSeek 进阶（5.5/5.5）",
    "doubao-seed-2.0-mini":   "豆包极速，套餐内最便宜（0.25/0.25）",
    "doubao-seed-2.0-lite":   "豆包标准，支持图片输入（0.5/0.5，256k 窗口）",
    "doubao-seed-2.1-turbo":  "豆包进阶，支持图片输入（2.5/2.5，256k 窗口）",
    "doubao-seed-evolving":   "豆包进阶，支持图片输入（2.5/2.5，1024k 窗口）",
    "doubao-seed-2.0-code":   "豆包代码向，按输入长度分档计费（约 0.45-0.6 输入档）",
}

DOC_LINKS = {
    "Agent Plan 套餐概览": "https://www.volcengine.com/docs/82379/2366394",
    "方舟 API 参考（总目录）": "https://www.volcengine.com/docs/82379/1263279",
}


def resolve_key():
    """解析 API key：优先环境变量 ARK_API_KEY，其次从 ~/.zshrc 提取。"""
    key = os.environ.get("ARK_API_KEY", "").strip()
    if key:
        return key
    try:
        with open(ZSHRC, encoding="utf-8", errors="ignore") as f:
            for line in f:
                m = re.match(r'\s*(?:export\s+)?ARK_API_KEY=["\']?([^"\'\s]+)', line)
                if m:
                    return m.group(1).strip()
    except OSError:
        pass
    die("找不到 API key：环境变量 ARK_API_KEY 未设置，且 ~/.zshrc 中无此定义")


def die(msg, code=1):
    print(f"错误: {msg}", file=sys.stderr)
    sys.exit(code)


def http(method, path, body=None, key=None, stream=False, timeout=None):
    if timeout is None:  # 环境变量可覆盖；默认 180s，长输出任务用 ARK_TIMEOUT=900
        timeout = int(os.environ.get("ARK_TIMEOUT", 180))
    """向方舟端点发请求。path 形如 /v1/messages。返回 (status, response对象或dict)。"""
    url = path if path.startswith("http") else BASE_URL + path
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {key}"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        resp = urllib.request.urlopen(req, timeout=timeout)
    except urllib.error.HTTPError as e:
        payload = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(payload)
        except json.JSONDecodeError:
            return e.code, {"raw": payload}
    if stream:
        return resp.status, resp
    payload = resp.read().decode(errors="replace")
    try:
        return resp.status, json.loads(payload)
    except json.JSONDecodeError:
        return resp.status, {"raw": payload}


def extract_text(content_blocks):
    """从 Anthropic 格式 content 数组中拼接 text 块（忽略 thinking 块）。"""
    return "".join(b.get("text", "") for b in content_blocks if b.get("type") == "text")


def chat_once(model, messages, max_tokens, temperature=None, system=None, key=None):
    body = {"model": model, "max_tokens": max_tokens, "messages": messages}
    if system:
        body["system"] = system
    if temperature is not None:
        body["temperature"] = temperature
    status, data = http("POST", "/v1/messages", body, key=key)
    if status != 200:
        die(api_error(status, data))
    return data


def api_error(status, data):
    err = data.get("error", {}) if isinstance(data, dict) else {}
    code = err.get("code", "?")
    msg = err.get("message", json.dumps(data, ensure_ascii=False)[:300])
    hint = {
        "AuthenticationError": "key 无效或端点不对。确认用的是 BASE_URL=/api/plan（不是 /api/v3），key 来自 ARK_API_KEY",
        "UnsupportedModel": "该模型不在 Agent Plan 套餐内，用 `models` 子命令看已验证清单",
        "InvalidParameter": "参数不被支持，例如这些模型不支持 thinking.type=disabled",
    }.get(code, "")
    return f"HTTP {status} [{code}] {msg}" + (f"\n提示: {hint}" if hint else "")


def do_chat(args):
    key = resolve_key()
    prompt = " ".join(args.prompt) if args.prompt else sys.stdin.read()
    if not prompt.strip():
        die("prompt 为空：从参数传入，或用管道 echo '...' | ark.py chat")
    messages = [{"role": "user", "content": prompt}]
    if args.multi_turn:
        # -c 模式：prompt 用 "user:.../assistant:..." 分段（简单约定）
        messages = []
        for seg in re.split(r"\n(?=(?:user|assistant):)", prompt):
            role, _, text = seg.partition(":")
            if role.strip() in ("user", "assistant") and text:
                messages.append({"role": role.strip(), "content": text.strip()})
        messages = messages or [{"role": "user", "content": prompt}]
    data = chat_once(args.model, messages, args.max_tokens, args.temperature, args.system, key)
    if args.raw_json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
        return
    text = extract_text(data.get("content", []))
    if text:
        print(text)
    if data.get("stop_reason") == "max_tokens":
        warn = "（警告：stop_reason=max_tokens，输出可能被截断——这些模型强制思考，思考也消耗 max_tokens，建议调大 --max-tokens）"
        print(text + "\n" + warn, file=sys.stderr)
    usage = data.get("usage", {})
    if args.verbose:
        print(f"\n--- model={data.get('model')} stop={data.get('stop_reason')} "
              f"in={usage.get('input_tokens')} out={usage.get('output_tokens')} "
              f"cache_read={usage.get('cache_read_input_tokens')} ---", file=sys.stderr)


def do_stream(args):
    key = resolve_key()
    prompt = " ".join(args.prompt) if args.prompt else sys.stdin.read()
    body = {"model": args.model, "max_tokens": args.max_tokens, "stream": True,
            "messages": [{"role": "user", "content": prompt}]}
    if args.system:
        body["system"] = args.system
    status, resp = http("POST", "/v1/messages", body, key=key, stream=True)
    if status != 200:
        die(f"HTTP {status}: {resp.read().decode(errors='replace')[:300]}")
    for raw_line in resp:
        line = raw_line.decode(errors="replace").strip()
        if not line.startswith("data:"):
            continue
        try:
            evt = json.loads(line[5:])
        except json.JSONDecodeError:
            continue
        d = evt.get("delta", {})
        if evt.get("type") == "content_block_delta":
            if d.get("type") == "text_delta":
                print(d.get("text", ""), end="", flush=True)
            elif d.get("type") == "thinking_delta" and args.show_thinking:
                print(d.get("thinking", ""), end="", flush=True, file=sys.stderr)
        elif evt.get("type") == "message_delta" and args.show_thinking:
            print(f"\n[stop: {evt.get('delta', {}).get('stop_reason')}]", file=sys.stderr)
    print()


def do_models(args):
    if args.probe:
        key = resolve_key()
        print("逐个探测模型可用性（每个发一个 max_tokens=4 的最小请求）…")
        for m in MODELS:
            ok, info = probe_model(m, key)
            print(f"  {m}: {'✅ 可用' if ok else '❌ ' + info}")
        return
    print(f"Base URL: {BASE_URL}（Agent Plan 专用端点，通用 /api/v3 会 401）")
    print(f"默认模型: {DEFAULT_MODEL}\n")
    print("已实测可用的模型（全部强制思考，不可关闭）:")
    for m, desc in MODELS.items():
        print(f"  {m:<20} {desc}")
    print("\n探测新模型名是否可用: python3 ark.py probe <model-name>")


def probe_model(name, key):
    status, data = http("POST", "/v1/messages",
                        {"model": name, "max_tokens": 4, "messages": [{"role": "user", "content": "hi"}]},
                        key=key, timeout=60)
    if status == 200:
        return True, ""
    err = data.get("error", {}) if isinstance(data, dict) else {}
    return False, err.get("code", f"HTTP {status}")


def do_probe(args):
    key = resolve_key()
    ok, info = probe_model(args.model, key)
    print(f"{args.model}: {'✅ 可用' if ok else '❌ 不可用 (' + info + ')'}")
    sys.exit(0 if ok else 2)


def do_endpoints(args):
    print(f"""方舟 Agent Plan 端点能力清单（BASE_URL={BASE_URL}）

【已实测验证 ✅】
  POST /v1/messages            Anthropic Messages 协议。x-api-key 或 Bearer 认证均可，
                               anthropic-version 头可省略。本 CLI 的 chat/stream 即基于此。
  POST /v3/chat/completions    OpenAI 兼容协议，Bearer 认证。reasoning_content 字段
                               承载思考内容，content 为正文。
  流式输出 (SSE)               Anthropic 协议传 "stream": true，事件格式与官方一致。
  system / temperature         均有效。

【文档列出、但在 Plan 端点未验证 ⚠️】（探索时用 `raw` 子命令试，失败很正常）
  向量化 /v3/embeddings        路由存在（返回 UnsupportedModel 而非 404），但
                               doubao-embedding 不在套餐内；可用 raw 试其他
                               embedding 模型名    Files/缓存/Responses API 未验证
  图片/视频/3D 生成            独立计费能力，大概率不在套餐内

【不可用 ❌】
  GET  /v1/models, /v3/models  返回 404，Plan 端点没有模型列表接口，模型清单固化在本 CLI 的 models 子命令中

【需要 AK/SK 签名 🔐】（API key 不够，暂不覆盖）
  套餐用量查询、API Key 管理等管控面 API

【关键文档】""" + "".join(f"\n  {k}: {v}" for k, v in DOC_LINKS.items()))


def do_raw(args):
    """探索接口：对任意路径发请求，自动附带认证。"""
    key = resolve_key()
    body = json.loads(args.data) if args.data else None
    status, data = http(args.method.upper(), args.path, body, key=key, stream=args.stream, timeout=args.timeout)
    if args.stream and status == 200:
        for raw_line in data:
            print(raw_line.decode(errors="replace"), end="")
        return
    print(f"HTTP {status}")
    print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])


def main():
    p = argparse.ArgumentParser(
        prog="ark.py",
        description="火山方舟 Agent Plan LLM 调用 CLI（端点与模型均经实测验证）",
        epilog="示例:\n"
               "  python3 ark.py chat '用一句话介绍自己'\n"
               "  python3 ark.py chat -m GLM-5.3 -s '你是海盗' '打招呼'\n"
               "  echo '长文本...' | python3 ark.py chat --max-tokens 2048\n"
               "  python3 ark.py stream '讲个笑话'\n"
               "  python3 ark.py models          # 看可用模型\n"
               "  python3 ark.py probe Kimi-K3   # 探测某模型\n"
               "  python3 ark.py endpoints       # 能力清单与探索入口\n"
               "  python3 ark.py raw /v3/embeddings -d '{\"model\":\"...\",\"input\":[\"hi\"]}'\n",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    pc = sub.add_parser("chat", help="一次性对话（默认子命令）")
    pc.add_argument("prompt", nargs="*", help="提示词；留空则从 stdin 读")
    pc.add_argument("-m", "--model", default=DEFAULT_MODEL)
    pc.add_argument("-s", "--system", help="system 提示词")
    pc.add_argument("--max-tokens", type=int, default=1024,
                    help="默认 1024。思考模型思考也耗 token，短答也建议 ≥512")
    pc.add_argument("-t", "--temperature", type=float, default=None)
    pc.add_argument("-c", "--multi-turn", action="store_true",
                    help="prompt 按 'user:...\\nassistant:...' 分段构成多轮")
    pc.add_argument("--raw-json", action="store_true", help="输出完整 JSON 响应")
    pc.add_argument("-v", "--verbose", action="store_true", help="stderr 输出用量信息")
    pc.set_defaults(func=do_chat)

    ps = sub.add_parser("stream", help="流式对话（SSE，逐字输出）")
    ps.add_argument("prompt", nargs="*")
    ps.add_argument("-m", "--model", default=DEFAULT_MODEL)
    ps.add_argument("-s", "--system")
    ps.add_argument("--max-tokens", type=int, default=1024)
    ps.add_argument("--show-thinking", action="store_true", help="stderr 显示思考过程")
    ps.set_defaults(func=do_stream)

    pm = sub.add_parser("models", help="列出已验证可用的模型")
    pm.add_argument("--probe", action="store_true", help="现场逐个发请求复核可用性")
    pm.set_defaults(func=do_models)

    pp = sub.add_parser("probe", help="探测某个模型名是否可用")
    pp.add_argument("model")
    pp.set_defaults(func=do_probe)

    pe = sub.add_parser("endpoints", help="能力清单：已验证/待探索/不可用的端点与文档链接")
    pe.set_defaults(func=do_endpoints)

    pr = sub.add_parser("raw", help="原始请求（探索新端点用），自动附带认证")
    pr.add_argument("path", help="如 /v1/messages 或完整 URL")
    pr.add_argument("-d", "--data", help="JSON 请求体字符串")
    pr.add_argument("-X", "--method", default="POST")
    pr.add_argument("--stream", action="store_true", help="以 SSE 方式读取响应")
    pr.add_argument("--timeout", type=int, default=180)
    pr.set_defaults(func=do_raw)

    args = p.parse_args()
    if not args.cmd:
        p.print_help()
        return
    args.func(args)


if __name__ == "__main__":
    main()
