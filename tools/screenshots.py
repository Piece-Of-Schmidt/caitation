"""Takes the README screenshots (docs/images/) of a running Caitation, in a headless
Chromium-based browser (Edge or Chrome) driven through the DevTools protocol.

    python -m backend                       # in one window
    python tools/screenshots.py search ask  # in another; scenes: search ask dashboard setup

The screenshots show the library of whoever runs this: check them before publishing.
"""

import argparse
import base64
import itertools
import json
import shutil
import subprocess
import time
import urllib.parse
import urllib.request
from pathlib import Path

from websockets.sync.client import connect

ROOT = Path(__file__).resolve().parent.parent
APP = "http://127.0.0.1:8000/"
DEBUG_PORT = 9333
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
    "google-chrome", "chromium", "microsoft-edge",
]

SEARCH = "Wie verbreiten sich ökonomische Narrative in den Medien?"
QUESTION = "Wie lassen sich ökonomische Narrative in Texten automatisch erkennen?"

# A first start without access to Zotero, faked in the page: the status the server reports
FAKE_FIRST_START = """
  const realFetch = window.fetch;
  window.fetch = async (url, opts) => {
    const res = await realFetch(url, opts);
    if (!String(url).includes('/api/reindex/status')) return res;
    const s = await res.json();
    Object.assign(s, {library_items: 0, zotero: {state: 'disabled', message: ''},
                      warning: 'Caitation hat noch keinen Lesezugriff auf Zotero.'});
    return new Response(JSON.stringify(s), {headers: {'Content-Type': 'application/json'}});
  };"""

# name -> (color scheme, url, page is ready when ..., then run ..., fake script)
SCENES = {
    "search": ("light", f"?mode=search&q={urllib.parse.quote(SEARCH)}",
               "document.querySelectorAll('.item-row').length > 3 && !document.querySelector('.refine-hint')",
               "document.querySelector('.item-row').click()", None),
    "ask": ("dark", f"?mode=ask&q={urllib.parse.quote(QUESTION)}",
            "!document.querySelector('#answerBox .is-streaming') && !!document.querySelector('#answerBox .quote-summary')",
            None, None),
    "dashboard": ("light", "#dashboard", "!!document.querySelector('#view-dashboard svg circle')", None, None),
    "setup": ("light", "", "!!document.querySelector('.setup-card ol')", None, FAKE_FIRST_START),
}


def find_browser() -> str:
    for candidate in BROWSERS:
        path = shutil.which(candidate) or (candidate if Path(candidate).exists() else None)
        if path:
            return path
    raise SystemExit("Kein Edge/Chrome gefunden.")


class Page:
    def __init__(self, ws_url: str):
        self.ws = connect(ws_url, max_size=None)
        self.ids = itertools.count(1)

    def call(self, method: str, **params):
        msg_id = next(self.ids)
        self.ws.send(json.dumps({"id": msg_id, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") == msg_id:
                if "error" in msg:
                    raise RuntimeError(msg["error"])
                return msg.get("result", {})

    def js(self, expression: str):
        result = self.call("Runtime.evaluate", expression=expression, awaitPromise=True, returnByValue=True)
        return result["result"].get("value")

    def wait_for(self, expression: str, timeout: float = 180):
        end = time.time() + timeout
        while time.time() < end:
            if self.js(f"!!({expression})"):  # !!: DOM nodes come back as {} (falsy in Python)
                return
            time.sleep(0.5)
        raise TimeoutError(expression)


def shoot(page: Page, name: str, out: Path) -> None:
    scheme, path, ready, then, fake = SCENES[name]
    page.call("Page.bringToFront")
    page.call("Emulation.setDeviceMetricsOverride", width=1440, height=880, deviceScaleFactor=2, mobile=False)
    page.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
    script = page.call("Page.addScriptToEvaluateOnNewDocument", source=fake)["identifier"] if fake else None
    page.call("Page.navigate", url=APP + path)
    time.sleep(1)
    page.wait_for("['ready', 'indexing', 'warning'].includes(document.querySelector('#indexStatus')?.dataset.state)")
    page.wait_for(ready)
    if then:
        page.js(then)
        time.sleep(1)
        page.wait_for("!document.querySelector('#itemPane .ip-muted')")  # details loaded
    page.js("document.activeElement && document.activeElement.blur()")
    time.sleep(0.5)
    data = page.call("Page.captureScreenshot", format="png")["data"]
    (out / f"{name}.png").write_bytes(base64.b64decode(data))
    if script:
        page.call("Page.removeScriptToEvaluateOnNewDocument", identifier=script)
    print("gespeichert:", out / f"{name}.png")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("scenes", nargs="+", choices=sorted(SCENES))
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "images")
    args = parser.parse_args()

    profile = ROOT / "data" / ".screenshot-browser"  # data/ is not under version control
    browser = subprocess.Popen([
        find_browser(), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--lang=de-DE",
        # a headless page counts as hidden; without these, timers and repaints get throttled
        "--disable-background-timer-throttling", "--disable-renderer-backgrounding",
        "--disable-backgrounding-occluded-windows",
        f"--remote-debugging-port={DEBUG_PORT}", f"--user-data-dir={profile}", "about:blank",
    ])
    try:
        for _ in range(50):
            try:
                targets = json.load(urllib.request.urlopen(f"http://127.0.0.1:{DEBUG_PORT}/json"))
                ws_url = next(t for t in targets if t["type"] == "page")["webSocketDebuggerUrl"]
                break
            except Exception:
                time.sleep(0.2)
        page = Page(ws_url)
        page.call("Page.enable")
        for name in args.scenes:
            shoot(page, name, args.out)
    finally:
        browser.terminate()


if __name__ == "__main__":
    main()
