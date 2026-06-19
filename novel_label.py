#!/usr/bin/env python3
"""Multi-agent novel dialogue speaker labeling - V3."""
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

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")

# ---- Helpers ----


def call_ollama(system, prompt, timeout=180):
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
    body = json.dumps({"model": MODEL, "messages": msgs, "stream": False, "options": {"temperature": 0.1}}).encode()
    req = urllib.request.Request(OLLAMA_URL + "/api/chat", data=body,
                                  headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode())
        return data["message"]["content"].strip()


def read_novel(start, end):
    with open(NOVEL_PATH, encoding="utf-8") as f:
        lines = f.readlines()
    return "".join(lines[start - 1:end])


def get_dialogues():
    result = []
    with open(NOVEL_PATH, encoding="utf-8") as f:
        for i, line in enumerate(f, 1):
            for m in re.finditer(r"\u300c([^\u300d]+)\u300d", line):
                result.append({"line": i, "text": m.group(1)})
    return result


def read_memory(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f).get("content", "")
    except (FileNotFoundError, json.JSONDecodeError):
        return ""


def write_memory(path, content):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"content": content}, f, ensure_ascii=False)


def read_characters():
    try:
        with open(CHARACTERS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def write_characters(data):
    os.makedirs(os.path.dirname(CHARACTERS_PATH), exist_ok=True)
    with open(CHARACTERS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_progress():
    try:
        with open(PROGRESS_PATH, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"labeled": 0, "last_line": 0}


def write_progress(data):
    os.makedirs(os.path.dirname(PROGRESS_PATH), exist_ok=True)
    with open(PROGRESS_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)


def count_labels():
    try:
        with open(LABELED_PATH, encoding="utf-8") as f:
            return sum(1 for l in f if l.strip())
    except FileNotFoundError:
        return 0


def append_label(speaker):
    with open(LABELED_PATH, "a", encoding="utf-8") as f:
        f.write(speaker + "\n")


# ---- Agents ----

def agent_scene_analyzer(line):
    context = read_novel(max(1, line - 8), min(3065, line + 8))
    prompt = f"以下是小说片段。请用一句话概括当前场景（谁在哪里、在做什么）：\n\n{context}\n\n场景概括："
    result = call_ollama("你是场景分析师。", prompt, timeout=180)
    return result


def agent_character_analyzer(line, text):
    context = read_novel(max(1, line - 8), min(3065, line + 8))
    prompt = f"以下是小说片段。请分析这段对话的说话人是谁，只输出角色名或身份词：\n\n上下文：{context}\n\n待标对话：「{text}」\n\n说话人："
    result = call_ollama("你是角色分析师。", prompt, timeout=180)
    return result


def agent_lookahead_prosecutor(line, compressed_history=""):
    ctx = read_novel(line + 1, min(3065, line + 20))
    hist = f"此前已搜索：{compressed_history}\n" if compressed_history else ""
    prompt = f"{hist}以下是第{line+1}行附近的内容。请找出说话人证据，引用原文行号：\n\n{ctx}\n\n证据："
    result = call_ollama("你是检举师。仔细读原文，找出说话人身份，必须引用具体行号作为证据。", prompt, timeout=180)
    return result


def agent_challenger(line, claim):
    ctx = read_novel(max(1, line - 3), min(3065, line + 23))
    prompt = (
        f"检举师声称：「{claim}」\n\n"
        f"原文如下（核实检举师的claim是否有依据）：\n{ctx}\n\n"
        f"任务：检举师的claim在原文中有依据吗？引用原文证明。给出你认为的说话人。"
    )
    result = call_ollama("你是质疑师。严格核实检举师的claim，指出不实之处，给出客观判断。", prompt, timeout=180)
    return result


def agent_memory_merger(scene, character, lookahead, short_term, long_term):
    prompt = (
        f"当前对话信息汇总：\n"
        f"场景：{scene}\n"
        f"角色分析：{character}\n"
        f"后文调查：{lookahead}\n\n"
        f"短期记忆（最近场景）：{short_term}\n"
        f"长期记忆（全卷至今）：{long_term}\n\n"
        f"请用一段话汇总以上事实信息。只写事实摘要，不要推断说话人是谁。"
    )
    result = call_ollama("你只负责汇总信息，不做任何角色判断。", prompt, timeout=180)
    return result


def agent_short_term_updater(old_short_term, scene):
    prompt = f"旧短期记忆：{old_short_term}\n\n当前场景：{scene}\n\n请判断是否需要更新短期记忆。如果需要，用一句话概括新的短期记忆："
    result = call_ollama("你是记忆管理员。", prompt, timeout=180)
    return result


def agent_long_term_updater(old_long_term, short_term):
    prompt = f"旧长期记忆：{old_long_term}\n\n最近进展：{short_term}\n\n请用两到三句话概括更新后的长期记忆（保留关键角色和事件）："
    result = call_ollama("你是历史记录员。", prompt, timeout=180)
    return result


def agent_final_labeler(text, scene, character, lookahead, memory_summary):
    prompt = (
        f"你是一名最终标注师。请综合以下信息，确定这段对话的说话人是谁。\n\n"
        f"待标对话：「{text}」\n"
        f"场景分析：{scene}\n"
        f"角色分析：{character}\n"
        f"后文调查：{lookahead}\n"
        f"历史信息：{memory_summary}\n\n"
        f"规则：\n"
        f"1. 说话人必须是小说中实际出现的角色名或稳定身份词\n"
        f"2. 已注册的角色用原名\n"
        f"3. 拟声词/环境音标「非人物发声」\n"
        f"4. 完全无法确定标「？？？」\n"
        f"5. 如果后文调查中检举师和质疑师冲突，优先采信质疑师的判断\n"
        f"6. 只输出说话人名字，不要多余内容\n\n"
        f"说话人："
    )
    result = call_ollama("你是最终标注师。", prompt, timeout=180)
    return result


def agent_normalizer(speaker, existing_chars):
    if not existing_chars:
        return "NEW"
    char_list = "、".join(existing_chars.keys())
    prompt = f"当前标注了说话人：{speaker}\n已有角色：{char_list}\n\n请判断：这个说话人是否与已有角色是同一人（别名/简称/不同叫法）？如果是同一人，输出该角色的具体名字（例如'赫萝'），不要输出'已有角色名'这四个字。如果是新角色，输出 NEW。"
    result = call_ollama("你是角色归一师。", prompt, timeout=180)
    return result


# ---- Main loop ----

def label_one(dialogue, short_term, long_term, short_term_update_count):
    line = dialogue["line"]
    text = dialogue["text"]
    logs = []

    print(f"\n{'='*60}")
    print(f"Dialogue at line {line}: 「{text}」")
    print(f"{'='*60}")

    # 1. Scene analyzer
    print(f"\n[Scene] Analyzing scene...")
    scene = agent_scene_analyzer(line)
    print(f"  -> {scene}")
    logs.append(f"[Scene] {scene}")

    # 2. Character analyzer
    print(f"\n[Character] Analyzing speaker...")
    character = agent_character_analyzer(line, text)
    print(f"  -> {character}")
    logs.append(f"[Character] {character}")

    # 3. Lookahead (prosecutor + challenger debate)
    print(f"\n[Lookahead] Searching for identity reveals...")
    claim = agent_lookahead_prosecutor(line)
    print(f"  Prosecutor: {claim[:80]}")
    challenge = agent_challenger(line, claim)
    print(f"  Challenger: {challenge[:80]}")
    lookahead = f"检举师：{claim}\n质疑师：{challenge}"
    logs.append(f"[Lookahead] {lookahead}")

    # 4. Memory merger (summary only, no character judgment)
    print(f"\n[Memory] Merging information...")
    memory = agent_memory_merger(scene, character, lookahead, short_term, long_term)
    print(f"  -> {memory[:80]}")
    logs.append(f"[Memory] {memory}")

    # 5. Final labeler
    print(f"\n[Labeler] Final judgment...")
    speaker = agent_final_labeler(text, scene, character, lookahead, memory)
    print(f"  -> Speaker: {speaker}")
    logs.append(f"[Labeler] {speaker}")

    # 6. Normalizer
    print(f"\n[Normalizer] Checking for duplicates...")
    existing = read_characters()
    norm = agent_normalizer(speaker, existing)
    final_speaker = norm if norm not in ("NEW", "") else speaker
    print(f"  -> Normalized: {final_speaker}")
    logs.append(f"[Normalizer] {norm}")

    # 7. Write label
    append_label(final_speaker)
    print(f"  [Write] Appended '{final_speaker}' to labeled.txt")

    # 8. Update character registry
    existing = read_characters()
    if final_speaker not in existing and final_speaker not in ("非人物发声", "？？？"):
        existing[final_speaker] = {"firstSeen": f"line {line}", "aliases": []}
        write_characters(existing)
        print(f"  [Registry] Added '{final_speaker}'")

    # 9. Short-term memory update (only if dialogue distance exceeds threshold)
    prev_line = read_progress().get("last_line", 0)
    distance = abs(line - prev_line)
    short_term_updated = False
    if distance > 5 and prev_line > 0:
        print(f"\n[Memory Update] Scene change detected ({distance} lines apart)")
        new_short = agent_short_term_updater(short_term, scene)
        if "不需要" not in new_short and "不更新" not in new_short:
            short_term = new_short
            short_term_update_count += 1
            short_term_updated = True
            write_memory(SHORT_TERM_PATH, short_term)
            print(f"  -> Updated short-term memory")
        else:
            print(f"  -> No update needed")
        logs.append(f"[ShortTermUpdate] {new_short}")
    else:
        print(f"\n[Memory Update] Same scene (distance={distance}), no update")

    # 10. Long-term memory update (every 5 short-term updates)
    if short_term_update_count > 0 and short_term_update_count % 5 == 0 and short_term_updated:
        long_term = agent_long_term_updater(long_term, short_term)
        write_memory(LONG_TERM_PATH, long_term)
        print(f"  [LongTermUpdate] Updated long-term memory")
        logs.append(f"[LongTermUpdate] {long_term}")

    # 11. Update progress
    prog = read_progress()
    prog["labeled"] += 1
    prog["last_line"] = line
    write_progress(prog)

    print(f"\n{'='*60}")
    print(f"Done. Progress: {prog['labeled']} labeled")
    print(f"{'='*60}")

    return short_term, long_term, short_term_update_count


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Multi-agent novel dialogue labeling V3")
    parser.add_argument("--reset", action="store_true", help="Clear all progress and start fresh")
    parser.add_argument("--count", type=int, default=1, help="Number of dialogues to label (default: 1)")
    args = parser.parse_args()

    if args.reset:
        if os.path.exists(LABELED_PATH):
            os.remove(LABELED_PATH)
        write_progress({"labeled": 0, "last_line": 0})
        write_characters({})
        write_memory(SHORT_TERM_PATH, "")
        write_memory(LONG_TERM_PATH, "")
        print("[RESET] All progress cleared")

    dialogues = get_dialogues()
    start = count_labels()
    short_term = read_memory(SHORT_TERM_PATH)
    long_term = read_memory(LONG_TERM_PATH)
    short_term_update_count = 0

    print(f"Model: {MODEL}")
    print(f"Ollama: {OLLAMA_URL}")
    print(f"Dialogues: {len(dialogues)} total, starting from {start}")
    print(f"Short-term: {'[empty]' if not short_term else short_term[:40]}")
    print(f"Long-term: {'[empty]' if not long_term else long_term[:40]}")

    for i in range(start, min(start + args.count, len(dialogues))):
        short_term, long_term, short_term_update_count = label_one(
            dialogues[i], short_term, long_term, short_term_update_count
        )

    print(f"\nDone! Labeled {args.count} dialogues.")


if __name__ == "__main__":
    main()
