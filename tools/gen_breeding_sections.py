"""One-time generator: breeding section data for the plant breeder.

The original PlantStudio breeder iterates udomain.sectionManager.sections ->
section.sectionItems (field numbers) and breeds each parameter according to
its type. That section structure is built at startup by umakepm.pas.py's
addParameterForSection(section, orthogonal, PdParameter().make(...)) calls,
in call order (the converted_source tab\\Parameters.tab columns "section" /
"section order" / "parameter order" encode the same data, but the constructor
calls are the exact code the original ran, with no column-format ambiguity).
Orthogonal ("other sections") sections are NOT part of sectionManager.sections
and are never bred - each parameter is bred exactly once, from its main
section, in first-mention order.

Writes plantstudio_blender/core/breeding_sections.json:
    [{"name": <section>, "fields": [fieldID, ...]}, ...]

Asserts: <= 30 sections (kMaxBreedingSections) and every non-header field ID
resolves in param_registry.json. Repo-only tool (never shipped/committed is
fine either way - the JSON output is what the addon bundles).
"""

import json
import os
import re

SRC = os.path.join(r"C:\Users\vitvin_v\dev\digital-garden\examples",
                   "PlantStudio-master", "converted_source", "used",
                   "umakepm.pas.py")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                   "plantstudio_blender", "core", "breeding_sections.json")
REGISTRY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                        "plantstudio_blender", "core", "param_registry.json")

CALL_RE = re.compile(
    r'addParameterForSection\("([^"]*)",\s*"[^"]*",\s*'
    r'uparams\.PdParameter\(\)\.make\(\d+,\s*"([^"]*)"')

with open(SRC, encoding="utf-8") as f:
    calls = CALL_RE.findall(f.read())
assert calls, "no addParameterForSection calls found - source moved?"

sections = []
index = {}
for section_name, field_id in calls:
    if section_name not in index:
        index[section_name] = len(sections)
        sections.append({"name": section_name, "fields": []})
    sections[index[section_name]]["fields"].append(field_id)

assert len(sections) <= 30, f"kMaxBreedingSections exceeded: {len(sections)}"

with open(REGISTRY, encoding="utf-8") as f:
    registry_ids = {e["id"] for e in json.load(f)}
unresolved = [fid for s in sections for fid in s["fields"]
              if fid != "header" and fid not in registry_ids]
assert not unresolved, f"field IDs missing from param_registry: {unresolved}"

with open(OUT, "w", encoding="utf-8") as f:
    json.dump(sections, f, indent=1)
    f.write("\n")

params = sum(1 for s in sections for fid in s["fields"] if fid != "header")
print(f"{len(sections)} sections, {params} parameters -> {os.path.abspath(OUT)}")
for s in sections:
    print(f"  {s['name']}: {sum(1 for x in s['fields'] if x != 'header')} params")
