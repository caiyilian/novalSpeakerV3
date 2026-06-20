#!/usr/bin/env python3
"""Multi-agent novel dialogue labeling V3."""
import json, os, re, sys, urllib.request, urllib.error

BASE = os.path.dirname(os.path.abspath(__file__))
OLLAMA_URL, MODEL = "http://172.31.102.237:11434", "qwen3:32b"
SHORT_TERM_PATH = os.path.join(BASE, ".omo", "memory", "short_term.json")
LONG_TERM_PATH = os.path.join(BASE, ".omo", "memory", "long_term.json")
CHARACTERS_PATH = os.path.join(BASE, ".omo", "evidence", "characters.json")
PROGRESS_PATH = os.path.join(BASE, ".omo", "evidence", "progress.json")
NOVEL_PATH = os.path.join(BASE, "novel.txt")
LABELED_PATH = os.path.join(BASE, "labeled.txt")
SESSION_LOG_PATH = os.path.join(BASE, ".omo", "logs", "session_log.jsonl")
TOOL_CALLS_LOG_PATH = os.path.join(BASE, ".omo", "logs", "tool_calls.jsonl")
if sys.platform == "win32": sys.stdout.reconfigure(encoding="utf-8")

def read_novel(s, e):
    with open(NOVEL_PATH, encoding="utf-8") as f:
        l = f.readlines()
    s, e = max(1,s), min(len(l),e)
    return f"---第{s}到{e}行---\n" + "".join(l[s-1:e])

def search_novel(k, limit=10):
    r = []
    with open(NOVEL_PATH, encoding="utf-8") as f:
        for i,line in enumerate(f,1):
            if k in line:
                r.append(f"第{i}行：{line.strip()[:80]}")
                if len(r)>=limit: break
    return "\n".join(r) or f"未找到「{k}」"

TOOLS_R = [{"type":"function","function":{"name":"read_novel","parameters":{"type":"object","properties":{"start_line":{"type":"integer"},"end_line":{"type":"integer"}},"required":["start_line","end_line"]}}},
           {"type":"function","function":{"name":"search_novel","parameters":{"type":"object","properties":{"keyword":{"type":"string"},"limit":{"type":"integer"}},"required":["keyword"]}}},
           {"type":"function","function":{"name":"get_characters","parameters":{"type":"object","properties":{}}}}]
TOOLS_F = TOOLS_R + [{"type":"function","function":{"name":"append_label","parameters":{"type":"object","properties":{"speaker":{"type":"string"}},"required":["speaker"]}}}]

def exec_tool(name, args):
    if name=="read_novel": return read_novel(args["start_line"],args["end_line"])
    if name=="search_novel": return search_novel(args["keyword"],args.get("limit",10))
    if name=="get_characters":
        c = read_characters(); return "、".join(c.keys()) or "暂无"
    if name=="append_label":
        with open(LABELED_PATH,"a",encoding="utf-8") as f: f.write(args["speaker"]+"\n")
        return f"已写入 {args['speaker']}"
    return "未知工具:"+name

def log_sess(a,p,o,tc=0):
    os.makedirs(os.path.dirname(SESSION_LOG_PATH),exist_ok=True)
    with open(SESSION_LOG_PATH,"a",encoding="utf-8") as f:
        f.write(json.dumps({"agent":a,"prompt":p[:600],"output":o[:300],"tool_calls":tc},ensure_ascii=False)+"\n")

def log_tool(a,t,args,r):
    os.makedirs(os.path.dirname(TOOL_CALLS_LOG_PATH),exist_ok=True)
    with open(TOOL_CALLS_LOG_PATH,"a",encoding="utf-8") as f:
        f.write(json.dumps({"agent":a,"tool":t,"args":str(args)[:120],"result":str(r)[:200]},ensure_ascii=False)+"\n")

