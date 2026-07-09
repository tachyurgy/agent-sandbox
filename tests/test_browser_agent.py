"""The Browser-Use Agent solving real tasks on the real app's UI.

This is the end-to-end proof: a browser agent perceives the rendered page,
acts (login, navigate, type, click), and the verifier grades the app's real
state afterward — no API shortcuts.
"""

from __future__ import annotations

from sandbox.browser_agent import ScriptedPolicy, run_task
from sandbox.config import settings
from sandbox.gitea_client import GiteaClient
from sandbox.tasks import default_tasks


def _policy() -> ScriptedPolicy:
    return ScriptedPolicy(settings.admin_user, settings.admin_password)


def test_bua_files_a_bug(app, fresh):
    task = next(t for t in default_tasks() if t.id == "file-outage-bug")
    traj = run_task(task, _policy(), headless=True)
    assert traj.done
    verdict = task.verify(GiteaClient())
    assert verdict.success, verdict.detail
    assert verdict.reward == 1.0


def test_bua_closes_an_issue(app, fresh):
    task = next(t for t in default_tasks() if t.id == "close-fixed-typo")
    traj = run_task(task, _policy(), headless=True)
    assert traj.done
    verdict = task.verify(GiteaClient())
    assert verdict.success, verdict.detail
