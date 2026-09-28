"""Write the prompt files out of the console's prompt-config document.

Reports what it changed. The deployment's text is authoritative, and a value that surprises this
repo is news for the reader of the diff, not an error here -- with one exception: WITHHELD. It
also insists on telling you when the deployment is NOT in `replace` mode, because this plugin
reproduces only that mode and an `append` deployment means the agent file overstates its case.
"""
import hashlib
import json
import os
import re
import sys

PROMPT_KEY = "system_message_suffix_append"
FILES = {
    PROMPT_KEY: "prompt/system-prompt.md",
    "response_quality": "prompt/response-quality.md",
}

#: Passages of the operator prompt this plugin does not carry, because it is published and they
#: are the deployment's alone. They are recorded by the SHA-256 of their text (`digest`), so the
#: published copy does not hold them in any form. Every one must be found in what the deployment
#: serves: a passage reworded there no longer matches its digest, and the sync stops rather than
#: publish the new wording before someone has read it.
WITHHELD = {
    "1591887737accdc8dddc0adbdf4c93790a30de48e7907190edd9460e81b10a3f": "principle 0",
    "5f1f80ff796acf0730f97d090ef8b4d7d0bcf1b5268c41c6d54249b97f298fa6":
        "the second paragraph of the introduction",
}
#: A passage: a run of lines that are not blank. Blank lines separate one from the next.
PASSAGE = re.compile(r"(?:[^\n]*\S[^\n]*(?:\n|\Z))+")
BLANK_LINES = re.compile(r"(?:[^\S\n]*\n)*")


def digest(passage: str) -> str:
    """The SHA-256 of a passage as WITHHELD records it, each line's trailing whitespace removed:
    whitespace a line gains or loses at its end is not a rewording."""
    lines = [line.rstrip() for line in passage.rstrip("\n").split("\n")]
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def withhold(text: str) -> "tuple[str, list[str]]":
    """`text` without the WITHHELD passages, and what WITHHELD calls each one it did not find.

    A passage goes with the blank lines after it, so the gap it leaves is the one before it and
    the rest of the text is unchanged byte for byte."""
    parts, found, at = [], set(), 0
    for match in PASSAGE.finditer(text):
        key = digest(match.group(0))
        if key not in WITHHELD:
            continue
        found.add(key)
        parts.append(text[at:match.start()])
        at = BLANK_LINES.match(text, match.end()).end()
    parts.append(text[at:])
    return "".join(parts), [what for key, what in WITHHELD.items() if key not in found]


def withheld_in(text: str) -> "list[str]":
    """What WITHHELD calls each of its passages that `text` still contains."""
    present = {digest(match.group(0)) for match in PASSAGE.finditer(text)}
    return [what for key, what in WITHHELD.items() if key in present]


def main() -> int:
    root = sys.argv[1]
    try:
        doc = json.load(sys.stdin)
    except ValueError:
        print("sync-prompt: the console did not return JSON", file=sys.stderr)
        return 1
    keys = {k.get("key"): k for k in doc.get("keys") or [] if isinstance(k, dict)}
    if not keys:
        print("sync-prompt: no keys in the document", file=sys.stderr)
        return 1

    values = {}
    for key, relative in FILES.items():
        entry = keys.get(key)
        if entry is None:
            print(f"sync-prompt: the deployment has no {key} key", file=sys.stderr)
            return 1
        values[relative] = entry.get("value") or ""

    # Before anything is written, so a passage that moved leaves the tree as it was.
    prompt = FILES[PROMPT_KEY]
    values[prompt], missing = withhold(values[prompt])
    if missing:
        for what in missing:
            print(f"sync-prompt: the deployment's prompt no longer has {what} as WITHHELD records "
                  "it, so it may have been reworded there. Read its new text, then update WITHHELD "
                  "in scripts/lib/write_prompt.py. Nothing was written.", file=sys.stderr)
        return 1
    print(f"withheld   {len(WITHHELD)} passages of {prompt} (WITHHELD in scripts/lib/write_prompt.py)")

    for relative, value in values.items():
        path = os.path.join(root, relative)
        try:
            with open(path) as handle:
                before = handle.read()
        except OSError:
            before = None
        if before == value:
            print(f"unchanged  {relative}  ({len(value)} chars)")
            continue
        with open(path, "w") as handle:
            handle.write(value)
        was = "new file" if before is None else f"was {len(before)} chars"
        print(f"UPDATED    {relative}  ({len(value)} chars, {was})")

    mode = (keys.get("system_prompt_mode") or {}).get("value", "").strip()
    if mode != "replace":
        print(
            f"NOTE: the deployment's system_prompt_mode is {mode!r}, not 'replace'. There, Claude "
            "Code keeps its own prompt and the operator's text is appended to it. This plugin "
            "always replaces, because that is what running an agent as the main session does.",
            file=sys.stderr,
        )
    suffix = (keys.get("user_message_suffix") or {}).get("value", "")
    if suffix.strip():
        print(
            "NOTE: the deployment now ships a non-empty user_message_suffix. It is not vendored "
            "here; set it as this plugin's user_message_suffix option to match.",
            file=sys.stderr,
        )
    deployment = doc.get("deployment") or {}
    print(f"source: {deployment.get('name', '?')} ({deployment.get('publicBaseUrl', '?')})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
