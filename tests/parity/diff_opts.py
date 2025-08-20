import json, sys, difflib

def load(p):
    with open(p, "r", encoding="utf-8") as f:
        return json.load(f)

def norm(x):
    if isinstance(x, float):
        return round(x, 3)
    if isinstance(x, dict):
        return {k: norm(x[k]) for k in sorted(x)}
    if isinstance(x, list):
        return [norm(v) for v in x]
    return x

def main(a, b):
    A = norm(load(a)); B = norm(load(b))
    if A == B:
        print("OK: opts.json are equivalent"); return 0
    print("DIFF: opts.json differ")
    ta = json.dumps(A, indent=2, sort_keys=True).splitlines()
    tb = json.dumps(B, indent=2, sort_keys=True).splitlines()
    for line in difflib.unified_diff(ta, tb, fromfile=a, tofile=b, lineterm=""):
        print(line)
    return 1

if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python3 diff_opts.py before/opts.json after/opts.json")
        sys.exit(2)
    sys.exit(main(sys.argv[1], sys.argv[2]))
