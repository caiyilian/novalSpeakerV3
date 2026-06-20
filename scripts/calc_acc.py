"""Calculate labeling accuracy with multi-answer support.
Answers format: 【speaker1|speaker2】「dialogue」
"""
import os, re, sys
if sys.platform == "win32": sys.stdout.reconfigure(encoding="utf-8")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ANSWERS_PATH = os.path.join(BASE, "answers", chr(31532) + chr(49) + chr(21367) + ".txt")
LABELED_PATH = os.path.join(BASE, "labeled.txt")


def load_answers():
    """Parse answers file. Returns list of [accepted_speakers, dialogue_text]."""
    result = []
    pat = re.compile(r"\u3010([^\u3011]+)\u3011\u300c([^\u300d]+)\u300d")
    with open(ANSWERS_PATH, encoding="utf-8") as f:
        for line in f:
            m = pat.search(line)
            if m:
                speakers = [s.strip() for s in m.group(1).split("|")]
                result.append(speakers)
    return result


def load_labels():
    try:
        with open(LABELED_PATH, encoding="utf-8") as f:
            return [line.strip() for line in f if line.strip()]
    except FileNotFoundError:
        return []


def main():
    labels = load_labels()
    answers = load_answers()
    n = min(len(labels), len(answers))

    print(f"Labeled: {len(labels)}  |  Answers available: {len(answers)}")
    print()

    if n == 0:
        print("No data to compare.")
        return

    correct = 0
    errors = []

    for i in range(n):
        label = labels[i]
        expected = answers[i]
        ok = label in expected
        if ok:
            correct += 1
        else:
            errors.append((i + 1, label, expected[0]))

    pct = correct / n * 100

    print(f"Correct: {correct}/{n} = {pct:.1f}%")
    print()

    if errors:
        print(f"Errors ({len(errors)} total, first 30):")
        print(f"  {'#':>4}  {'labeled':<15}  {'expected'}")
        print(f"  {'-'*4}  {'-'*15}  {'-'*15}")
        for idx, label, exp in errors[:30]:
            print(f"  {idx:>4}  {label:<15}  {exp}")
        if len(errors) > 30:
            print(f"  ... and {len(errors) - 30} more")

    # Label distribution
    dist = {}
    for l in labels:
        dist[l] = dist.get(l, 0) + 1
    print()
    print("Label distribution:")
    for name, count in sorted(dist.items(), key=lambda x: -x[1])[:20]:
        print(f"  {name:<12}  {count}")


if __name__ == "__main__":
    main()
