"""Stand-in for a slow build: runs ~20 s, then writes build/out.txt."""
import os, time
time.sleep(20)
os.makedirs("build", exist_ok=True)
open("build/out.txt", "w").write("build ok: 42 files compiled\n")
