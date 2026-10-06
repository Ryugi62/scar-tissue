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
    """Voice-over: edge-tts neural voice (free) if $EDGE_TTS points to the CLI, else OpenAI TTS."""
    if os.environ.get("EDGE_TTS"):
        subprocess.run([os.environ["EDGE_TTS"], "--voice", "en-US-AndrewMultilingualNeural", "--rate", "+4%", "--text", text,
                        "--write-media", path], check=True, capture_output=True)
        return
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
    rec = lambda name: open(os.path.join(HERE, "recordings", name)).read()
    demo = run("python3 -m scar_tissue demo")
    scan_part, guard_part = demo.split("3) guard", 1)
    live = rec("live-claude-code-block.txt").split("── agent → Bash ──", 1)[1]
    live_short = "── agent → Bash ──" + live.split("── agent (final answer) ──")[0]
    live_short = "\n".join(l for l in live_short.splitlines() if l.strip() and not l.startswith(("drwx", "-rw-", "total ", "---")))
    live_short = live_short.replace("PreToolUse:Bash hook error: [python3 ~/dev/hack47-offgrid/scar_tissue/guard.py]: ", "")
    live_short = live_short.replace(" (If you are sure this case is different, append `# scar-ok: <reason>` to the command.)", "")
    import re as _re
    scan_part = _re.sub(r"in /\S+/(scar-demo-\w+)", r"in $TMPDIR/\1", scan_part)
    guard_part = "\n".join((l[:118] + " …") if "↳" in l and len(l) > 120 else l for l in guard_part.splitlines())
    stats = json.loads(rec("stats-real.json")); hold = json.loads(rec("holdout-real.json")); swe = json.loads(rec("swe-agent-public.json"))
    pct = lambda a, b: f"{100 * a / b:.1f}%" if 100 * a / b >= 1 else f"{100 * a / b:.2f}%"
    names = {"bash-word-zsh-equals": "unquoted `=` word in zsh", "bash-include-zsh-nomatch": "unquoted --include=* glob in zsh",
             "bash-pdffonts-missing-command": "pdffonts not installed"}
    rule_txt = "\n".join(f"  {names.get(r['id'], r['id']):34s} {r['matched_failures']:>5,} failures · {r['sessions']:>3} sessions · {r['successes_blocked']:>2} wrong blocks"
                         for r in stats["rules"])
    stats_txt = rec("stats-real.txt") + "\nrules learned:\n" + rule_txt
    fc = stats["failure_cost"]; inc = [r for r in stats["rules"] if r["id"] == "bash-include-zsh-nomatch"][0]
    hold_txt = "\n".join([
        f"learn from the earliest {hold['train_sessions']:,} sessions → {hold['guard_rules']} rules; replay the later {hold['test_sessions']:,}:",
        f"  failures that would have been blocked   {hold['test_failures_blocked']:,} of {hold['test_failures']:,}  ({pct(hold['test_failures_blocked'], hold['test_failures'])})",
        f"  successful calls wrongly blocked        {hold['test_successes_blocked']} of {hold['test_successes']:,}  ({pct(hold['test_successes_blocked'], hold['test_successes'])})",
        "  same result with the demotion ratio at 10, 20 or 50 (sensitivity-real.json)",
        "", "silent failures — exit 0, but zsh aborted the search:",
        f"  --include=* failures that exited 0          {inc['matched_silent']:,} of {inc['matched_failures']:,}",
        f"  ...never re-run: agent moved on, 'nothing found'   {fc['bash-include-zsh-nomatch']['silent_never_fixed']}",
        "", f"zsh failures per 1,000 shell calls: " + " → ".join(f"{t['per_1000']:.0f}" for t in stats["zsh_trend_per_1000_bash_calls"]) + "  (Sep 1 → Oct 6)",
    ])
    tests = run("python3 -m unittest discover -s tests 2>&1 | tail -3")
    scenes = [
        (slide_title("Scar Tissue", "Your AI coding agent's repeated mistakes become guardrails — learned from its own logs."),
         "Coding agents start every session fresh, so they repeat the same mistakes. On my laptop, almost half of my agent's failed shell commands came from a few habits it never unlearned. Scar Tissue finds them in the logs, and blocks them."),
        (slide_term("1 · scan + heal (bundled demo logs, no network)", "pipx install git+https://github.com/Ryugi62/scar-tissue && scar demo", scan_part),
         "Scan reads the agent's session logs. A failure that repeats across sessions becomes a scar. When the error text names the cause, like zsh choking on an unquoted equals sign, or a timeout binary that isn't installed, the cause becomes the signature."),
        (slide_term("2 · the guard: same habit blocked, the agent's own fix allowed", "scar demo   # (continued)", "3) guard" + guard_part, highlight=("BLOCKED",)),
         "Each scar compiles into a Claude Code hook rule, matched by a small shell tokenizer, not a regex. The habit is blocked with the reason, and the fix the agent found last time is shown and allowed. Plain git push and normal work pass."),
        (slide_term("3 · live (prompted): a real Claude Code session meets the scar", "claude -p \"A build is running … Wait for it using: until ! pgrep -f build.py; do sleep 2; done …\"", live_short, highlight=("BLOCKED", "scar-tissue")),
         "Here the agent is asked to use the old wait loop. The hook blocks it and shows what worked before. The agent uses that fix, the guard lets it through, and the build finishes in four turns."),
        (slide_term("4 · every transcript on my laptop (aggregate counts only)", "scar stats '~/.claude/projects/**/*.jsonl' --table", stats_txt, highlight=("of",)),
         f"On my laptop: {stats['sessions']:,} sessions and {stats['tool_calls'] // 1000} thousand tool calls. Three learned rules match {pct(stats['bash_failures_matched_by_rules'], stats['bash_failures'])} of the agent's failed shell commands, and would block {stats['bash_successes_blocked']} of {stats['bash_successes'] // 1000} thousand successful ones. Every candidate is replayed against the agent's own successful history first."),
        (slide_term("5 · would it have helped? learn from the past, replay the future", "scar holdout '~/.claude/projects/**/*.jsonl'   (+ failure_cost, trend from stats-real.json)", hold_txt),
         f"Learned only from earlier sessions, the rules would have blocked {pct(hold['test_failures_blocked'], hold['test_failures'])} of later failures. The silent ones matter most: {fc['bash-include-zsh-nomatch']['silent_never_fixed']} times a search was aborted by zsh, printed nothing, and the agent moved on as if nothing was found."),
        (slide_term("tests · standard library only", "python3 -m unittest discover -s tests && scar report '<logs>'", tests),
         "One line to install, scar demo to try, scar report for a read-only look at your own logs. Standard library only, every rule reviewable as markdown. Next: Codex and Cursor adapters, and team scars shared through the repo."),
    ]
    clips = []
    for i, (img, vo) in enumerate(scenes):
        png = os.path.join(OUT, f"s{i}.png"); img.save(png)
        mp3 = os.path.join(OUT, f"s{i}.mp3")
        txt = mp3 + ".txt"
        if not (os.path.exists(mp3) and os.path.exists(txt) and open(txt).read() == vo):
            tts(vo, mp3); open(txt, "w").write(vo)
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
