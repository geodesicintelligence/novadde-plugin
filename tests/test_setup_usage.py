"""setup-credential.sh --help prints its usage, and stops where the usage stops.

usage() printed lines 2-9 of the script. The usage is lines 2-6; lines 8-9 are the first two of
the "Why two stores" paragraph, so the help ended mid-sentence on "Monitor processes get no
plugin options at". An unrecognised argument prints the same text, so it was the first thing a
mistyped flag showed.
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _harness import SCRIPTS, Checks, Sandbox  # noqa: E402

HELP = (
    "The plugin's credential: the one key in ~/.config/geodesic/model-platform.env.\n"
    "\n"
    "  --check            report what is configured and whether the platform accepts it\n"
    "  --key mp_...       verify a key, then store it in that file\n"
)


def main():
    checks = Checks("test_setup_usage")
    with Sandbox() as box:
        result = box.run("setup-credential.sh", "--help")
        checks.eq("--help prints the usage and nothing after it", result.stdout, HELP)
        checks.eq("--help exits 0", result.returncode, 0)

        # The expected text above is a copy of the header, so it cannot notice a flag added to
        # the script that the line range leaves out. The case statement can.
        with open(os.path.join(SCRIPTS, "setup-credential.sh")) as handle:
            flags = re.findall(r"^\s+(--[a-z-]+)\)", handle.read(), re.M)
        checks.eq("every flag the script accepts is in its help",
                  [flag for flag in flags if flag not in result.stdout], [])

        result = box.run("setup-credential.sh", "--frobnicate")
        checks.eq("an unknown flag prints the same usage", result.stdout, HELP)
        checks.eq("and exits 2", result.returncode, 2)

        # --login signed in with a password at /api/auth/login, which the platform no longer
        # serves (503: it signs people in with Google). It is gone, not left to fail at the
        # prompt after asking for a password: it is an unknown flag like any other.
        result = box.run("setup-credential.sh", "--login")
        checks.eq("--login is no longer a flag: the usage", result.stdout, HELP)
        checks.eq("and exits 2", result.returncode, 2)
    return checks.done()


if __name__ == "__main__":
    raise SystemExit(main())
