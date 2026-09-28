"""The plugin installs on Codex as itself: one marketplace, one plugin id, its own MCP file.

Codex reads a Claude plugin's files when it finds nothing of its own, and what it gets that way is
a plugin that installs and then half works: no card, no starter prompts, Claude's hooks loaded as
untrusted Codex hooks, and an MCP server whose Claude-only `headersHelper` Codex ignores, so it
connects with no key and says nothing. The Codex package is three files beside the Claude ones, and
the guards below hold each to what Codex does with it (Codex CLI 0.153.4, its source and a run):

* `.agents/plugins/marketplace.json` is the file Codex looks for first; once it exists Codex never
  reads `.claude-plugin/marketplace.json`. It must carry the Claude file's marketplace name, because
  that name is the `@suffix` of the plugin id: `novadde@novadde-plugin` is what Codex sends as
  `_meta.plugin_id`, and what every user override in `config.toml` is keyed on.
* `plugins/novadde/.codex-plugin/plugin.json` is Codex's manifest. `"hooks": {}` is the only way to
  load no hooks: with the field absent Codex loads Claude's `hooks/hooks.json` instead. It names the
  MCP file, and when it does, Codex reads that file and no other.
* `plugins/novadde/.codex.mcp.json` is Codex's own MCP file, because the keys Codex needs cannot go
  in Claude's. A `tools` table in `.mcp.json` -- even `"tools": {}` -- makes Claude Code 2.1.267
  drop the whole server while `claude plugin validate --strict` still passes the file: validate
  prints "Validation passed" and `claude mcp list` then prints "No MCP servers configured". So the
  Codex file carries the per-tool approvals, and the Claude file is held to the four keys Claude
  reads. That is a static check, and the only kind CI has that can see the drop: the validator
  passes the file, and no Claude session runs in CI.
* The key is read by one helper string, byte for byte the same in both MCP files and run here the
  way Codex runs it, on every hand-edit of the key file that test_key_file_credential.py runs
  Claude's copy on.

Written for the oldest python3 a Mac ships (3.9) as well as CI's.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import REPO, Checks  # noqa: E402
from _tools import READ_TOOLS, SPEND_TOOLS  # noqa: E402
# The key-file cases and their helpers are test_key_file_credential's, imported rather than copied:
# Codex's copy of the helper is held to exactly the files Claude's is, so a case added there is a
# case run here.
from test_key_file_credential import (  # noqa: E402
    BEARER, KEY_CASES, NO_KEY_CASES, bearer_of, write_key_file)

PLUGIN = os.path.join(REPO, "plugins", "novadde")
CLAUDE_MARKETPLACE = os.path.join(REPO, ".claude-plugin", "marketplace.json")
CODEX_MARKETPLACE = os.path.join(REPO, ".agents", "plugins", "marketplace.json")
CLAUDE_MANIFEST = os.path.join(PLUGIN, ".claude-plugin", "plugin.json")
CODEX_MANIFEST = os.path.join(PLUGIN, ".codex-plugin", "plugin.json")
CLAUDE_MCP = os.path.join(PLUGIN, ".mcp.json")
CODEX_MCP_NAME = ".codex.mcp.json"
CODEX_MCP = os.path.join(PLUGIN, CODEX_MCP_NAME)
CLAUDE_HOOKS = os.path.join(PLUGIN, "hooks", "hooks.json")
STATUS_SKILL = os.path.join(PLUGIN, "skills", "status", "SKILL.md")
BUILT_VERBS = os.path.join(PLUGIN, "prompt", ".built-verbs")

# The server name both hosts use. Claude's hook matchers match it, and a Codex user's
# `[plugins."novadde@novadde-plugin".mcp_servers.model_platform]` override is keyed on it.
SERVER = "model_platform"
# The keys Claude Code reads from a remote server in `.mcp.json`. A Codex `tools` table beside them,
# even `"tools": {}`, makes 2.1.267 drop the server with no error. It tolerated the other Codex
# keys that were tried (`http_headers`, `http_headers_helper`, `disabled_tools`), but that is luck
# rather than a contract, so the check is an allowlist of what Claude reads, not a ban on `tools`.
CLAUDE_SERVER_KEYS = {"type", "url", "headers", "headersHelper"}
# Keys through which Codex would send an Authorization that outranks, or replaces, the helper's:
# "explicit bearer tokens and OAuth credentials take precedence over a helper-provided
# Authorization header" (Codex MCP docs). Any of them makes the key file one store of two.
CODEX_OTHER_CREDENTIALS = ("bearer_token", "bearer_token_env_var", "env_http_headers", "oauth",
                           "auth")
# The values of a tool's approval_mode in Codex 0.153.4 (config/src/mcp_types.rs, AppToolApproval).
APPROVAL_MODES = {"auto", "prompt", "writes", "approve"}

# What Codex 0.153.4 parses in `interface` (core-plugins/src/manifest.rs:76-112). An unknown key is
# ignored without a word, so a misspelt `defaultPrompts` would be a card with no starter prompts.
INTERFACE_STRINGS = ("displayName", "shortDescription", "longDescription", "developerName",
                     "category", "websiteURL", "privacyPolicyURL", "termsOfServiceURL",
                     "brandColor", "composerIcon", "logo", "logoDark")
INTERFACE_LISTS = ("capabilities", "screenshots", "defaultPrompt")
INTERFACE_ASSETS = ("composerIcon", "logo", "logoDark")
INTERFACE_URLS = ("websiteURL", "privacyPolicyURL", "termsOfServiceURL")
# The runtime's limits (manifest.rs:14-15, 482-558): at most three starter prompts of at most 128
# characters each, counted after whitespace is collapsed; a longer one is dropped with a WARN.
MAX_PROMPTS, MAX_PROMPT_CHARS = 3, 128
# The limits OpenAI's plugin directory applies to a submission's card, held now so the card needs no
# change to be submitted later. The runtime shows longer text; the directory refuses it. The rest of
# the manifest is not held to the directory: its validator (plugin-creator's validate_plugin.py, as
# Codex 0.153.4 installs it) rejects `hooks` and any `mcpServers` other than `.mcp.json`, and this
# plugin needs both -- `"hooks": {}` is how Codex loads no hooks, and the MCP file cannot be
# `.mcp.json` because Claude drops a server whose entry carries a `tools` table.
MAX_CHARS = {"displayName": 30, "shortDescription": 30, "longDescription": 4000,
             "developerName": 80}
MAX_CAPABILITIES, MAX_CAPABILITY_CHARS, MAX_URL_CHARS = 20, 120, 1024
DIRECTORY_CATEGORIES = {"Productivity", "Creativity", "Developer Tools", "Business & Operations",
                        "Data & Analytics", "Communication", "Education & Research", "Security",
                        "Finance", "Healthcare", "Travel", "Entertainment", "Other"}


def read(path):
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def load(path):
    """The parsed JSON at path, or None when the file is missing or is not JSON."""
    try:
        return json.loads(read(path))
    except (OSError, ValueError):
        return None


def entries(marketplace):
    """{plugin name: entry} of a marketplace document, {} for None."""
    plugins = (marketplace or {}).get("plugins") or []
    return {entry.get("name"): entry for entry in plugins if isinstance(entry, dict)}


def source_path(entry):
    """Where a marketplace entry's plugin lives, relative to the repo: either host's spelling."""
    source = entry.get("source")
    if isinstance(source, str):
        return source
    if isinstance(source, dict) and source.get("source") == "local":
        return source.get("path")
    return None


def server(path):
    """The model_platform server of an MCP file, or {}."""
    return ((load(path) or {}).get("mcpServers") or {}).get(SERVER) or {}


def codex_manifest():
    return load(CODEX_MANIFEST) or {}


def run_as_codex(helper, home, cwd):
    """Run the helper as Codex 0.153.4 does (rmcp-client/src/http_headers.rs:433-460).

    `sh -c <helper>`, with the environment cleared down to a few names that include HOME and PATH,
    stdin closed, and the session's working directory -- not the plugin's -- as cwd. Codex throws
    stderr away; it is kept here, and must be empty. Bytes, so a stray CR stays visible.
    """
    return subprocess.run(["sh", "-c", helper], env={"HOME": home, "PATH": "/usr/bin:/bin"},
                          cwd=cwd, stdin=subprocess.DEVNULL, capture_output=True, timeout=20)


def test_both_marketplaces_list_the_same_plugin_under_the_same_name(checks):
    print("the two marketplace files")
    claude, codex = load(CLAUDE_MARKETPLACE), load(CODEX_MARKETPLACE)
    checks.eq("(precondition) the Claude marketplace parses and is named novadde-plugin",
              (claude or {}).get("name"), "novadde-plugin")
    checks.eq(".agents/plugins/marketplace.json exists and parses", codex is not None, True)
    checks.eq("it has the Claude marketplace's name, so the plugin id is novadde@novadde-plugin "
              "on both hosts", (codex or {}).get("name"), (claude or {}).get("name"))
    checks.eq("its section title is Geodesic Intelligence",
              ((codex or {}).get("interface") or {}).get("displayName"), "Geodesic Intelligence")
    claude_entries, codex_entries = entries(claude), entries(codex)
    checks.eq("it lists the same plugins, by name", sorted(codex_entries), sorted(claude_entries))
    entry = codex_entries.get("novadde") or {}
    checks.eq("the entry's source is the local plugin directory",
              entry.get("source"), {"source": "local", "path": "./plugins/novadde"})
    where = [source_path(e) for e in (claude_entries.get("novadde") or {}, entry)]
    where = [os.path.realpath(os.path.join(REPO, p)) if p else None for p in where]
    checks.eq("(precondition) the Claude entry points at plugins/novadde",
              where[0], os.path.realpath(PLUGIN))
    checks.eq("which is the directory the Codex entry points at", where[1], where[0])
    checks.eq("it is available to install and asks for nothing until used",
              entry.get("policy"), {"installation": "AVAILABLE", "authentication": "ON_USE"})
    checks.eq("its category is Education & Research", entry.get("category"), "Education & Research")
    checks.eq("the directory's Codex manifest names the plugin as the entry does",
              codex_manifest().get("name"), "novadde")


def test_codex_manifest_version_equals_claude_manifest(checks):
    print(".codex-plugin/plugin.json against .claude-plugin/plugin.json")
    claude = load(CLAUDE_MANIFEST) or {}
    codex = codex_manifest()
    checks.eq("(precondition) the Claude manifest has a version", bool(claude.get("version")), True)
    checks.eq("the Codex manifest exists and parses", load(CODEX_MANIFEST) is not None, True)
    checks.eq("the same version, so a release bumps both or the check fails",
              codex.get("version"), claude.get("version"))
    checks.eq("the same name, which is the skill namespace (novadde:<skill>) on both hosts",
              codex.get("name"), claude.get("name"))


def test_codex_loads_no_hooks(checks):
    print("hooks on Codex")
    claude_hooks = (load(CLAUDE_HOOKS) or {}).get("hooks") or {}
    checks.eq("(precondition) Claude's hooks/hooks.json has hooks, which Codex loads when the "
              "manifest names none", bool(claude_hooks), True)
    codex = codex_manifest()
    checks.eq("the Codex manifest sets hooks, rather than leaving the default to Claude's file",
              "hooks" in codex, True)
    checks.eq("and sets it to {}: an inline hooks file with no events, so Codex loads none",
              codex.get("hooks"), {})


def test_codex_mcp_file_exists_and_its_url_is_a_literal_https_url(checks):
    print(".codex.mcp.json")
    codex = codex_manifest()
    checks.eq("the Codex manifest names its own MCP file, so Codex never reads Claude's",
              codex.get("mcpServers"), "./" + CODEX_MCP_NAME)
    document = load(CODEX_MCP)
    checks.eq("that file exists and parses", document is not None, True)
    checks.eq("it serves one server, under the name Claude's file uses",
              sorted(((document or {}).get("mcpServers") or {})), [SERVER])
    mine, claudes = server(CODEX_MCP), server(CLAUDE_MCP)
    url = mine.get("url")
    checks.eq("(precondition) Claude's file has a url to compare with",
              bool(claudes.get("url")), True)
    checks.eq("the url is https", isinstance(url, str) and url.startswith("https://"), True)
    checks.eq("and literal: Codex expands nothing in a url, so a $ or ${…} is sent as typed",
              isinstance(url, str) and "$" not in url, True)
    checks.eq("and it is Claude's url", url, claudes.get("url"))
    checks.eq("the type is http", mine.get("type"), "http")
    checks.eq("startup waits 20 s: the handshake is several round trips of about 0.9 s each",
              mine.get("startup_timeout_sec"), 20)
    checks.eq("a tool call waits 120 s: wait_for_job alone may block for 50",
              mine.get("tool_timeout_sec"), 120)
    checks.eq("the server is never required: required makes Codex refuse every session while the "
              "platform is down", mine.get("required", False), False)


def test_codex_approves_only_read_tools(checks):
    print("the tools Codex runs without asking")
    served = read(BUILT_VERBS).split()
    checks.eq("(precondition) READ_TOOLS and SPEND_TOOLS do not overlap",
              sorted(READ_TOOLS & SPEND_TOOLS), [])
    checks.eq("(precondition) every SPEND_TOOLS name is a verb the platform has served, so the "
              "check below cannot pass on a misspelling", sorted(SPEND_TOOLS - set(served)), [])
    mine = server(CODEX_MCP)
    tools = mine.get("tools")
    checks.eq("(precondition) .codex.mcp.json has a tools table", isinstance(tools, dict), True)
    tools = tools if isinstance(tools, dict) else {}
    approved = sorted(name for name, spec in tools.items()
                      if isinstance(spec, dict) and spec.get("approval_mode") == "approve")
    # An approval_mode Codex cannot parse is not ignored: the server's config fails to deserialize
    # and Codex drops the whole server, reads and all (mcp_types.rs AppToolApproval).
    checks.eq("every entry is an object whose approval_mode, if any, is one Codex parses",
              sorted(name for name, spec in tools.items()
                     if not isinstance(spec, dict)
                     or spec.get("approval_mode", "auto") not in APPROVAL_MODES), [])
    checks.eq("it approves no tool that spends credits, cancels work or uploads a file",
              sorted(set(approved) & SPEND_TOOLS), [])
    checks.eq("it approves only read tools", sorted(set(approved) - READ_TOOLS), [])
    checks.eq("and it approves every read tool, so each one runs under approval_policy=never "
              "(codex exec, scheduled tasks) and without a prompt in the app",
              approved, sorted(READ_TOOLS))
    checks.eq("no default approval mode, which would reach tools this list does not name",
              "default_tools_approval_mode" in mine, False)


def test_one_credential_reader(checks):
    print("the key helper, in both MCP files")
    claude_helper = server(CLAUDE_MCP).get("headersHelper")
    mine = server(CODEX_MCP)
    helper = mine.get("http_headers_helper")
    checks.eq("(precondition) Claude's file has a headersHelper string",
              isinstance(claude_helper, str) and bool(claude_helper.strip()), True)
    checks.eq("the Codex file has an http_headers_helper string",
              isinstance(helper, str) and bool(helper.strip()), True)
    checks.eq("byte for byte the string in Claude's file", helper, claude_helper)
    checks.eq("no Claude-only key in the Codex file, which Codex would ignore",
              sorted(k for k in ("headers", "headersHelper") if k in mine), [])
    checks.eq("no other credential that would outrank or replace the helper's",
              sorted(k for k in CODEX_OTHER_CREDENTIALS if k in mine), [])
    checks.eq("no static Authorization header",
              [k for k in (mine.get("http_headers") or {}) if k.lower() == "authorization"], [])
    if not isinstance(helper, str) or not helper.strip():
        return
    home = tempfile.mkdtemp(prefix="novadde-codex-helper-")
    session = tempfile.mkdtemp(prefix="novadde-codex-session-")
    try:
        for label, text in KEY_CASES:
            write_key_file(home, text)
            done = run_as_codex(helper, home, session)
            checks.eq(f"{label}: prints exactly {BEARER}", done.stdout, BEARER.encode())
            checks.eq(f"{label}: which is JSON with that one header",
                      bearer_of(done.stdout), "mp_x")
            checks.eq(f"{label}: nothing on stderr, exit 0",
                      (done.stderr, done.returncode), (b"", 0))
        for label, text in NO_KEY_CASES:
            write_key_file(home, text)
            done = run_as_codex(helper, home, session)
            checks.eq(f"{label}: prints {{}}, so Codex connects without a key and the catalog "
                      "still lists", done.stdout, b"{}")
            checks.eq(f"{label}: nothing on stderr, exit 0",
                      (done.stderr, done.returncode), (b"", 0))
    finally:
        shutil.rmtree(home, ignore_errors=True)
        shutil.rmtree(session, ignore_errors=True)


def test_claude_mcp_json_carries_only_claude_keys(checks):
    print(".mcp.json, which only Claude Code reads")
    servers = (load(CLAUDE_MCP) or {}).get("mcpServers") or {}
    checks.eq("(precondition) it serves model_platform", SERVER in servers, True)
    for name, spec in sorted(servers.items()):
        extra = sorted(set(spec or {}) - CLAUDE_SERVER_KEYS)
        checks.eq(f"{name}: no key outside {sorted(CLAUDE_SERVER_KEYS)}; a Codex tools table "
                  "makes Claude drop the server with no error", extra, [])


def test_codex_interface_limits(checks):
    print("the card Codex shows: .codex-plugin/plugin.json's interface")
    interface = codex_manifest().get("interface")
    checks.eq("(precondition) the manifest has an interface object",
              isinstance(interface, dict), True)
    interface = interface if isinstance(interface, dict) else {}
    checks.eq("its title is NovaDDE, which Codex also appends to every tool's description",
              interface.get("displayName"), "NovaDDE")
    checks.eq("it has no key Codex does not read, which would be dropped without a word",
              sorted(set(interface) - set(INTERFACE_STRINGS) - set(INTERFACE_LISTS)), [])
    # A known field of the wrong type fails the whole manifest, and the plugin silently disappears.
    checks.eq("every text field is a string",
              sorted(k for k in INTERFACE_STRINGS if k in interface
                     and not isinstance(interface[k], str)), [])
    checks.eq("every list field is a list of strings",
              sorted(k for k in INTERFACE_LISTS if k in interface
                     and not (isinstance(interface[k], list)
                              and all(isinstance(v, str) for v in interface[k]))), [])
    for key, limit in sorted(MAX_CHARS.items()):
        checks.eq(f"{key} is present and at most {limit} characters",
                  0 < len(interface.get(key) or "") <= limit, True)

    prompts = interface.get("defaultPrompt")
    prompts = prompts if isinstance(prompts, list) else []
    shown = [" ".join(p.split()) for p in prompts if isinstance(p, str)]
    checks.eq(f"exactly {MAX_PROMPTS} starter prompts, the most Codex shows",
              len(prompts), MAX_PROMPTS)
    checks.eq(f"each one non-empty and at most {MAX_PROMPT_CHARS} characters once whitespace is "
              "collapsed, or Codex drops it",
              [p for p in shown if not 0 < len(p) <= MAX_PROMPT_CHARS], [])
    checks.eq("no two the same", len(set(shown)), len(shown))
    checks.eq("none with an @mention", [p for p in shown if "@" in p], [])

    capabilities = interface.get("capabilities") or []
    checks.eq("capabilities are listed", bool(capabilities), True)
    checks.eq(f"at most {MAX_CAPABILITIES}, each at most {MAX_CAPABILITY_CHARS} characters",
              len(capabilities) <= MAX_CAPABILITIES
              and all(0 < len(str(c)) <= MAX_CAPABILITY_CHARS for c in capabilities), True)
    checks.eq("the category is one the directory offers",
              interface.get("category") in DIRECTORY_CATEGORIES, True)
    checks.eq("websiteURL is set", bool(interface.get("websiteURL")), True)
    checks.eq(f"every URL is https and at most {MAX_URL_CHARS} characters",
              sorted(k for k in INTERFACE_URLS if k in interface
                     and not (str(interface[k]).startswith("https://")
                              and len(interface[k]) <= MAX_URL_CHARS)), [])
    checks.eq("every asset path is ./-relative, stays inside the plugin, and exists",
              sorted(k for k in INTERFACE_ASSETS if k in interface
                     and not (str(interface[k]).startswith("./") and ".." not in interface[k]
                              and os.path.isfile(os.path.join(PLUGIN, interface[k])))), [])


def test_claude_marketplace_has_no_policy(checks):
    print(".claude-plugin/marketplace.json")
    codex_entry = entries(load(CODEX_MARKETPLACE)).get("novadde") or {}
    checks.eq("(precondition) the Codex marketplace carries the install policy",
              "policy" in codex_entry, True)
    claude_entries = entries(load(CLAUDE_MARKETPLACE))
    checks.eq("(precondition) the Claude marketplace lists novadde",
              "novadde" in claude_entries, True)
    checks.eq("no Claude entry has a policy, which fails claude plugin validate --strict",
              sorted(name for name, entry in claude_entries.items() if "policy" in entry), [])


def test_the_status_skill_says_what_to_call_when_its_script_cannot_run(checks):
    print("skills/status/SKILL.md, which Codex also loads")
    skill = read(STATUS_SKILL)
    checks.eq("(precondition) the skill still runs status.sh", "scripts/status.sh" in skill, True)
    # Sentences of the text with its line wrapping undone, so a sentence split across lines is one.
    sentences = re.split(r"(?<=[.!?])\s+", " ".join(skill.split()))
    fallback = [s for s in sentences if "cannot run" in s]
    checks.eq("one sentence says what to do if the script cannot run, as on Codex",
              len(fallback), 1)
    checks.eq("and it is to call get_usage and list_jobs and report them",
              [name for name in ("`get_usage`", "`list_jobs`", "report")
               if not any(name in s for s in fallback)], [])


def main():
    checks = Checks("test_codex_package")
    test_both_marketplaces_list_the_same_plugin_under_the_same_name(checks)
    test_codex_manifest_version_equals_claude_manifest(checks)
    test_codex_loads_no_hooks(checks)
    test_codex_mcp_file_exists_and_its_url_is_a_literal_https_url(checks)
    test_codex_approves_only_read_tools(checks)
    test_one_credential_reader(checks)
    test_claude_mcp_json_carries_only_claude_keys(checks)
    test_codex_interface_limits(checks)
    test_claude_marketplace_has_no_policy(checks)
    test_the_status_skill_says_what_to_call_when_its_script_cannot_run(checks)
    return checks.done()


if __name__ == "__main__":
    raise SystemExit(main())
