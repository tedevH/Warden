"""Compact page snapshots for the planner: visible text + numbered interactive elements, plus screenshots.

Everything in a snapshot is page content, which is UNTRUSTED. `format_for_llm` wraps it in an
<untrusted_page_content> block and neutralises any attempt by the page to close that block early.
"""
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

SNAPSHOT_JS = r"""
() => {
  const visible = el => { const r = el.getBoundingClientRect(), s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const clean = s => (s || '').replace(/\s+/g, ' ').trim().slice(0, 120);
  const nameOf = el => {
    let n = el.getAttribute('aria-label') || '';
    if (!n && el.labels && el.labels.length) n = el.labels[0].innerText;
    if (!n && el.tagName !== 'INPUT') n = el.innerText;
    if (!n) n = el.getAttribute('placeholder') || el.getAttribute('title') || el.getAttribute('name') || el.value || '';
    return clean(n);
  };
  document.querySelectorAll('[data-lend-ref]').forEach(e => e.removeAttribute('data-lend-ref'));
  const sel = 'a[href],button,input:not([type=hidden]),select,textarea,[role=button],[role=link],summary';
  const out = []; let i = 0;
  for (const el of document.querySelectorAll(sel)) {
    if (!visible(el)) continue;
    const ref = 'e' + (++i); el.setAttribute('data-lend-ref', ref);
    const tag = el.tagName.toLowerCase(), type = (el.getAttribute('type') || '').toLowerCase();
    let role = el.getAttribute('role') || {a: 'link', button: 'button', select: 'combobox', textarea: 'textbox', summary: 'button'}[tag] || 'textbox';
    if (tag === 'input') role = {submit: 'button', button: 'button', checkbox: 'checkbox', radio: 'radio', password: 'password'}[type] || 'textbox';
    const item = {ref, role, name: nameOf(el)};
    if (tag === 'a') item.href = el.href;
    if (role === 'password') item.value = el.value ? '(filled)' : '';
    else if ((tag === 'input' || tag === 'textarea') && role === 'textbox') item.value = (el.value || '').slice(0, 80);
    if (tag === 'select') { item.options = [...el.options].map(o => clean(o.text)); item.value = el.value; }
    const form = el.closest('form');
    if (form) { item.form = form.getAttribute('aria-label') || ''; item.form_action = form.action || ''; }
    out.push(item);
  }
  const forms = [...document.forms].map(f => ({action: f.action, method: (f.method || 'get').toLowerCase(),
    label: f.getAttribute('aria-label') || '', has_password: !!f.querySelector('input[type=password]')}));
  const text = (document.body ? document.body.innerText : '').replace(/[ \t]+\n/g, '\n').replace(/\n{3,}/g, '\n\n');
  return {url: location.href, title: document.title, text: text.slice(0, 8000), elements: out, forms};
}
"""


@dataclass
class Snapshot:
    url: str
    title: str
    text: str
    elements: list = field(default_factory=list)
    forms: list = field(default_factory=list)
    screenshot: str | None = None

    @property
    def origin(self):
        p = urlsplit(self.url)
        return f"{p.scheme}://{p.netloc}"

    @property
    def host(self):
        return urlsplit(self.url).hostname or ""

    def element(self, ref):
        return next((e for e in self.elements if e["ref"] == ref), None)

    def find(self, pattern, role=None):
        rx = re.compile(pattern, re.I)
        return next((e for e in self.elements if rx.search(e["name"]) and (role is None or e["role"] == role)), None)

    @property
    def has_password_field(self):
        return any(e["role"] == "password" for e in self.elements)


async def snapshot(page, screenshot_dir: Path | None = None) -> Snapshot:
    try:
        await page.wait_for_load_state("domcontentloaded", timeout=5000)
    except Exception:
        pass
    data = await page.evaluate(SNAPSHOT_JS)
    snap = Snapshot(**data)
    if screenshot_dir is not None:
        screenshot_dir.mkdir(parents=True, exist_ok=True)
        path = screenshot_dir / f"{time.strftime('%H%M%S')}-{int(time.time() * 1000) % 1000:03d}.png"
        await page.screenshot(path=str(path))
        snap.screenshot = str(path)
    return snap


def _neutralise(s: str) -> str:
    return re.sub(r"<\s*/?\s*untrusted", "‹untrusted", s, flags=re.I)


def format_element(e) -> str:
    s = f'[{e["ref"]}] {e["role"]} "{e["name"]}"'
    if e.get("href"):
        s += f' -> {e["href"]}'
    if e.get("options"):
        s += f' options={e["options"]}'
    if e.get("value"):
        s += f' value="{e["value"]}"'
    if e.get("form"):
        s += f' (in form "{e["form"]}")'
    return s


def format_for_llm(snap: Snapshot, max_text=6000) -> str:
    body = _neutralise(snap.text[:max_text])
    elems = "\n".join(_neutralise(format_element(e)) for e in snap.elements[:150])
    notes = ""
    g = getattr(snap, "guard", None)
    if g and g.get("verdict") != "safe" and g.get("plain_explanation"):
        notes = f"WARDEN GUARD NOTES (from Warden's own scam checker, trusted): {g['plain_explanation']}\n"
    return (
        notes +
        f"Current page: {snap.url}\n"
        f'<untrusted_page_content url="{snap.url}">\n'
        f"TITLE: {_neutralise(snap.title)}\n\nVISIBLE TEXT:\n{body}\n\n"
        f"INTERACTIVE ELEMENTS (use the [ref] with your tools):\n{elems}\n"
        f"</untrusted_page_content>"
    )
