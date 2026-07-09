"""A Browser-Use Agent (BUA) that operates the real app through its web UI.

This is the second way the agent drives the sandbox — not via the app's API, but
by perceiving and acting on the *rendered page*, exactly like a human. It's the
same family as the `browser-use` library, OpenAI Operator, and Anthropic
computer-use. The important, transferable part is the machinery:

  * a compact ACTION SPACE over a real browser (navigate / observe / click / type),
  * an OBSERVATION the policy reasons over (the visible interactive elements, each
    with a stable ref — an accessibility-tree-style view, not raw HTML),
  * a perceive → decide → act LOOP that runs an episode to completion,
  * a pluggable POLICY: a deterministic ScriptedPolicy (runs with no API key, for
    tests + demos) or an LLMPolicy (a real model chooses the next action).

The verifier (tasks.py) grades the app's real state afterward — it doesn't care
whether the agent used the browser or the MCP tools.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from playwright.sync_api import Browser, Page, sync_playwright

from .config import settings

CACHED_CHROMIUM = os.environ.get("CHROME_BIN") or (
    "/Users/magnusfremont/Library/Caches/ms-playwright/chromium-1223/"
    "chrome-mac-arm64/Google Chrome for Testing.app/Contents/MacOS/Google Chrome for Testing"
)

INTERACTIVE = "a, button, input, textarea, select, [role=button]"


@dataclass
class Element:
    ref: int
    tag: str
    type: str
    name: str
    label: str


@dataclass
class Observation:
    url: str
    title: str
    elements: list[Element]

    def find(self, *, name: Optional[str] = None, label_contains: Optional[str] = None,
             tag: Optional[str] = None) -> Optional[Element]:
        for e in self.elements:
            if name is not None and e.name != name:
                continue
            if tag is not None and e.tag != tag:
                continue
            if label_contains is not None and label_contains.lower() not in e.label.lower():
                continue
            return e
        return None

    def render(self) -> str:
        """Text view an LLM policy reads."""
        lines = [f"URL: {self.url}", f"TITLE: {self.title}", "ELEMENTS:"]
        for e in self.elements:
            lines.append(f"  [{e.ref}] <{e.tag}{'/'+e.type if e.type else ''}> "
                         f"name={e.name!r} label={e.label!r}")
        return "\n".join(lines)


@dataclass
class Action:
    kind: str                       # navigate | click | type | done | fail
    ref: Optional[int] = None
    url: Optional[str] = None
    text: Optional[str] = None
    reason: str = ""


@dataclass
class Step:
    action: Action
    observation_url: str


@dataclass
class Trajectory:
    task_id: str
    steps: list[Step] = field(default_factory=list)
    done: bool = False
    screenshots: list[str] = field(default_factory=list)


# --------------------------------------------------------------------------
# The browser tools (the action space)
# --------------------------------------------------------------------------

class BrowserSession:
    def __init__(self, headless: bool = True) -> None:
        self.headless = headless
        self._pw = None
        self._browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    def start(self) -> None:
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(
            executable_path=CACHED_CHROMIUM, headless=self.headless,
            args=["--no-sandbox"],
        )
        self.page = self._browser.new_page(viewport={"width": 1280, "height": 900})

    def close(self) -> None:
        if self._browser:
            self._browser.close()
        if self._pw:
            self._pw.stop()

    # -- actions ------------------------------------------------------------

    # JS that assigns a stable data-bua-ref to every visible interactive element,
    # in DOM order, and returns their descriptors.
    _TAG_JS = """
        (nodes) => {
            const out = []; let i = 0;
            for (const el of nodes) {
                const r = el.getBoundingClientRect();
                const st = getComputedStyle(el);
                if (r.width <= 0 || r.height <= 0 || st.visibility === 'hidden' || st.display === 'none') continue;
                el.setAttribute('data-bua-ref', String(i));
                const label = (el.innerText || el.value || el.placeholder ||
                    el.getAttribute('aria-label') || el.getAttribute('name') ||
                    el.getAttribute('title') || '').trim().replace(/\\s+/g,' ').slice(0, 80);
                out.push({ref: i, tag: el.tagName.toLowerCase(),
                    type: el.getAttribute('type') || '', name: el.getAttribute('name') || '',
                    label});
                i++;
            }
            return out;
        }
    """

    def _settle(self) -> None:
        # Let client-side JS finish (re)rendering before we read or act, so refs
        # are assigned to nodes that won't detach mid-action.
        try:
            self.page.wait_for_load_state("networkidle", timeout=5000)
        except Exception:
            pass
        self.page.wait_for_timeout(250)

    def _tag(self) -> list[dict]:
        return self.page.eval_on_selector_all(INTERACTIVE, self._TAG_JS)

    def navigate(self, url: str) -> None:
        if url.startswith("/"):
            url = settings.base_url + url
        self.page.goto(url, wait_until="load")

    def observe(self) -> Observation:
        self._settle()
        els = [Element(**e) for e in self._tag()]
        return Observation(url=self.page.url, title=self.page.title(), elements=els)

    def click(self, ref: int) -> None:
        # Re-tag right before acting so the ref points at a live (not detached)
        # node, then let Playwright auto-wait for it to be clickable.
        self._tag()
        self.page.locator(f'[data-bua-ref="{ref}"]').click(timeout=10000)
        self.page.wait_for_load_state("load")

    def type(self, ref: int, text: str) -> None:
        self._tag()
        self.page.locator(f'[data-bua-ref="{ref}"]').fill(text, timeout=10000)

    def screenshot(self, path: str) -> str:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.page.screenshot(path=path, full_page=False)
        return path


# --------------------------------------------------------------------------
# Policies (the "brain")
# --------------------------------------------------------------------------

class Policy:
    def act(self, task, obs: Observation, history: list[Step]) -> Action:  # noqa: ANN001
        raise NotImplementedError


class ScriptedPolicy(Policy):
    """Deterministic rule-based agent — no API key. Solves the default tasks by
    reasoning over the SAME observations an LLM policy would see.

    Handles login when it lands on the sign-in page, then dispatches on task id.
    """

    def __init__(self, username: str, password: str) -> None:
        self.username = username
        self.password = password
        self._typed_title = False

    def act(self, task, obs: Observation, history: list[Step]) -> Action:
        # 1) Log in if we're on the sign-in page.
        if "/user/login" in obs.url:
            user = obs.find(name="user_name")
            pw = obs.find(name="password")
            typed = {s.action.ref for s in history if s.action.kind == "type"}
            if user and user.ref not in typed:
                return Action("type", ref=user.ref, text=self.username, reason="enter username")
            if pw and pw.ref not in typed:
                return Action("type", ref=pw.ref, text=self.password, reason="enter password")
            # Target the form's submit BUTTON, not the header "Sign In" nav link
            # (an <a> that merely reloads the login page).
            btn = obs.find(tag="button", label_contains="Sign In") or obs.find(tag="button")
            if btn:
                return Action("click", ref=btn.ref, reason="submit login")

        if task.id == "file-outage-bug":
            return self._file_bug(task, obs, history)
        if task.id == "close-fixed-typo":
            return self._close_issue(task, obs, history)
        return Action("fail", reason=f"no script for task {task.id}")

    def _file_bug(self, task, obs: Observation, history: list[Step]) -> Action:
        import re

        # Landed on the created issue page (…/issues/<number>) → success.
        if self._typed_title and re.search(r"/issues/\d+$", obs.url):
            return Action("done", reason="issue created")
        target = f"/{task.owner}/{task.repo}/issues/new"
        if not obs.url.rstrip("/").endswith("issues/new"):
            return Action("navigate", url=target, reason="go to new-issue form")
        title = obs.find(name="title")
        if title and not self._typed_title:
            self._typed_title = True
            return Action("type", ref=title.ref,
                          text="Storefront returns 502 for all users",
                          reason="fill the required issue title")
        submit = obs.find(label_contains="Create Issue") or obs.find(label_contains="New Issue")
        if submit:
            return Action("click", ref=submit.ref, reason="submit the issue")
        return Action("fail", reason="could not find the submit button")

    def _close_issue(self, task, obs: Observation, history: list[Step]) -> Action:
        issue_url = f"/{task.owner}/{task.repo}/issues/3"
        if f"/{task.repo}/issues/3" not in obs.url:
            return Action("navigate", url=issue_url, reason="open the typo issue")
        # Click "Close" exactly once — a second click would re-open it.
        already_clicked = any(s.action.kind == "click" and "close" in s.action.reason
                              for s in history)
        if already_clicked:
            return Action("done", reason="issue closed")
        close = obs.find(tag="button", label_contains="Close")
        if close:
            return Action("click", ref=close.ref, reason="close the issue")
        return Action("done", reason="no close button (already closed?)")


class LLMPolicy(Policy):
    """A real model picks the next action from the observation.

    Uses the Gemini free-tier REST endpoint (no SDK). This is the "real brain"
    the ScriptedPolicy stands in for; enable it by setting GEMINI_API_KEY. The
    loop, action space and observation are identical — only the decision changes.
    """

    MODEL = "gemini-2.5-flash"

    def __init__(self, api_key: Optional[str] = None) -> None:
        self.api_key = api_key or os.environ.get("GEMINI_API_KEY") or os.environ.get("GEMINI_KEY")
        if not self.api_key:
            raise RuntimeError("LLMPolicy needs GEMINI_API_KEY (or GEMINI_KEY).")

    def act(self, task, obs: Observation, history: list[Step]) -> Action:
        import json
        import urllib.request

        prompt = (
            "You are a browser-use agent operating a Gitea web app to accomplish a task.\n"
            f"TASK: {task.goal}\n\n"
            f"CURRENT PAGE:\n{obs.render()}\n\n"
            "Recent actions: "
            + ", ".join(f"{s.action.kind}({s.action.ref if s.action.ref is not None else s.action.url})"
                        for s in history[-6:])
            + "\n\nReply with ONE next action as JSON: "
            '{"kind":"navigate|click|type|done|fail","ref":<int or null>,'
            '"url":<string or null>,"text":<string or null>,"reason":<string>}. '
            "Use element refs from the list. To fill a field use kind=type with its ref and text."
        )
        body = json.dumps({
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0, "responseMimeType": "application/json",
                                 "thinkingConfig": {"thinkingBudget": 0}},
        }).encode()
        url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
               f"{self.MODEL}:generateContent?key={self.api_key}")
        req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        a = json.loads(text)
        return Action(kind=a.get("kind", "fail"), ref=a.get("ref"), url=a.get("url"),
                      text=a.get("text"), reason=a.get("reason", ""))


# --------------------------------------------------------------------------
# The episode loop
# --------------------------------------------------------------------------

def run_task(task, policy: Policy, headless: bool = True, max_steps: int = 12,
             shot_dir: Optional[str] = None) -> Trajectory:
    """Perceive → decide → act until the policy signals done or the budget runs out."""
    traj = Trajectory(task_id=task.id)
    sess = BrowserSession(headless=headless)
    sess.start()
    try:
        sess.navigate(settings.base_url + "/user/login")
        for i in range(max_steps):
            obs = sess.observe()
            action = policy.act(task, obs, traj.steps)
            traj.steps.append(Step(action=action, observation_url=obs.url))
            if action.kind == "navigate":
                sess.navigate(action.url)
            elif action.kind == "click":
                sess.click(action.ref)
            elif action.kind == "type":
                sess.type(action.ref, action.text or "")
            elif action.kind == "done":
                traj.done = True
                break
            elif action.kind == "fail":
                break
            if shot_dir:
                traj.screenshots.append(sess.screenshot(f"{shot_dir}/{task.id}-{i:02d}.png"))
        else:
            traj.done = True  # ran out the budget after acting
    finally:
        if shot_dir:
            traj.screenshots.append(sess.screenshot(f"{shot_dir}/{task.id}-final.png"))
        sess.close()
    return traj
