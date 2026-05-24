import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

def load_allowed_tags():
    path = os.path.join(ROOT, "tags-registry.md")
    tags = set()
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            m = re.match(r'\|\s*`([^`]+)`\s*\|', line)
            if m:
                tags.add(m.group(1))
    return tags

allowed = load_allowed_tags()
out_path = os.path.join(ROOT, "scratch", "allowed_tags_output.txt")
with open(out_path, "w", encoding="utf-8") as out_f:
    out_f.write(f"Total allowed tags: {len(allowed)}\n")
    out_f.write("Allowed tags list:\n")
    for t in sorted(list(allowed)):
        out_f.write(f"- {t}\n")

print("Done! Check scratch/allowed_tags_output.txt")
