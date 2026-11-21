"""Run the real panel QML (Panel.qml and its components) in quickshell under the sandbox's headless sway.

One Session is one quickshell process with its own stub-helper directory.
Observation goes through `quickshell ipc call harness state` (see
harness.qml) and the stub's call log; input goes through wtype. Every wait
polls for an observable condition and is bounded by a timeout.
"""
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time

from vptr import VPtr

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
TIMEOUT = 15
# Bounds a whole test: a spinning quickshell can outlast every 15 s wait.
WATCHDOG = int(os.environ.get("OMAPASS_QML_WATCHDOG", "90"))

def in_qml_sandbox():
    return os.environ.get("WAYLAND_DISPLAY") and shutil.which("quickshell") is not None


class Session:
    def __init__(self, config=None):
        self.dir = tempfile.mkdtemp(prefix="qml-session-")
        self.stub_dir = os.path.join(self.dir, "stub")
        os.mkdir(self.stub_dir)
        self.proc = None
        self.log = None
        self._pointer = None
        self._watchdog = None
        self.timed_out = False
        self.set_config(config or {})
        self._stage()

    def _shim_imports(self):
        """Hide QtQuick types newer than 6.11 from the staged QML.

        Qt 6.12 added a QtQuick `Color` type. Omarchy's patched quickshell
        still resolves `Color` to qs.Commons.Color, the stock quickshell in
        this sandbox picks QtQuick's. Importing QtQuick at 6.11 removes the
        clash without touching the files' logic.
        """
        for base, _, names in os.walk(self.dir):
            for name in names:
                if name.endswith(".qml"):
                    path = os.path.join(base, name)
                    with open(path) as f:
                        text = f.read()
                    fixed = re.sub(r"^import QtQuick$", "import QtQuick 6.11", text, flags=re.M)
                    if fixed != text:
                        with open(path, "w") as f:
                            f.write(fixed)

    def _stage(self):
        shutil.copy(os.path.join(HERE, "harness.qml"), os.path.join(self.dir, "shell.qml"))
        for name in ("Commons", "Ui"):
            shutil.copytree(os.path.join(HERE, "shell", name), os.path.join(self.dir, name))
        plugin = os.path.join(self.dir, "plugin")
        os.makedirs(os.path.join(plugin, "bin"))
        # Every root QML file; OMAPASS_QML_PANEL replaces only Panel.qml.
        for name in sorted(os.listdir(ROOT)):
            if name.endswith(".qml") or name == "Model.js":
                shutil.copy(os.path.join(ROOT, name), os.path.join(plugin, name))
        panel = os.environ.get("OMAPASS_QML_PANEL")
        if panel:
            shutil.copy(panel, os.path.join(plugin, "Panel.qml"))
        for stub, name in (("stub-helper", "omapass-keyring"), ("stub-notify", "notify-stub")):
            path = os.path.join(plugin, "bin", name)
            shutil.copy(os.path.join(HERE, stub), path)
            os.chmod(path, 0o755)
        self._shim_imports()

    def set_config(self, config):
        with open(os.path.join(self.stub_dir, "config.json"), "w") as f:
            json.dump(config, f)

    def start(self):
        env = dict(os.environ, OMAPASS_STUB_DIR=self.stub_dir)
        self.log = open(os.path.join(self.dir, "quickshell.log"), "w")
        self.proc = subprocess.Popen(["quickshell", "-p", self.dir], env=env,
                                     stdout=self.log, stderr=subprocess.STDOUT)
        self._watchdog = threading.Timer(WATCHDOG, self._bark)
        self._watchdog.daemon = True
        self._watchdog.start()
        self.wait(lambda: self._try_state() is not None, "quickshell did not start")
        # Sway's cursor starts at (100,100), where the panel would see it as
        # its first hover. Park it in a corner, away from the panel, before
        # anything opens, so a test's first move is the first position.
        self.pointer().move(0, VPtr.H - 1)

    def _bark(self):
        """Watchdog: kill quickshell; every later call fails the test."""
        self.timed_out = True
        self.proc.kill()

    def stop(self):
        if self._watchdog:
            self._watchdog.cancel()
        if self._pointer:
            self._pointer.close()
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait()
        if self.log:
            self.log.close()
        shutil.rmtree(self.dir, ignore_errors=True)
        if self.timed_out:
            raise AssertionError("watchdog: the test ran longer than %d s; quickshell was killed"
                                 % WATCHDOG)

    def quickshell_log(self):
        if not self.log.closed:
            self.log.flush()
        with open(os.path.join(self.dir, "quickshell.log")) as f:
            return f.read()

    # Observation ---------------------------------------------------------

    def _ipc(self, *args):
        return subprocess.run(["quickshell", "ipc", "-p", self.dir, "call", "harness", *args],
                              capture_output=True, text=True, timeout=TIMEOUT)

    def _try_state(self):
        if self.proc.poll() is not None:
            raise RuntimeError(("watchdog killed quickshell after %d s:\n" % WATCHDOG
                                if self.timed_out else "quickshell exited:\n") + self.quickshell_log())
        r = self._ipc("state")
        if r.returncode != 0:
            return None
        return json.loads(r.stdout)

    def state(self):
        s = self._try_state()
        if s is None:
            raise RuntimeError("no state from harness:\n" + self.quickshell_log())
        return s

    def calls(self):
        path = os.path.join(self.stub_dir, "calls.jsonl")
        if not os.path.exists(path):
            return []
        with open(path) as f:
            return [json.loads(line) for line in f if line.strip()]

    def helper_calls(self, *cmds):
        return [c for c in self.calls() if "event" not in c and c["cmd"] in cmds]

    def notifications(self):
        return self.helper_calls("notify")

    def rows(self):
        return json.loads(self._ipc("rows").stdout)

    def buttons(self):
        return json.loads(self._ipc("buttons").stdout)

    def pointer(self):
        """A virtual pointer (created on first use) that never moves by itself."""
        if self._pointer is None:
            self._pointer = VPtr()
        return self._pointer

    def field(self, placeholder):
        for f in self.state()["fields"]:
            if f["placeholder"] == placeholder:
                return f
        return None

    def wait(self, cond, what, timeout=TIMEOUT):
        end = time.monotonic() + timeout
        while True:
            if self.timed_out:
                self._try_state()  # raises: the watchdog killed quickshell
            value = cond()
            if value:
                return value
            if time.monotonic() > end:
                raise AssertionError("timed out waiting for: " + what + "\n--- state: "
                                     + json.dumps(self.state() if self.proc.poll() is None else None)
                                     + "\n--- helper calls: " + json.dumps(self.calls())
                                     + "\n--- quickshell log:\n" + self.quickshell_log()[-2000:])
            time.sleep(0.02)

    def wait_state(self, what, pred):
        return self.wait(lambda: (lambda s: s if pred(s) else None)(self.state()), what)

    def stays(self, pred, what, window):
        """Assert that pred(state) holds on every poll for `window` seconds.

        For "nothing happens" checks that no event can mark the end of: the
        window is a bound on how long a wrong reaction may take, not a wait
        for a result. It fails at the first poll where the state differs.
        """
        end = time.monotonic() + window
        while True:
            st = self.state()
            if not pred(st):
                raise AssertionError("did not stay: " + what + "\n--- state: " + json.dumps(st))
            if time.monotonic() > end:
                return st
            time.sleep(0.02)

    def settle(self):
        """Wait until no helper process is running, three polls in a row.

        Used before asserting that something did NOT happen: a stray copy or
        type would be running (or already logged) by then.
        """
        quiet = 0

        def idle():
            nonlocal quiet
            quiet = 0 if self.state()["busy"] else quiet + 1
            return quiet >= 3
        self.wait(idle, "helper processes to finish")

    # Actions -------------------------------------------------------------

    def open_panel(self):
        self._ipc("open")
        # The search field is active once the compositor gave the surface the
        # keyboard, and the list has loaded. (Qt drops "active" soon after, while
        # keys keep arriving, so later waits use the fields' `focus` flag.)
        self.wait(lambda: (lambda s: s["opened"] and s["records"] > 0
                           and any(f["placeholder"] == "Search" and f["active"] for f in s["fields"]))(self.state()),
                  "panel open with focused search")
        self.prime_keys()

    def prime_keys(self):
        """Wait until the surface really takes keys.

        Right after a (re)open the compositor may still be settling keyboard
        focus and drop a key. Type a sentinel into the search field until it
        shows up, then erase it. Keys sent after this arrive.
        """
        def text_is(pred):
            return pred(self.state()["searchText"])

        def until(key_args, pred):
            end = time.monotonic() + TIMEOUT
            while not text_is(pred):
                if time.monotonic() > end:
                    raise AssertionError("keys never reached the panel: " + json.dumps(self.state()))
                self.press(*key_args)
                stop = time.monotonic() + 0.5
                while time.monotonic() < stop and not text_is(pred):
                    time.sleep(0.02)
        until(("z",), lambda t: t != "")
        until(("-k", "BackSpace"), lambda t: t == "")

    def summon_again(self):
        """open() on a panel that is already open (`shell summon`, IPC), then
        watch briefly for anything it would do: a focus move shows up within
        a few frames. Returns the state."""
        n = len(self.helper_calls("focus-snapshot"))
        self._ipc("open")
        end = time.monotonic() + 1.0
        while time.monotonic() < end:
            st = self.state()
            if len(self.helper_calls("focus-snapshot")) > n or any(
                    f["placeholder"] == "Search" and f["focus"] for f in st["fields"]):
                break
            time.sleep(0.02)
        return self.state()

    def close_panel(self):
        self._ipc("close")
        self.wait_state("panel closed", lambda s: not s["opened"])

    def press(self, *wtype_args):
        """One wtype call. A separate call per key drops the first key, so
        group a sequence into one call."""
        subprocess.run(["wtype", "-s", "100", *wtype_args], check=True, timeout=TIMEOUT)

    def chord(self, mod, key):
        self.press("-M", mod, "-k", key, "-m", mod)
