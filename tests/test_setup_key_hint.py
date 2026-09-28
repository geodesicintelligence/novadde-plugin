"""setup-credential.sh stores the key in the one file, and hands nobody a command to put it elsewhere.

--key used to end with a hint -- `claude plugin install novadde@novadde-plugin --config
api_key=<key>` -- because the MCP server read the key from a keychain plugin option and only the
watcher read the file. (Before #5 that hint even printed a literal "%s" where the key should be.)
The option is gone: the MCP connection, the hooks and the watcher all read
~/.config/geodesic/model-platform.env, which --key writes. A hint now would name a setting that
does not exist, and print the key into whatever ran the script. So it ends by saying to start a
new session, and does not print the key.

(--login, which minted a key from an email and a password, did the same and is gone: the platform
no longer signs anyone in with a password. test_setup_usage.py holds that it is an unknown flag.)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import Checks, Sandbox  # noqa: E402

ME = {"status": 200, "json": {"id": "u1", "email": "someone@example.test"}}


def hint(output):
    """A line that tells the user to hand the key to a plugin option, or None."""
    return next((line for line in output.splitlines() if "--config api_key" in line
                 or "/plugin configure" in line), None)


def stored(box):
    """The key lines of the credential file, or None when there is no file."""
    try:
        with open(box.env_file) as handle:
            return [line for line in handle.read().splitlines()
                    if line.startswith("MODEL_PLATFORM_API_KEY=")]
    except FileNotFoundError:
        return None


def main():
    checks = Checks("test_setup_key_hint")

    print("--key")
    key = "mp_given_0123456789abcdef"
    with Sandbox({"GET /api/auth/me": ME}, key=None) as box:
        result = box.run("setup-credential.sh", "--key", key)
        checks.eq("--key exits 0", result.returncode, 0)
        checks.eq("the key is stored in the file", stored(box), [f"MODEL_PLATFORM_API_KEY={key}"])
        checks.eq("no hint sends it to a plugin option", hint(result.stdout), None)
        checks.eq("the key is not printed", key in result.stdout + result.stderr, False)
        checks.eq("it says to start a new session", "Start a new session" in result.stdout, True)

    return checks.done()


if __name__ == "__main__":
    raise SystemExit(main())
