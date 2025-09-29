# get_encrypted.py
import base64
from pathlib import Path

from patchright.async_api import async_playwright
from pathlib import Path

BASE_DIR = Path(__file__).parent 

CHUNK = BASE_DIR / "wasm_chunk.py"
WASM = BASE_DIR / "wasm_lib.py"

HARNESS = r"""
// 1) Make the webpack bus BEFORE evaluating the chunk
window.__BUCKET__ = {};
window.webpackChunk_N_E = window.webpackChunk_N_E || [];
const __arr = window.webpackChunk_N_E;
const __origPush = __arr.push.bind(__arr);
__arr.push = function(args){
  try {
    const [, mods] = args; // [chunkIds], { id: factory }, runtime?
    if (mods && typeof mods === 'object') Object.assign(window.__BUCKET__, mods);
  } catch (e) {}
  return __origPush(args);
};

// 2) Minimal webpack runtime
window.__cache__ = {};
window.__require__ = function(id){
  if (window.__cache__[id]) return window.__cache__[id].exports;
  const factory = window.__BUCKET__[id];
  if (!factory) throw new Error("Module not found: " + id);
  const module = { exports: {} };
  window.__cache__[id] = module;
  factory(module, module.exports, window.__require__);
  return module.exports;
};
window.__require__.d = (exports, def) => {
  for (const k in def)
    if (Object.prototype.hasOwnProperty.call(def, k) && !Object.prototype.hasOwnProperty.call(exports, k))
      Object.defineProperty(exports, k, { enumerable: true, get: def[k] });
};
window.__require__.r = (exports) => {
  if (typeof Symbol !== 'undefined' && Symbol.toStringTag)
    Object.defineProperty(exports, Symbol.toStringTag, { value: 'Module' });
  Object.defineProperty(exports, '__esModule', { value: true });
};
window.__require__.g = window;

// 3) Find the glue module (the one that exports Ay and Qc)
window.__exposeGlue__ = () => {
  const ids = Object.keys(window.__BUCKET__);
  for (const id of ids) {
    let mod;
    try { mod = window.__require__(+id); } catch (_) { continue; }
    const cands = [mod, mod && mod.default].filter(Boolean);
    for (const obj of cands) {
      if (obj && typeof obj.Ay === 'function' && typeof obj.Qc === 'function') {
        window.__GLUE__ = { Ay: obj.Ay, Qc: obj.Qc };
        return +id;
      }
    }
  }
  return null;
};
"""

# 1) Change EVAL_CALL to take harnessCode and eval it first
EVAL_CALL = r"""
async ({ e, t, harnessCode, chunkCode, wasmB64 }) => {
  // Install harness NOW, in this exact world
  (0, eval)(harnessCode);

  // Minimal stubs
  window.navigator ||= {
    userAgent: 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/136.0.0.0 Safari/537.36',
    languages: ['en-US','en'],
    platform: 'Win32',
    hardwareConcurrency: 8,
  };
  window.document ||= {
    cookie: '',
    getElementById: () => null,
    createElement: () => ({ getContext: () => ({ getExtension: () => null, getParameter: () => 0 }) }),
  };
  window.performance ||= { now: () => Date.now() };

  // Sanity check
  if (typeof window.__exposeGlue__ !== 'function') {
    throw new Error("Harness not installed; typeof __exposeGlue__ = " + typeof window.__exposeGlue__);
  }

  // 1) Evaluate your webpack chunk (captures modules)
  (0, eval)(chunkCode);

  // 2) Find glue (Ay/Qc)
  const glueId = window.__exposeGlue__();
  if (!glueId || !window.__GLUE__) {
    throw new Error("Glue not found; ids=" + Object.keys(window.__BUCKET__).join(','));
  }

  // 3) Compile WASM, init, call
  const bytes = Uint8Array.from(atob(wasmB64), c => c.charCodeAt(0));
  const module = await WebAssembly.compile(bytes);
  await window.__GLUE__.Ay(module);

  const out = await window.__GLUE__.Qc(e, t);
  return (typeof out === 'string') ? out : JSON.stringify(out);
}
"""


from urllib.parse import urlparse
def _parse_proxy_settings( proxy_str: str | None) -> dict:
        parsed = urlparse(proxy_str)
        
        username = parsed.username or ""
        password = parsed.password or ""
        server = f"{parsed.scheme}://{parsed.hostname}:{parsed.port}"
        
        return {
            "server": server,
            "username": username,
            "password": password
        }
        
 
async def get_encrypted_data(action: str, gen_time: str, proxy : str): 

    try:
        chunk_code = CHUNK.read_text(encoding="utf-8")
        wasm_b64 = base64.b64encode(WASM.read_bytes()).decode("ascii")
        async with async_playwright() as context:
            context.chromium.launch
            browser = await context.chromium.launch(
                channel="chrome",
                headless=True,
                proxy=_parse_proxy_settings(proxy),
                args=["--ignore-gpu-blocklist","--disable-dev-shm-usage","--no-sandbox"]
            )

            page = await browser.new_page()

            await page.goto("https://app.galxe.com/hub", wait_until="networkidle")
      
            result = await page.evaluate(
                EVAL_CALL,
                {
                    "e": action,
                    "t": gen_time,
                    "harnessCode": HARNESS,  
                    "chunkCode": chunk_code,
                    "wasmB64": wasm_b64,
                },
            )

            await browser.close()
            return result
    except Exception as ex:
        print("Error in get_encrypted:", ex)
        return ""

   
 