def call_ollama(msgs, system, timeout=180, agent="unknown", tools="R"):
    """Call model with tools. tools='R'=read_only, 'F'=full(incl append_label)."""
    tlist = TOOLS_F if tools=="F" else TOOLS_R
    if not msgs or msgs[0].get("role")!="system": msgs.insert(0,{"role":"system","content":system})
    p = msgs[-1].get("content","")[:600]; tc = 0
    for _ in range(10):
        body = json.dumps({"model":MODEL,"messages":msgs,"tools":tlist,"stream":False,"options":{"temperature":0.1}}).encode()
        req = urllib.request.Request(OLLAMA_URL+"/api/chat",data=body,headers={"Content-Type":"application/json"})
        with urllib.request.urlopen(req,timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        msg = data["message"]; content = msg.get("content","").strip(); calls = msg.get("tool_calls")
        if not calls:
            log_sess(agent,p,content,tc); return content or "（无输出）"
        for c in calls:
            tc += 1; nm = c["function"]["name"]
            args = json.loads(c["function"]["arguments"]) if isinstance(c["function"]["arguments"],str) else c["function"]["arguments"]
            result = exec_tool(nm,args); log_tool(agent,nm,args,result)
            print(f"    [{agent}] {nm}({str(args)[:50]})")
            msgs.append({"role":"assistant","content":"","tool_calls":[c]})
            msgs.append({"role":"tool","content":result,"tool_call_id":c.get("id","")})
    log_sess(agent,p,"MAX_CALLS",tc); return "（达到最大工具调用次数）"

def call_ollama_nt(msgs, system, timeout=180, agent="unknown"):
    """Call model WITHOUT any tools."""
    if not msgs or msgs[0].get("role")!="system": msgs.insert(0,{"role":"system","content":system})
    p = msgs[-1].get("content","")[:600]
    body = json.dumps({"model":MODEL,"messages":msgs,"stream":False,"options":{"temperature":0.1}}).encode()
    req = urllib.request.Request(OLLAMA_URL+"/api/chat",data=body,headers={"Content-Type":"application/json"})
    with urllib.request.urlopen(req,timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
    c = data["message"].get("content","").strip()
    log_sess(agent,p,c,0); return c or "（无输出）"

def get_dialogues():
    r = []
    with open(NOVEL_PATH,encoding="utf-8") as f:
        for i,line in enumerate(f,1):
            for m in re.finditer(r"\u300c([^\u300d]+)\u300d",line): r.append({"line":i,"text":m.group(1)})
    return r
def read_memory(p):
    try:
        with open(p,encoding="utf-8") as f: return json.load(f).get("content","")
    except: return ""
def write_memory(p,c):
    os.makedirs(os.path.dirname(p),exist_ok=True)
    with open(p,"w",encoding="utf-8") as f: json.dump({"content":c},f,ensure_ascii=False)
def read_characters():
    try:
        with open(CHARACTERS_PATH,encoding="utf-8") as f: return json.load(f)
    except: return {}
def write_characters(d):
    os.makedirs(os.path.dirname(CHARACTERS_PATH),exist_ok=True)
    with open(CHARACTERS_PATH,"w",encoding="utf-8") as f: json.dump(d,f,ensure_ascii=False,indent=2)
def read_progress():
    try:
        with open(PROGRESS_PATH,encoding="utf-8") as f: return json.load(f)
    except: return {"labeled":0,"last_line":0}
def write_progress(d):
    with open(PROGRESS_PATH,"w",encoding="utf-8") as f: json.dump(d,f,ensure_ascii=False)
def append_label(speaker):
    with open(LABELED_PATH,"a",encoding="utf-8") as f: f.write(speaker+"\n")
def count_labels():
    try:
        with open(LABELED_PATH,encoding="utf-8") as f: return sum(1 for l in f if l.strip())
    except: return 0

S = {
    "scene":"场景分析师。用 read_novel/search_novel 分析场景。用一句话概括（谁、在哪、做什么）。",
    "character":"角色调查师。用 read_novel/search_novel/get_characters 自由搜索原文，找出说话人证据。只输出发现，不下结论。",
    "prosecutor":"检举师。用 read_novel/search_novel/get_characters 找证据，引用具体行号。",
    "challenger":"质疑师。用 read_novel/search_novel 核实检举师的证据。指出不实之处。",
    "final":"最终标注师。综合所有证据判断说话人。你必须给出一个具体角色名或身份词，严禁输出「？？？」。如果证据不足，用 read_novel/search_novel 自己调查后再判断。检举师和质疑师冲突时优先采信质疑师。只输出名字。",
    "executor":"执行师。根据判决调用 append_label 工具写入。完成后回复 DONE。",
}

def run_checker(claim, ctx=""):
    return call_ollama([{"role":"user","content":f"需核实的claim：{claim}\n{ctx}\n请核实。正确回复 OK，否则说明情况。"}],"检查师。用 read_novel 严格核实 claim。",agent="checker")

def label_one(d, st, lt, stc):
    line, text = d["line"], d["text"]
    print(f"\n{'='*60}\nL{line}:「{text}」\n{'='*60}")
    # 1. Scene
    print("\n[Scene]...")
    prev = read_progress().get("last_line",0)
    ctx_range = f"请阅读第{prev+1}行到第{line+5}行的内容" if prev > 0 and line - prev > 3 else f"请阅读第{max(1,line-5)}行到第{line+5}行的内容"
    scene = call_ollama([{"role":"user","content":f"对话在第{line}行：「{text}」。{ctx_range}，分析场景（谁、在哪、做什么）。"}],S["scene"],agent="scene")
    print(f"  -> {scene}")
    # 2. Character evidence (tools=R -> read/search/get_characters)
    print("\n[Character] Searching...")
    ev = call_ollama([{"role":"user","content":f"对话在第{line}行：「{text}」。搜索说话人证据。"}],S["character"],agent="character")
    print(f"  -> {ev[:80]}")
    ck = run_checker(ev,f"对话在第{line}行")
    if "OK" not in ck: print(f"  [Checker] Issues: {ck[:60]}"); ev += f"\n[检查师意见] {ck}"
    # 3. Prosecutor + Challenger
    print("\n[Prosecutor]...")
    claim = call_ollama([{"role":"user","content":f"对话在第{line}行：「{text}」。找证据。"}],S["prosecutor"],agent="prosecutor")
    print(f"  -> {claim[:80]}")
    chal = call_ollama([{"role":"user","content":f"检举师声称：「{claim}」\n请核实。"}],S["challenger"],agent="challenger")
    print(f"  -> {chal[:80]}"); la = f"检举师：{claim}\n质疑师：{chal}"
    # 4. Memory (no tools)
    print("\n[Memory]...")
    mem = call_ollama_nt([{"role":"user","content":f"场景：{scene}\n角色证据：{ev}\n后文：{la}\n短期：{st}\n长期：{lt}\n\n汇总事实。"}],"你只汇总信息，不做判断。",agent="memory")
    print(f"  -> {mem[:80]}")
    # 5. Final labeler (tools=R -> has read_novel to verify)
    print("\n[Labeler]...")
    lp = (f"待标对话在第{line}行：「{text}」\n\n场景：{scene}\n角色证据：{ev}\n后文：{la}\n历史：{mem}\n\n"
          f"规则：1.用原文角色名 2.已注册角色用原名 3.拟声词标「非人物发声」4.不确定标「？？？」\n"
          f"5.检举师和质疑师冲突时优先采信质疑师 6.可用 read_novel 核实 7.只输出名字，不要加「」括号")
    label = call_ollama([{"role":"user","content":lp}],S["final"],agent="final_labeler")
    print(f"  -> {label}")
    # 6. Normalizer (tools=R -> has read_novel to check aliases)
    existing = read_characters(); final = label
    if existing:
        cl = "、".join(existing.keys())
        n = call_ollama_nt([{"role":"user","content":f"说话人：{label}\n已有：{cl}\n\n同一人？输出角色名或 NEW。"}],"角色归一师。判断是否重复。只输出角色名或 NEW。",agent="normalizer")
        if n not in ("NEW",""): final = n
        print(f"\n[Normalizer] {n} -> final: {final}")
        ck_n = run_checker(f"说话人{label}应归入已有角色{final}",f"对话在第{line}行：「{text}」")
        if "OK" not in ck_n: print(f"  [Checker] Normalizer review: {ck_n[:60]}")
    # 7. Executor (no tools - just confirms, Python writes)
    print("\n[Executor] Confirming...")
    call_ollama_nt([{"role":"user","content":f"最终判决：第{line}行「{text}」的说话人是{final}。确认无误回复 OK。"}],"执行师。确认判决无误后回复 OK。",agent="executor")
    append_label(final)
    print(f"  [Write] '{final}'")
    # 8. Registry (Python only)
    if final not in existing and final not in ("非人物发声","？？？"):
        existing[final] = {"firstSeen":f"line {line}"}; write_characters(existing)
        print(f"  [Registry] Added '{final}'")
    # 9. Memory update
    prev = read_progress().get("last_line",0); dist = abs(line-prev); st_up = False
    if dist > 5 or prev == 0:
        if prev == 0: print(f"\n[Memory] First dialogue, creating initial memory")
        else: print(f"\n[Memory] Scene change ({dist} lines)")
        st = call_ollama_nt([{"role":"user","content":f"旧短期：{st}\n当前场景：{scene}\n角色证据：{ev}\n后文：{la}\n\n用1-2句话概括新短期记忆。"}],"概括短期记忆。",agent="short_term")
        stc += 1; st_up = True; write_memory(SHORT_TERM_PATH,st)
        if not lt: lt = st; write_memory(LONG_TERM_PATH,lt); print("  [LongTerm] Init from short-term")
        elif stc % 5 == 0:
            lt = call_ollama_nt([{"role":"user","content":f"旧长期：{lt}\n最近：{st}\n\n用2-3句话概括更新后长期记忆。"}],"概括长期记忆。",agent="long_term")
            write_memory(LONG_TERM_PATH,lt)
    else: print(f"\n[Memory] Same (dist={dist})")
    prog = read_progress(); prog["labeled"] += 1; prog["last_line"] = line; write_progress(prog)
    print(f"\nProgress: {prog['labeled']} labeled\n{'='*60}")
    return st, lt, stc

def main():
    import argparse
    p = argparse.ArgumentParser(); p.add_argument("--reset",action="store_true"); p.add_argument("--count",type=int,default=1)
    a = p.parse_args()
    if a.reset:
        for f in [LABELED_PATH]:
            if os.path.exists(f): os.remove(f)
        write_progress({"labeled":0,"last_line":0}); write_characters({})
        write_memory(SHORT_TERM_PATH,""); write_memory(LONG_TERM_PATH,"")
        for l in [SESSION_LOG_PATH,TOOL_CALLS_LOG_PATH]:
            os.makedirs(os.path.dirname(l),exist_ok=True); open(l,"w").close()
        print("[RESET] Done")
    dialogs = get_dialogues(); start = count_labels()
    st = read_memory(SHORT_TERM_PATH); lt = read_memory(LONG_TERM_PATH); sc = 0
    print(f"Model: {MODEL}\nDialogues: {len(dialogs)}, start={start}")
    for i in range(start, min(start+a.count, len(dialogs))):
        st, lt, sc = label_one(dialogs[i], st, lt, sc)
    print(f"\nDone! {a.count} dialogues.")

if __name__ == "__main__":
    main()
