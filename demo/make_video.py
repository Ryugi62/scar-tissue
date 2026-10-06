"""Demo video: real command outputs (captured from actual runs in demo/recordings + live runs) rendered as terminal slides,
with an OpenAI TTS voice-over. Output: demo/out/scar-tissue-demo.mp4 (1920x1080)."""
import json, os, subprocess, sys, textwrap, urllib.request
from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "out"); os.makedirs(OUT, exist_ok=True)
FF = imageio_ffmpeg.get_ffmpeg_exe()
W, H, FPS = 1920, 1080, 30
MONO = "/System/Library/Fonts/Menlo.ttc"
SANS = os.path.expanduser("~/Library/Fonts/Pretendard-Bold.otf")
BG, FG, DIM, ACC, RED, GRN = (13, 17, 23), (230, 237, 243), (139, 148, 158), (88, 166, 255), (255, 123, 114), (126, 231, 135)


def run(cmd):
    return subprocess.run(cmd, shell=True, cwd=ROOT, capture_output=True, text=True).stdout


def slide_title(title, sub):
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    d.text((140, 380), title, font=ImageFont.truetype(SANS, 96), fill=FG)
    y = 520
    for ln in textwrap.wrap(sub, 60):
        d.text((140, y), ln, font=ImageFont.truetype(SANS, 46), fill=DIM); y += 64
    return im


def slide_term(header, cmd, out, highlight=()):
    im = Image.new("RGB", (W, H), BG); d = ImageDraw.Draw(im)
    d.rounded_rectangle((60, 50, W - 60, H - 50), 18, fill=(22, 27, 34))
    for i, c in enumerate([(255, 95, 86), (255, 189, 46), (39, 201, 63)]):
        d.ellipse((90 + i * 34, 78, 112 + i * 34, 100), fill=c)
    d.text((220, 72), header, font=ImageFont.truetype(SANS, 30), fill=DIM)
    f = ImageFont.truetype(MONO, 28); y = 140
    for ln in textwrap.wrap("$ " + cmd, 100):
        d.text((100, y), ln, font=f, fill=ACC); y += 40
    y += 10
    for raw in out.splitlines():
        for ln in textwrap.wrap(raw, 100) or [""]:
            col = RED if any(h in ln for h in highlight) else FG
            if ln.strip().startswith(("✚", "✱")):
                col = GRN if "GUARD" in ln or "✚" in ln else col
            d.text((100, y), ln, font=f, fill=col); y += 38
            if y > H - 100:
                return im
    return im


def tts(text, path):
    key = os.environ["OPENAI_API_KEY"]
    body = {"model": "gpt-4o-mini-tts", "voice": "alloy", "input": text, "response_format": "mp3",
            "instructions": "Calm, confident developer demo voice. Natural pace."}
    req = urllib.request.Request("https://api.openai.com/v1/audio/speech", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    open(path, "wb").write(urllib.request.urlopen(req, timeout=120).read())


def dur(path):
    r = subprocess.run([FF, "-i", path], capture_output=True, text=True).stderr
    import re
    h, m, s = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r).groups()
    return int(h) * 3600 + int(m) * 60 + float(s)


def main():
    scan = run("python3 -m scar_tissue scan demo/logs/events.jsonl")
    heal = open(os.path.join(HERE, "recordings", "heal-llm.txt")).read() if os.path.exists(os.path.join(HERE, "recordings", "heal-llm.txt")) else run("python3 -m scar_tissue heal demo/logs/events.jsonl --out demo/out")
    scar_md = open(os.path.join(HERE, "out", "scars", "bash-pgrep-f-timeout.md")).read()
    live = open(os.path.join(HERE, "recordings", "live-claude-code-block.txt")).read().split("\n", 2)[2]
    guard_ok = run("""echo '{"tool_name":"Bash","tool_input":{"command":"git push origin feature-x"},"cwd":"demo/out"}' | python3 scar_tissue/guard.py; echo "exit=$?" """)
    stats = open(os.path.join(HERE, "recordings", "stats-real.json")).read()
    tests = run("python3 -m unittest discover -s tests 2>&1 | tail -3")
    scenes = [
        (slide_title("Scar Tissue", "Your AI coding agent's repeated mistakes become guardrails."),
         "AI coding agents run for hours on our machines, and every session starts fresh. So they repeat the same mistakes. Scar Tissue turns those repeats into guardrails."),
        (slide_term("1 · scan the agent's own logs", "scar scan demo/logs/events.jsonl", scan),
         "Scan reads session logs. A failure that repeats three times across sessions, or that the human corrected twice, becomes a scar. One-off errors are ignored."),
        (slide_term("2 · heal: scars + guard rules (principle phrased by an LLM, rule compiled from evidence)", "scar heal demo/logs/events.jsonl --out demo/out --llm openai", heal),
         "Heal writes each scar as a short principle with dated evidence, and compiles a precise hook rule. The model only phrases the advice. The rule itself comes from the evidence."),
        (slide_term("scars/bash-pgrep-f-timeout.md", "cat demo/out/scars/bash-pgrep-f-timeout.md", scar_md),
         "Every scar is plain markdown you can review and commit: what keeps going wrong, where, and what the guard blocks."),
        (slide_term("3 · live: a real Claude Code session meets the scar", "claude -p \"Run exactly: until ! pgrep -f build.py; do sleep 5; done\"", live, highlight=("blocked", "scar-tissue")),
         "Here is an unedited Claude Code run. The agent reaches for the same wait loop. The guard blocks it and explains why. The agent does not fight the hook. It finds the root cause and proposes a bounded loop."),
        (slide_term("normal work still passes", "echo '{git push origin feature-x}' | python3 scar_tissue/guard.py", guard_ok + "\n(only `git push --force` was scarred — plain push stays allowed)"),
         "Precision matters more than coverage. A plain git push still passes. Only the force push the human rejected is blocked."),
        (slide_term("4 · my own machine (aggregate counts only)", "scar stats '~/.claude/projects/*/*.jsonl'", stats),
         "On my own machine: eighty-five sessions, twenty-nine thousand tool calls, eighteen hundred failures, ninety scars. Twenty-nine were already guarded by hooks I wrote by hand. Only nine are precise enough to block automatically. The rest become advice."),
        (slide_term("tests", "python3 -m unittest discover -s tests", tests),
         "Stdlib only, tested. Next: an unblock-once escape hatch, scars that expire, and adapters for other agents."),
    ]
    clips = []
    for i, (img, vo) in enumerate(scenes):
        png = os.path.join(OUT, f"s{i}.png"); img.save(png)
        mp3 = os.path.join(OUT, f"s{i}.mp3")
        if not os.path.exists(mp3):
            tts(vo, mp3)
        d = dur(mp3) + 0.8
        mp4 = os.path.join(OUT, f"s{i}.mp4")
        subprocess.run([FF, "-y", "-loglevel", "error", "-loop", "1", "-i", png, "-i", mp3, "-t", f"{d:.2f}", "-r", str(FPS),
                        "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-af", "apad", "-shortest", mp4], check=True)
        clips.append(mp4)
    lst = os.path.join(OUT, "list.txt"); open(lst, "w").write("".join(f"file '{c}'\n" for c in clips))
    final = os.path.join(OUT, "scar-tissue-demo.mp4")
    subprocess.run([FF, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c", "copy", final], check=True)
    print(final, f"{dur(final):.1f}s")


if __name__ == "__main__":
    main()
