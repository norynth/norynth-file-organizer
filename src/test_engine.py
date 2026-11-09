import os, shutil, tempfile, time, json, sys
tmp = tempfile.mkdtemp()
os.environ["NORYNTH_DATA_DIR"] = os.path.join(tmp, "appdata")
import engine
from engine import Engine, Options

def mk(path, data=b"x", mtime=None):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f: f.write(data)
    if mtime: os.utime(path, (mtime, mtime))

src = os.path.join(tmp, "src"); dst = os.path.join(tmp, "dst")
mk(f"{src}/photo_2024-03-15_101530.jpg", b"A"*100)
mk(f"{src}/IMG_20230704.png", b"B"*200)
mk(f"{src}/invoice_march.pdf", b"C"*300)
mk(f"{src}/copy_of_invoice.pdf", b"C"*300)          # duplicate content
mk(f"{src}/notes.txt", b"meeting agenda and report")
mk(f"{src}/sub/deep.py", b"print(1)")
mk(f"{src}/.hidden", b"h")
mk(f"{src}/Thumbs.db", b"t")
mk(f"{src}/clash/notes.txt", b"other notes text")
e = Engine()
print("presets loaded:", [p["name"] for p in e.presets["presets"]])

# 1. dry run changes nothing
o = Options(source=src, dest=dst, strategy="type", recursive=True)
before = sorted(os.listdir(src))
p = e.plan(o)
assert sorted(os.listdir(src)) == before and not os.path.exists(dst), "dry run touched disk"
s = p["summary"]; print("summary", s)
assert s["duplicate"] == 1, s
names = {i["src_name"]: i for i in p["items"]}
assert ".hidden" not in names and "Thumbs.db" not in names
assert names["deep.py"]["folder"] == "Code"
print("smart names:", [i["rel"] for i in p["items"] if i["status"]=="ready"])
assert any("20240315_101530" in i["rel"] for i in p["items"])

# 2. execute, then undo restores exactly
snapshot = {os.path.relpath(os.path.join(r,f), src) for r,_,fs in os.walk(src) for f in fs}
res = e.execute(p, excluded=[])
assert res["status"] == "completed" and res["errors"] == 0, res
assert res["done"] == s["ready"]
moved = [os.path.join(r,f) for r,_,fs in os.walk(dst) for f in fs]
assert len(moved) == s["ready"]
u = e.undo(res["id"]); print("undo", u)
after = {os.path.relpath(os.path.join(r,f), src) for r,_,fs in os.walk(src) for f in fs}
# dups were never moved, so the set must equal the original
assert after == snapshot, (snapshot ^ after)
assert not [x for _,_,fs in os.walk(dst) for x in fs]
assert e.history()[0]["undone"] is True
try: e.undo(res["id"]); assert False
except ValueError as ex: print("double undo blocked:", ex)

# 3. copy mode + exclusion + undo removes copies
o2 = Options(source=src, dest=dst, strategy="size", copy_mode=True, smart_rename=False)
p2 = e.plan(o2)
r2 = e.execute(p2, excluded=[p2["items"][0]["id"]])
assert r2["done"] == p2["summary"]["ready"] - 1
assert os.path.exists(f"{src}/notes.txt")
e.undo(r2["id"])
assert not [x for _,_,fs in os.walk(dst) for x in fs]

# 4. same-name clash in one plan gets unique names
o3 = Options(source=src, dest=dst, strategy="type", recursive=True, smart_rename=False)
p3 = e.plan(o3)
notes = [i for i in p3["items"] if i["src_name"] == "notes.txt"]
assert len(notes) == 2 and notes[0]["dest"] != notes[1]["dest"], notes
print("clash handled:", [n["rel"] for n in notes])

# 5. rules + template traversal safety
e.save_rules([{"name":"PDFs by year","ext":"pdf","dest":"../../evil/{year}/{ext}"},
              {"name":"no conditions","dest":"Nope"}])
p4 = e.plan(Options(source=src, dest=dst, skip_duplicates=False))
pdf = [i for i in p4["items"] if i["src_name"].endswith(".pdf")][0]
print("rule dest:", pdf["rel"], pdf["rule"])
assert pdf["rel"].startswith("evil/") and ".." not in pdf["rel"]
assert engine._inside(pdf["dest"], dst)
assert all(i["rule"] != "Rule: no conditions" for i in p4["items"])

# 6. preset
e.rules = []
p5 = e.plan(Options(source=src, dest=dst, preset="Code & Scripts", recursive=True, skip_duplicates=False))
d = [i for i in p5["items"] if i["src_name"]=="deep.py"][0]
print("preset dest:", d["rel"], d["rule"]); assert d["rel"].startswith("Code/Python/")

# 7. dest inside source is not re-scanned; in-place detection
inner = os.path.join(src, "organized")
mk(f"{inner}/Documents/already.txt", b"zzz")
p6 = e.plan(Options(source=src, dest=inner, recursive=True))
assert all("organized" not in i["src"] for i in p6["items"])
mk(f"{tmp}/inplace/Images/a.jpg", b"q")
p7 = e.plan(Options(source=f"{tmp}/inplace", dest=f"{tmp}/inplace", recursive=True, smart_rename=False))
assert p7["items"][0]["status"] == "inplace", p7["items"][0]

# 8. dedupe against destination
mk(f"{tmp}/s2/new_copy.pdf", b"C"*300)
mk(f"{tmp}/d2/Documents/old.pdf", b"C"*300)
p8 = e.plan(Options(source=f"{tmp}/s2", dest=f"{tmp}/d2"))
assert p8["items"][0]["status"] == "duplicate", p8["items"][0]

# 9. duplicates finder + quarantine + undo
groups = e.find_duplicates([src])
print("dup groups:", [(len(g["files"]), g["size"]) for g in groups])
assert len(groups) == 1 and len(groups[0]["files"]) == 2
extra = groups[0]["files"][1]["path"]
q = e.quarantine([extra], src)
assert not os.path.exists(extra) and q["done"] == 1
e.undo(q["id"]); assert os.path.exists(extra)

# 10. cancel
ev = __import__("threading").Event(); ev.set()
try: e.plan(o, cancel=ev); assert False
except engine.Cancelled: print("cancel ok")

# 11. report export + validation
rep = os.path.join(tmp, "r.csv"); n = e.export_report(res["id"], rep); print("report rows", n)
try: e.plan(Options(source="/nope", dest=dst)); assert False
except ValueError as ex: print("validation:", ex)
print("deps:", {k: v[0] for k, v in engine.DEPS.items()})
print("ALL ENGINE TESTS PASSED")
shutil.rmtree(tmp)
