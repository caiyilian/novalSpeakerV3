#!/usr/bin/env python3
"""Multi-agent novel dialogue labeling V3 - with tool calling + detailed logging."""
import json
import os
import re
import sys
import urllib.request
import urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
OLLAMA_URL = "http://172.31.102.237:11434"
MODEL = "qwen3:32b"

SHORT_TERM_PATH = os.path.join(BASE, ".omo", "memory", "short_term.json")
LONG_TERM_PATH = os.path.join(BASE, ".omo", "memory", "long_term.json")
CHARACTERS_PATH = os.path.join(BASE, ".omo", "evidence", "characters.json")
PROGRESS_PATH = os.path.join(BASE, ".omo", "evidence", "progress.json")
NOVEL_PATH = os.path.join(BASE, "novel.txt")
LABELED_PATH = os.path.join(BASE, "labeled.txt")
LOG_PATH = os.path.join(BASE, ".omo", "logs", "session_log.jsonl")
TOOL_LOG_PATH = os.path.join(BASE, ".omo", "logs", "tool_calls.jsonl")

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

MAX_TOOL_CALLS = 10


def read_novel(start, end):
    with open(NOVEL_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    start = max(1, start); end = min(len(lines), end)
    text = "".join(lines[start-1:end])
    return f"--- 第{start}行到第{end}行 ---\n{text}\n--- {end-start+1}行 ---"


def search_novel(keyword, limit=10):
    results = []
    with open(NOVEL_PATH, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            if keyword in line:
                results.append(f"第{i}行：{line.strip()[:80]}")
                if len(results) >= limit: break
    return "\n".join(results) if results else f"未找到「{keyword}」"


TOOLS = [
    {"type":"function","function":{"name":"read_novel","description":"读取novel.txt中指定行范围的内容","parameters":{"type":"object","properties":{"start_line":{"type":"integer"},"end_line":{"type":"integer"}},"required":["start_line","end_line"]}}},
    {"type":"function","function":{"name":"search_novel","description":"在novel.txt中搜索关键词","parameters":{"type":"object","properties":{"keyword":{"type":"string"},"limit":{"type":"integer"}},"required":["keyword"]}}},
    {"type":"function","function":{"name":"get_characters","description":"获取当前角色注册表中的所有已知角色","parameters":{"type":"object","properties":{}}}}
]


def execute_tool(name, args):
    if name == "read_novel": return read_novel(args["start_line"], args["end_line"])
    elif name == "search_novel": return search_novel(args["keyword"], args.get("limit", 10))
    elif name == "get_characters":
        chars = read_characters()
        return "、".join(chars.keys()) if chars else "暂无"
    return f"未知工具: {name}"


def log_session(agent, prompt, output, tc=0):
    os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"agent":agent,"prompt":prompt[:600],"output":output[:300],"tool_calls":tc}, ensure_ascii=False)+"\n")


def log_tool_call(agent, tool, args, result):
    os.makedirs(os.path.dirname(TOOL_LOG_PATH), exist_ok=True)
    with open(TOOL_LOG_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps({"agent":agent,"tool":tool,"args":str(args)[:120],"result":str(result)[:200]}, ensure_ascii=False)+"\n")


