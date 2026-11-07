#!/usr/bin/env python3
"""Export a pi session (JSONL) to readable Markdown.

Full fidelity of the human/assistant text; tool calls and their results are truncated so
the transcript stays greppable instead of 5 MB of hexdumps. The raw JSONL is kept next to
the output as .jsonl.gz.

  python3 tools/export_session.py <session.jsonl> <out.md> [--tool-chars N]
"""
import gzip
import json
import sys
from pathlib import Path

TOOL_CHARS = 400
TEXT_LIMIT = 100_000


def text_of(content):
    if isinstance(content, str):
        return content
    out = []
    for block in content or []:
        if isinstance(block, str):
            out.append(block)
        elif isinstance(block, dict):
            if block.get("type") == "text":
                out.append(block.get("text", ""))
            elif block.get("type") == "toolCall":
                args = block.get("arguments") or block.get("input") or {}
                a = json.dumps(args, ensure_ascii=False)
                if len(a) > TOOL_CHARS:
                    a = a[:TOOL_CHARS] + " …"
                out.append(f"`→ {block.get('name','tool')}` {a}")
            elif block.get("type") == "thinking":
                t = block.get("thinking") or block.get("text") or ""
                if t:
                    out.append(f"<details><summary>thinking</summary>\n\n{t[:2000]}\n\n</details>")
    return "\n\n".join(out)


def main():
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    tool_chars = TOOL_CHARS
    if "--tool-chars" in sys.argv:
        tool_chars = int(sys.argv[sys.argv.index("--tool-chars") + 1])

    lines = []
    model = None
    for raw in src.read_text(errors="replace").splitlines():
        try:
            rec = json.loads(raw)
        except json.JSONDecodeError:
            continue
        t = rec.get("type")
        if t == "session":
            lines.append(f"# Session {rec.get('id')}\n\n"
                         f"* cwd: `{rec.get('cwd')}`\n* started: {rec.get('timestamp')}\n")
        elif t == "model_change":
            model = f"{rec.get('provider')}/{rec.get('modelId')}"
            lines.append(f"\n> model: `{model}`\n")
        elif t == "message":
            m = rec.get("message", {})
            role = m.get("role", "?")
            body = text_of(m.get("content"))
            if role == "toolResult":
                name = m.get("toolName") or m.get("name") or "tool"
                body = body.strip()
                if len(body) > tool_chars:
                    body = body[:tool_chars] + f"\n… ({len(body)} chars total)"
                lines.append(f"<details><summary>result: {name}</summary>\n\n```\n{body}\n```\n\n</details>\n")
            elif role == "system":
                continue
            else:
                if len(body) > TEXT_LIMIT:
                    body = body[:TEXT_LIMIT] + "\n… (truncated)"
                who = "user" if role == "user" else "assistant"
                lines.append(f"\n## {who}\n\n{body}\n")

    dst.write_text("\n".join(lines))
    gz = dst.with_suffix(".jsonl.gz")
    with gzip.open(gz, "wt", errors="replace") as f:
        f.write(src.read_text(errors="replace"))
    print(f"wrote {dst} ({dst.stat().st_size/1e6:.2f} MB) and {gz.name} ({gz.stat().st_size/1e6:.2f} MB)")


if __name__ == "__main__":
    main()
