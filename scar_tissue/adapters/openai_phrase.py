"""Optional adapter: phrase a scar's principle with an OpenAI model. Falls back to the template on any error."""
import json, os, urllib.request


def phrase(scar, fallback, model="gpt-5.4-mini"):
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        return fallback
    examples = [e.command[:160] for e in scar.failures[:3]] + [e.text[:160] for e in scar.corrections[:2]]
    prompt = ("You write one-sentence guardrails for an AI coding agent. The agent repeatedly failed with this pattern.\n"
              f"Signature: {scar.signature}\nExamples: {json.dumps(examples)}\nError snippets: "
              f"{json.dumps([e.text[:160] for e in scar.failures[:3]])}\n"
              "Write ONE imperative sentence (max 30 words): what to avoid and what to do instead. No preamble.")
    body = {"model": model, "input": prompt}
    req = urllib.request.Request("https://api.openai.com/v1/responses", data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            d = json.load(r)
        for o in d.get("output", []):
            for c in o.get("content", []) or []:
                if c.get("type") in ("output_text", "text") and c.get("text", "").strip():
                    return c["text"].strip()
    except Exception:
        pass
    return fallback
