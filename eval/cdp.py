"""Cliente CDP mínimo (Chrome DevTools Protocol) sobre `websockets`.

Sin Playwright/Puppeteer: lanza Chrome headless con depuración remota y permite
evaluar JS en la página. Es la base del harness frontend (eval/frontend.py) para
medir los KPIs que solo se ven en el navegador (paridad gráfica/CSV/PNG, informe).
"""

import asyncio
import json
import subprocess
import time
import urllib.request

import websockets

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"


def _http_json(url, timeout=2):
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode())


class Chrome:
    """Proceso de Chrome headless con el puerto de depuración abierto."""

    def __init__(self, port=9222, user_data_dir="/tmp/brujula-cdp", window="1400,1900"):
        self.port = port
        self.user_data_dir = user_data_dir
        self.window = window
        self.proc = None

    def start(self):
        self.proc = subprocess.Popen(
            [CHROME, "--headless=new", f"--remote-debugging-port={self.port}",
             f"--user-data-dir={self.user_data_dir}", "--no-first-run",
             "--no-default-browser-check", "--disable-gpu", "--disable-extensions",
             "--disable-dev-shm-usage", "--hide-scrollbars", "--mute-audio",
             f"--window-size={self.window}", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(150):
            try:
                _http_json(f"http://localhost:{self.port}/json/version")
                return self
            except Exception:
                time.sleep(0.1)
        raise RuntimeError("Chrome no abrió el puerto de depuración a tiempo")

    def page_ws_url(self):
        for _ in range(50):
            targets = _http_json(f"http://localhost:{self.port}/json")
            pages = [t for t in targets if t.get("type") == "page"
                     and t.get("webSocketDebuggerUrl")]
            if pages:
                return pages[0]["webSocketDebuggerUrl"]
            time.sleep(0.1)
        raise RuntimeError("Sin target 'page' en Chrome")

    def stop(self):
        if self.proc:
            self.proc.terminate()
            try:
                self.proc.wait(timeout=5)
            except Exception:
                self.proc.kill()


class Session:
    """Sesión CDP sobre una página: request/response + espera de eventos."""

    def __init__(self, ws):
        self.ws = ws
        self._id = 0
        self._pending = {}
        self._waiters = []
        self._task = None

    def start(self):
        self._task = asyncio.create_task(self._recv_loop())
        return self

    async def _recv_loop(self):
        try:
            async for raw in self.ws:
                msg = json.loads(raw)
                mid = msg.get("id")
                if mid in self._pending:
                    fut = self._pending.pop(mid)
                    if not fut.done():
                        fut.set_result(msg)
                elif "method" in msg:
                    for fut, pred in list(self._waiters):
                        if not fut.done() and pred(msg):
                            fut.set_result(msg)
                            self._waiters.remove((fut, pred))
        except (websockets.ConnectionClosed, asyncio.CancelledError):
            pass

    async def call(self, method, timeout=30, **params):
        self._id += 1
        mid = self._id
        fut = asyncio.get_event_loop().create_future()
        self._pending[mid] = fut
        await self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        msg = await asyncio.wait_for(fut, timeout=timeout)
        if "error" in msg:
            raise RuntimeError(f"{method}: {msg['error']}")
        return msg.get("result", {})

    async def wait_event(self, method, timeout=20):
        fut = asyncio.get_event_loop().create_future()
        self._waiters.append((fut, lambda m: m.get("method") == method))
        return await asyncio.wait_for(fut, timeout=timeout)

    async def evaluate(self, expr, await_promise=False, timeout=30):
        res = await self.call("Runtime.evaluate", timeout=timeout, expression=expr,
                              returnByValue=True, awaitPromise=await_promise)
        if "exceptionDetails" in res:
            det = res["exceptionDetails"]
            text = det.get("exception", {}).get("description") or det.get("text")
            raise RuntimeError(f"JS error: {text}")
        return res.get("result", {}).get("value")

    async def poll(self, expr, timeout=15, interval=0.1):
        """Espera hasta que `expr` (JS booleano) sea verdadero o expire."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if await self.evaluate(f"!!({expr})"):
                    return True
            except Exception:
                pass
            await asyncio.sleep(interval)
        return False


async def open_page(chrome, url, ready_expr="typeof loadProduct==='function' && !!state",
                    timeout=20):
    """Conecta a la página, navega a `url` y espera a que la SPA esté lista."""
    ws = await websockets.connect(chrome.page_ws_url(), max_size=None)
    sess = Session(ws).start()
    await sess.call("Page.enable")
    await sess.call("Runtime.enable")
    await sess.call("Page.navigate", url=url)
    try:
        await sess.wait_event("Page.loadEventFired", timeout=timeout)
    except asyncio.TimeoutError:
        pass
    # window.print no-op: evita que un click en "Generar informe" bloquee headless.
    await sess.evaluate("window.print = function(){};")
    if not await sess.poll(ready_expr, timeout=timeout):
        raise RuntimeError("La SPA no quedó lista (estado/funciones no disponibles)")
    return sess, ws
