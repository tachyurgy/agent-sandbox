#!/usr/bin/env python3
"""Run the Browser-Use Agent on a task and capture screenshots into docs/.

Shows the BUA operating Gitea's real UI end-to-end, then grades it with the
verifier. Requires the app up (scripts/start_app.sh) and the baseline seeded
(python -m sandbox.seed).

    python scripts/demo_bua.py [task_id]
"""
import sys
from sandbox.app_process import GiteaApp
from sandbox import state
from sandbox.browser_agent import ScriptedPolicy, run_task
from sandbox.config import settings
from sandbox.gitea_client import GiteaClient
from sandbox.tasks import default_tasks

task_id = sys.argv[1] if len(sys.argv) > 1 else "file-outage-bug"
app = GiteaApp()
if not app.is_up():
    app.start()
state.populate(GiteaClient())  # fresh baseline (fast API reseed)

task = next(t for t in default_tasks() if t.id == task_id)
print(f"TASK: {task.goal}\n")
policy = ScriptedPolicy(settings.admin_user, settings.admin_password)
traj = run_task(task, policy, headless=True, shot_dir="docs")

print("TRAJECTORY:")
for i, s in enumerate(traj.steps):
    a = s.action
    print(f"  {i:02d} {a.kind:9} ref={a.ref}  {a.reason}")
verdict = task.verify(GiteaClient())
print(f"\nVERDICT: {'PASS' if verdict.success else 'FAIL'} (reward={verdict.reward}) — {verdict.detail}")
print("screenshots:", ", ".join(traj.screenshots[-3:]))
