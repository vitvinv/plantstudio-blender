"""One-time generator: parse umakepm.py into a JSON parameter registry.

Robust approach: split on 'addParameterForSection' and 'make(' segments,
extract the kFieldID and the access string (15th argument) positionally.
"""
import re
import json
import os

SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..",
                   "examples", "PlantStudio-master", "for-olpc-python", "umakepm.py")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "param_registry.json")

src = open(SRC, encoding="latin-1").read()

# find all make( ... ) calls, matching balanced parens
results = []
pos = 0
while True:
    start = src.find(".make(", pos)
    if start < 0:
        break
    depth = 1
    i = start + len(".make(")
    quote = None
    while i < len(src) and depth > 0:
        ch = src[i]
        if ch in ("'", '"'):
            # handle escaped quotes (\" or \')
            if i > 0 and src[i - 1] == "\\":
                pass
            else:
                if quote is None:
                    quote = ch
                elif quote == ch:
                    quote = None
        elif quote is None:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
        i += 1
    body = src[start + len(".make("):i - 1]
    results.append(body)
    pos = i

def parse_args(body):
    """Split comma-separated args, respecting single- or double-quoted
    strings (which may themselves contain commas, e.g. TDO defaults)."""
    args = []
    cur = ""
    quote = None
    prev = ""
    for ch in body:
        if ch in ("'", '"'):
            if prev == "\\":
                cur += ch
                prev = ch
                continue
            if quote is None:
                quote = ch
            elif quote == ch:
                quote = None
            cur += ch
        elif ch == "," and quote is None:
            args.append(cur.strip())
            cur = ""
        else:
            cur += ch
        prev = ch
    if cur.strip():
        args.append(cur.strip())
    return args

registry = []
for body in results:
    args = parse_args(body)
    if len(args) < 17:
        continue

    def clean(s):
        s = s.strip()
        if len(s) >= 2 and s[0] in ("'", '"') and s[-1] == s[0]:
            s = s[1:-1]
        return s

    field_no = args[0]
    field_id = clean(args[1])
    if field_id == "header":
        continue
    name = clean(args[2])
    ftype = args[3]
    lo, hi = args[9], args[10]
    default = clean(args[11])
    access = clean(args[14])
    ttype = args[15]
    try:
        registry.append({
            "field_no": int(field_no),
            "id": field_id,
            "name": name,
            "type": int(ftype),
            "lo": float(lo),
            "hi": float(hi),
            "default": default,
            "access": access,
            "transfer": int(ttype),
        })
    except ValueError:
        continue

print("parsed", len(registry), "params")
with open(OUT, "w") as f:
    json.dump(registry, f, indent=1)
for r in registry[:12]:
    print(r["id"], "->", r["access"], "|", r["type"], "|", r["default"][:25])
