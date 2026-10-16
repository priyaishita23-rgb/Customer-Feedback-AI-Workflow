"""CLI: generate pulse + explainer, then ask for approval before any MCP action runs.

python run.py            # interactive approval prompt  <-- MCP approval gate (see ask_approval)
python run.py --dry-run  # generate only, run no actions
"""
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

from mcp_client import execute_approved, proposed_actions
from pipeline import run


def ask_approval(actions: list[dict]) -> bool:
    print("\n=== PROPOSED MCP ACTIONS (nothing has run yet) ===")
    for i, a in enumerate(actions, 1):
        if a["tool"] == "append_to_notes":
            print(f"{i}. append_to_notes -> out/Product_Pulse_Notes.md  (entry dated {a['args']['entry']['date']})")
        else:
            print(f"{i}. create_email_draft -> subject: {a['args']['subject']}  (draft only, NOT sent)")
    return input("\nApprove these actions? [y/N]: ").strip().lower() in ("y", "yes")


if __name__ == "__main__":
    r = run()
    print(r["pulse"], "\n\n", r["explainer"]["markdown"])
    if "--dry-run" in sys.argv:
        sys.exit(0)
    actions = proposed_actions(r["payload"])
    if ask_approval(actions):
        for line in execute_approved(actions):
            print("✔", line)
    else:
        print("Rejected. No actions were taken.")