def call_ollama(msgs, system, timeout=180, agent="unknown"):
    if not msgs or msgs[0].get("role") != "system":
        msgs.insert(0, {"role":"system","content":system})
    prompt = msgs[-1].get("content","")[:600]
    tc_count = 0
    for _ in range(MAX_TOOL_CALLS):
        body = json.dumps({"model":MODEL,"messages":msgs,"tools":TOOLS,"stream":False,"options":{"temperature":0.1}}).encode()
        req = urllib.request.Request(OLLAMA_URL+"/api/chat", data=body, headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        msg = data["message"]
        content = msg.get("content","").strip()
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            log_session(agent, prompt, content, tc_count)
            return content if content else "（无输出）"
        for tc in tool_calls:
            tc_count += 1
            name = tc["function"]["name"]
            raw_args = tc["function"]["arguments"]
            if isinstance(raw_args, str):
                args = json.loads(raw_args)
            else:
                args = raw_args
            result = execute_tool(name, args)
            log_tool_call(agent, name, args, result)
            print(f"    [{agent}] {name}({str(args)[:50]})")
            msgs.append({"role":"assistant","content":"","tool_calls":[tc]})
            msgs.append({"role":"tool","content":result,"tool_call_id":tc.get("id","")})
    log_session(agent, prompt, "MAX_TOOL_CALLS", tc_count)
    return "（达到最大工具调用次数）"


# ---- File helpers ----

def get_dialogues():
    result = []
    with open(NOVEL_PATH, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            for m in re.finditer(r"\u300c([^\u300d]+)\u300d", line):
                result.append({"line":i,"text":m.group(1)})
    return result

def read_memory(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("content","")
    except: return ""

def write_memory(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"content":content}, f, ensure_ascii=False)

def read_characters():
    try:
        with open(CHARACTERS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except: return {}

def write_characters(data):
    os.makedirs(os.path.dirname(CHARACTERS_PATH), exist_ok=True)
    with open(CHARACTERS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

def read_progress():
    try:
        with open(PROGRESS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except: return {"labeled":0,"last_line":0}

def write_progress(data):
    os.makedirs(os.path.dirname(PROGRESS_PATH), exist_ok=True)
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)

def count_labels():
    try:
        with open(LABELED_PATH, encoding="utf-8") as f:
            return sum(1 for l in f if l.strip())
    except: return 0

def append_label(speaker):
    with open(LABELED_PATH, "a", encoding="utf-8") as f:
        f.write(speaker+"\n")


# ---- Agent prompts ----

SYSTEMS = {
    "scene": "你是场景分析师。用 read_novel/search_novel 分析场景。最后用一句话概括场景（谁、在哪、做什么）。",
    "character": "你是角色分析师。用 read_novel 读原文、search_novel 搜索角色名来分析说话人。输出角色名或身份词。",
    "prosecutor": "你是检举师。用 read_novel/search_novel/get_characters 找证据。引用具体行号。",
    "challenger": "你是质疑师。用 read_novel/search_novel 核实检举师的证据。指出不实之处。给出你的判断。",
    "final": "你是最终标注师。可用 read_novel 自己核实。检举师和质疑师冲突时优先采信质疑师。只输出说话人名字。",
}


def label_one(d, short_term, long_term, st_count):
    line, text = d["line"], d["text"]
    print(f"\n{'='*60}\nDialogue at line {line}:「{text}」\n{'='*60}")

    # 1. Scene
    print("\n[Scene] Analyzing scene...")
    s1 = f"对话在第{line}行：「{text}」。请分析场景。"
    scene = call_ollama([{"role":"user","content":s1}], SYSTEMS["scene"], agent="scene")
    print(f"  -> {scene}")

    # 2. Character
    print("\n[Character] Analyzing speaker...")
    s2 = f"对话在第{line}行：「{text}」。请判断说话人。"
    char = call_ollama([{"role":"user","content":s2}], SYSTEMS["character"], agent="character")
    print(f"  -> {char}")

    # 3. Prosecutor
    print("\n[Prosecutor] Searching evidence...")
    s3 = f"对话在第{line}行：「{text}」。请找证据。"
    claim = call_ollama([{"role":"user","content":s3}], SYSTEMS["prosecutor"], agent="prosecutor")
    print(f"  -> {claim[:80]}")

    # 4. Challenger
    print("\n[Challenger] Verifying...")
    s4 = f"检举师声称：「{claim}」\n请核实证据，给出判断。"
    chal = call_ollama([{"role":"user","content":s4}], SYSTEMS["challenger"], agent="challenger")
    print(f"  -> {chal[:80]}")

    lookahead = f"检举师：{claim}\n质疑师：{chal}"

    # 5. Memory
    print("\n[Memory] Summarizing...")
    mp = (f"场景：{scene}\n角色分析：{char}\n后文：{lookahead}\n短期记忆：{short_term}\n长期记忆：{long_term}\n\n"
          f"请用一段话汇总以上事实信息。不要推断说话人。")
    mem = call_ollama([{"role":"user","content":mp}], "你只汇总信息，不做判断。", agent="memory")
    print(f"  -> {mem[:80]}")

    # 6. Final labeler
    print("\n[Labeler] Final judgment (with tools)...")
    lp = (f"待标对话在第{line}行：「{text}」\n\n场景：{scene}\n角色：{char}\n后文：{lookahead}\n历史：{mem}\n\n"
          f"规则：1.用原文角色名或身份词 2.已注册的角色用原名 3.拟声词标「非人物发声」4.完全不确定标「？？？」\n"
          f"5.检举师和质疑师冲突时优先采信质疑师 6.可用 read_novel 自己核实 7.只输出说话人名字")
    label = call_ollama([{"role":"user","content":lp}], SYSTEMS["final"], agent="final_labeler")
    print(f"  -> Speaker: {label}")

    # 7. Normalizer
    existing = read_characters()
    final = label
    if existing:
        cl = "、".join(existing.keys())
        np_ = f"说话人：{label}\n已有：{cl}\n\n同一人？输出角色名或 NEW。不要输出'已有角色名'。"
        norm = call_ollama([{"role":"user","content":np_}], "你是角色归一师。", agent="normalizer")
        if norm not in ("NEW",""):
            final = norm
        print(f"\n[Normalizer] {norm} -> final: {final}")

    # 8. Write (Python only)
    append_label(final)
    print(f"  [Write] '{final}'")

    # 9. Registry (Python only)
    if final not in existing and final not in ("非人物发声","？？？"):
        existing[final] = {"firstSeen":f"line {line}"}
        write_characters(existing)

    # 10. Short-term memory
    prev = read_progress().get("last_line", 0)
    dist = abs(line - prev)
    st_updated = False
    if dist > 5 and prev > 0:
        print(f"\n[Memory] Scene change ({dist} lines)")
        up = f"旧短期：{short_term}\n当前场景：{scene}\n\n概括新短期记忆："
        short_term = call_ollama([{"role":"user","content":up}], "你是记忆管理员。", agent="short_term")
        st_count += 1; st_updated = True
        write_memory(SHORT_TERM_PATH, short_term)
    else:
        print(f"\n[Memory] Same scene (dist={dist})")

    # 11. Long-term
    if st_count > 0 and st_count % 5 == 0 and st_updated:
        lp2 = f"旧长期：{long_term}\n最近：{short_term}\n\n概括更新后长期记忆。"
        long_term = call_ollama([{"role":"user","content":lp2}], "你是历史记录员。", agent="long_term")
        write_memory(LONG_TERM_PATH, long_term)

    # 12. Progress
    prog = read_progress()
    prog["labeled"] += 1; prog["last_line"] = line
    write_progress(prog)
    print(f"\n{'='*60}\nProgress: {prog['labeled']} labeled\n{'='*60}")
    return short_term, long_term, st_count


def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--reset", action="store_true")
    p.add_argument("--count", type=int, default=1)
    a = p.parse_args()
    if a.reset:
        for f in [LABELED_PATH]: os.path.exists(f) and os.remove(f)
        write_progress({"labeled":0,"last_line":0})
        write_characters({})
        write_memory(SHORT_TERM_PATH,"")
        write_memory(LONG_TERM_PATH,"")
        for log in [LOG_PATH, TOOL_LOG_PATH]:
            os.makedirs(os.path.dirname(log), exist_ok=True)
            open(log, "w").close()
        print("[RESET] Done")

    dialogs = get_dialogues()
    start = count_labels()
    st = read_memory(SHORT_TERM_PATH)
    lt = read_memory(LONG_TERM_PATH)
    sc = 0
    print(f"Model: {MODEL}\nDialogues: {len(dialogs)}, start={start}")
    for i in range(start, min(start+a.count, len(dialogs))):
        st, lt, sc = label_one(dialogs[i], st, lt, sc)
    print(f"\nDone! {a.count} dialogues.")


if __name__ == "__main__":
    main()
