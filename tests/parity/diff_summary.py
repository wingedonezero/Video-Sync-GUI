import difflib
import sys


def main(a, b):
    ta = open(a, "r", encoding="utf-8", errors="ignore").read().splitlines()
    tb = open(b, "r", encoding="utf-8", errors="ignore").read().splitlines()
    if ta == tb:
        print("OK: summaries match");
        return 0
    print("DIFF: summaries differ")
    for line in difflib.unified_diff(ta, tb, fromfile=a, tofile=b, lineterm=""):
        print(line)
    return 1


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 diff_summary.py before/summary.txt after/summary.txt")
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
