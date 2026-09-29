"""Write the static HTML reference for a Schema model.

The output is a plain directory of pages that works from file:// (no server, no network): one page per complex
type, A-Z indexes of elements and types, simple types, groups, Schematron rules, and a search box fed by a
generated script. Output is a pure function of the input files: no timestamps, stable order, so the generated
site can be committed and checked for staleness.
"""
from __future__ import annotations

import json
import re
from html import escape

from . import model as m
from .model import ROOT_TYPE, Attribute, Particle, Schema, SimpleType

GENERATOR = "sr-schemadoc"

CSS = """\
:root{--bg:#fbfbfa;--fg:#1d1f21;--muted:#5d6166;--line:#e3e3df;--panel:#f2f2ef;--accent:#2457c5;--code:#7a2e0e;
--chip:#e8edf8;--req:#a4161a;--warn:#fff6d6;font-family:system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#15171a;--fg:#e6e6e3;--muted:#9aa0a6;
--line:#2c3036;--panel:#1c1f23;--accent:#8ab4ff;--code:#f2b48c;--chip:#23304a;--req:#ff8a8a;--warn:#3a3320}}
:root[data-theme="dark"]{--bg:#15171a;--fg:#e6e6e3;--muted:#9aa0a6;--line:#2c3036;--panel:#1c1f23;--accent:#8ab4ff;
--code:#f2b48c;--chip:#23304a;--req:#ff8a8a;--warn:#3a3320}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);line-height:1.5;font-size:15px}
a{color:var(--accent);text-decoration:none}a:hover{text-decoration:underline}
header{position:sticky;top:0;z-index:2;background:var(--bg);border-bottom:1px solid var(--line)}
.bar{max-width:1100px;margin:0 auto;padding:10px 16px;display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center}
.brand{font-weight:650;color:var(--fg)}
nav{display:flex;flex-wrap:wrap;gap:4px 14px;font-size:14px}
.search{position:relative;margin-left:auto;flex:1 1 220px;max-width:340px}
.search input{width:100%;padding:6px 10px;border:1px solid var(--line);border-radius:6px;background:var(--panel);
color:var(--fg);font:inherit;font-size:14px}
.results{position:absolute;right:0;left:0;top:100%;margin:4px 0 0;padding:4px 0;list-style:none;background:var(--bg);
border:1px solid var(--line);border-radius:6px;max-height:60vh;overflow:auto;box-shadow:0 6px 24px rgba(0,0,0,.18)}
.results:empty{display:none}.results li a{display:block;padding:4px 10px;color:var(--fg)}
.results li a.sel,.results li a:hover{background:var(--chip);text-decoration:none}
.results small{color:var(--muted);margin-left:6px}
main{max-width:1100px;margin:0 auto;padding:8px 16px 48px}
h1{font-size:26px;margin:22px 0 4px}h2{font-size:19px;margin:30px 0 8px;padding-top:6px;border-top:1px solid var(--line)}
h3{font-size:16px;margin:20px 0 6px}
.sub{color:var(--muted);margin:0 0 12px}
code,pre{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:13px}
code{color:var(--code)}a code{color:inherit}
pre{background:var(--panel);border:1px solid var(--line);border-radius:6px;padding:10px 12px;overflow:auto;white-space:pre-wrap}
.doc p{margin:6px 0}
.wrap{overflow-x:auto;border:1px solid var(--line);border-radius:6px}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{text-align:left;vertical-align:top;padding:6px 10px;border-bottom:1px solid var(--line)}
th{background:var(--panel);font-weight:600;white-space:nowrap}tr:last-child td{border-bottom:0}
td.n{white-space:nowrap}
tr.from td{background:var(--panel);color:var(--muted);font-size:13px}
.chip{display:inline-block;padding:0 6px;margin:1px 2px 1px 0;border-radius:4px;background:var(--chip);font-size:12px;
white-space:nowrap}
.req{color:var(--req);font-weight:600}
.occ{color:var(--muted);font-size:12px;margin-left:6px}
ul.model,ul.model ul,ol.model{margin:2px 0;padding-left:20px}
.model li{margin:2px 0}
.lbl{color:var(--muted);font-size:13px}
details>summary{cursor:pointer}
ul.tree{list-style:none;padding-left:16px;margin:0}ul.tree>li{margin:1px 0}
.cols{columns:3 220px;column-gap:24px;padding-left:18px}.cols li{break-inside:avoid}
.rule{border:1px solid var(--line);border-radius:6px;padding:8px 12px;margin:10px 0}
.rule .ctx{font-size:13px}
.assert{margin:6px 0 0}.assert .id{font-weight:600;margin-right:6px}
.assert code.test{display:block;margin-top:2px;color:var(--muted);white-space:pre-wrap}
footer{max-width:1100px;margin:0 auto;padding:16px;color:var(--muted);font-size:12px;border-top:1px solid var(--line)}
@media (max-width:600px){h1{font-size:22px}.search{max-width:none}}
"""

SEARCH_JS = """\
(function(){
  var box=document.getElementById('q'),out=document.getElementById('res'),base=document.body.dataset.root||'';
  if(!box||!window.SR_INDEX)return;
  var sel=-1;
  function render(){
    var q=box.value.trim().toLowerCase();out.innerHTML='';sel=-1;if(!q)return;
    var hits=[];
    for(var i=0;i<SR_INDEX.length&&hits.length<40;i++){
      var e=SR_INDEX[i],k=e[0].toLowerCase(),p=k.indexOf(q);
      if(p>=0)hits.push([p===0?0:(k.charAt(p-1).match(/[^a-z0-9]/)?1:2),e]);
    }
    hits.sort(function(a,b){return a[0]-b[0]||a[1][0].length-b[1][0].length});
    hits.forEach(function(h){var e=h[1],li=document.createElement('li'),a=document.createElement('a');
      a.href=base+e[1];a.textContent=e[0];var s=document.createElement('small');s.textContent=e[2];a.appendChild(s);
      li.appendChild(a);out.appendChild(li)});
  }
  function move(d){var as=out.querySelectorAll('a');if(!as.length)return;if(sel>=0)as[sel].classList.remove('sel');
    sel=(sel+d+as.length)%as.length;as[sel].classList.add('sel');as[sel].scrollIntoView({block:'nearest'})}
  box.addEventListener('input',render);
  box.addEventListener('keydown',function(ev){
    if(ev.key==='ArrowDown'){move(1);ev.preventDefault()}else if(ev.key==='ArrowUp'){move(-1);ev.preventDefault()}
    else if(ev.key==='Enter'){var as=out.querySelectorAll('a');var a=as[sel>=0?sel:0];if(a)location.href=a.href}
    else if(ev.key==='Escape'){box.value='';render()}});
  document.addEventListener('keydown',function(ev){if(ev.key==='/'&&document.activeElement!==box){box.focus();ev.preventDefault()}});
  document.addEventListener('click',function(ev){if(!ev.target.closest('.search'))out.innerHTML=''});
})();
"""

NAV = [("index.html", "Overview"), ("elements.html", "Elements"), ("types.html", "Types"),
       ("simple-types.html", "Simple types"), ("groups.html", "Groups"), ("rules.html", "Rules")]


def slug(key: str) -> str:
    return "scene" if key == ROOT_TYPE else re.sub(r"[^A-Za-z0-9_.-]", ".", key)


def type_href(key: str, depth: int = 0) -> str:
    return "../" * depth + f"type/{slug(key)}.html"


class Site:
    def __init__(self, s: Schema):
        self.s = s
        self.files: dict[str, str] = {}
        # which parents use each type, as element names
        self.used_by: dict[str, list[m.Usage]] = {}
        for u in s.usages:
            if u.type:
                self.used_by.setdefault(u.type, []).append(u)
        self.rules_for: dict[str, list[m.Rule]] = {}
        for r in s.rules:
            for k in m.rule_types(s, r.context):
                self.rules_for.setdefault(k, []).append(r)
        self.title = f"scene-render {s.version} schema"

    # ------------------------------------------------------------ helpers
    def page(self, path: str, title: str, body: str, depth: int = 0) -> None:
        up = "../" * depth
        nav = " ".join(f'<a href="{up}{h}">{t}</a>' for h, t in NAV)
        foot = (f"Generated by {GENERATOR} from <a href=\"{up}{escape(self.s.xsd_name)}\">{escape(self.s.xsd_name)}</a> "
                f"(SHA-256 <code>{self.s.xsd_sha256}</code>)")
        if self.s.sch_name:
            foot += (f" and <a href=\"{up}{escape(self.s.sch_name)}\">{escape(self.s.sch_name)}</a> "
                     f"(SHA-256 <code>{self.s.sch_sha256}</code>)")
        self.files[path] = (
            "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{escape(title)} — {escape(self.title)}</title>\n"
            f"<link rel=\"stylesheet\" href=\"{up}style.css\">\n</head>\n"
            f"<body data-root=\"{up}\">\n<header><div class=\"bar\"><a class=\"brand\" href=\"{up}index.html\">"
            f"{escape(self.title)}</a>\n<nav>{nav}</nav>\n"
            "<div class=\"search\"><input id=\"q\" type=\"search\" placeholder=\"Search elements, attributes, types  ( / )\" "
            "autocomplete=\"off\" aria-label=\"Search\"><ul id=\"res\" class=\"results\"></ul></div>"
            "</div></header>\n"
            f"<main>\n{body}\n</main>\n<footer>{foot}.</footer>\n"
            f"<script src=\"{up}search-index.js\"></script>\n<script src=\"{up}search.js\"></script>\n"
            "</body>\n</html>\n")

    def doc(self, text: str) -> str:
        if not text:
            return ""
        out = []
        for para in re.split(r"\n\s*\n", text.strip()):
            lines = para.split("\n")
            structured = len(lines) > 1 and any(re.match(r"\s*([-*•]|\d+[.)])\s", ln) or re.search(r"\S {2,}\S", ln)
                                                for ln in lines)
            if structured:
                out.append(f"<pre>{escape(textwrap_dedent(para))}</pre>")
            else:
                out.append("<p>" + inline(" ".join(ln.strip() for ln in lines)) + "</p>")
        return '<div class="doc">' + "\n".join(out) + "</div>"

    def tref(self, name: str | None, depth: int) -> str:
        """A link to a named type (complex or simple), or the built-in's name."""
        if not name:
            return "<code>any</code>"
        if name in self.s.complex:
            return f'<a href="{type_href(name, depth)}"><code>{escape(name)}</code></a>'
        if name in self.s.simple:
            return f'<a href="{"../" * depth}simple-types.html#{escape(name)}"><code>{escape(name)}</code></a>'
        return f"<code>{escape(name)}</code>"

    def kref(self, key: str, depth: int) -> str:
        """A link to a complex type by key; the root's anonymous type is shown as its element."""
        if key == ROOT_TYPE:
            return f'<a href="{type_href(ROOT_TYPE, depth)}"><code>&lt;{escape(self.s.root)}&gt;</code></a>'
        return self.tref(key, depth)

    def simple_desc(self, st: SimpleType, depth: int, open_enums: bool = False) -> str:
        if st.kind == "list":
            inner = self.simple_desc(st.inline[0], depth) if st.inline else self.tref(st.base, depth)
            return f"list of {inner}"
        if st.kind == "union":
            parts = [self.tref(t, depth) for t in st.members] + [self.simple_desc(i, depth) for i in st.inline]
            return " or ".join(parts)
        base = self.simple_desc(st.inline[0], depth) if st.inline else self.tref(st.base, depth)
        bits = []
        if st.enums:
            chips = " ".join(f'<span class="chip"><code>{escape(v)}</code></span>' for v, _ in st.enums)
            if len(st.enums) > 12 and not open_enums:
                return f"<details><summary>one of {len(st.enums)} values</summary>{chips}</details>"
            return f"one of {chips}"
        f = dict(st.facets)
        lo = f.get("minInclusive"), f.get("minExclusive")
        hi = f.get("maxInclusive"), f.get("maxExclusive")
        if any(v is not None for v in lo) and any(v is not None for v in hi):
            l = f"[{lo[0]}" if lo[0] is not None else f"({lo[1]}"
            h = f"{hi[0]}]" if hi[0] is not None else f"{hi[1]})"
            bits.append(f"in {l}, {h}")
        elif any(v is not None for v in lo):
            bits.append(f"≥ {lo[0]}" if lo[0] is not None else f"> {lo[1]}")
        elif any(v is not None for v in hi):
            bits.append(f"≤ {hi[0]}" if hi[0] is not None else f"< {hi[1]}")
        for k in ("length", "minLength", "maxLength", "totalDigits", "fractionDigits"):
            if k in f:
                bits.append(f"{k} {escape(f[k])}")
        for k, v in st.facets:
            if k == "pattern":
                bits.append(f"matching <code>{escape(v)}</code>")
        return base + (" " + ", ".join(bits) if bits else "")

    def attr_type(self, a: Attribute, depth: int) -> str:
        if a.inline is not None:
            return self.simple_desc(a.inline, depth)
        return self.tref(a.type, depth) if a.type else "<code>any</code>"

    def occurs(self, p: Particle) -> str:
        lo, hi = p.min, p.max
        if (lo, hi) == ("1", "1"):
            return ""
        txt = {("0", "1"): "optional", ("0", "unbounded"): "any number", ("1", "unbounded"): "one or more"}.get(
            (lo, hi), f"{lo}..{'∞' if hi == 'unbounded' else hi}")
        return f'<span class="occ">{txt}</span>'

    def model(self, p: Particle | None, depth: int, seen_groups: tuple[str, ...] = ()) -> str:
        if p is None:
            return ""
        if p.kind == "element":
            if p.name == "*":
                return f"<li>{escape(p.doc)}{self.occurs(p)}</li>"
            target = (f'<a href="{type_href(p.type, depth)}"><code>&lt;{escape(p.name)}&gt;</code></a>'
                      if p.type in self.s.complex else f"<code>&lt;{escape(p.name)}&gt;</code> {self.tref(p.type, depth)}")
            d = f' — {inline(first_sentence(p.doc))}' if p.doc else ""
            return f"<li>{target}{self.occurs(p)}{d}</li>"
        if p.kind == "group":
            g = self.s.groups[p.name]
            link = f'<a href="{"../" * depth}groups.html#{escape(p.name)}"><code>{escape(p.name)}</code></a>'
            if p.name in seen_groups:
                return f"<li>group {link}{self.occurs(p)} (recursive)</li>"
            inner = self.model(g.content, depth, seen_groups + (p.name,))
            return (f"<li><details><summary>group {link}{self.occurs(p)}</summary>"
                    f"<ul class=\"model\">{inner}</ul></details></li>")
        label = {"sequence": "in this order", "choice": "one of", "all": "all, in any order"}[p.kind]
        inner = "".join(self.model(c, depth, seen_groups) for c in p.children)
        tag = "ol" if p.kind == "sequence" else "ul"
        return f'<li><span class="lbl">{label}</span>{self.occurs(p)}<{tag} class="model">{inner}</{tag}></li>'

    def attr_table(self, attrs: list[Attribute], depth: int, anchors: bool) -> str:
        if not attrs:
            return "<p>None.</p>"
        rows, last = [], object()
        for a in attrs:
            src = (a.inherited, a.origin)
            if src != last and (a.inherited or a.origin):
                bits = []
                if a.inherited:
                    bits.append(f"inherited from {self.tref(a.inherited, depth)}")
                if a.origin:
                    bits.append(f'from attribute group <a href="{"../" * depth}groups.html#{escape(a.origin)}">'
                                f"<code>{escape(a.origin)}</code></a>")
                rows.append(f'<tr class="from"><td colspan="4">{" ".join(bits)}</td></tr>')
            elif src != last:
                rows.append('<tr class="from"><td colspan="4">declared here</td></tr>')
            last = src
            aid = f' id="a-{escape(a.name)}"' if anchors else ""
            req = ' <span class="req">required</span>' if a.use == "required" else ""
            dflt = (f"<code>{escape(a.default)}</code>" if a.default is not None else
                    f"<code>{escape(a.fixed)}</code> (fixed)" if a.fixed is not None else "")
            rows.append(f"<tr{aid}><td class=\"n\"><code>{escape(a.name)}</code>{req}</td>"
                        f"<td>{self.attr_type(a, depth)}</td><td>{dflt}</td><td>{self.doc(a.doc)}</td></tr>")
        return ('<div class="wrap"><table><thead><tr><th>Attribute</th><th>Type</th><th>Default</th>'
                "<th>Description</th></tr></thead><tbody>" + "\n".join(rows) + "</tbody></table></div>")

    def rules_html(self, rules: list[m.Rule], depth: int, extra: str = "", anchor: bool = False) -> str:
        out = []
        for r in rules:
            asserts = "".join(
                f'<div class="assert"><span class="id">{escape(a.id or "·")}</span>{inline_msg(a.message)}'
                f'<code class="test">{"report if" if a.kind == "report" else "test"}: {escape(a.test)}</code></div>'
                for a in r.asserts)
            rid = f' id="{escape(r.pattern)}"' if anchor else ""
            out.append(f'<div class="rule"{rid}><div class="ctx"><span class="lbl">context</span> '
                       f"<code>{escape(r.context)}</code> <a class=\"lbl\" href=\"{'../' * depth}rules.html#"
                       f"{escape(r.pattern)}\">{escape(r.pattern)}</a></div>{asserts}{extra}</div>")
        return "\n".join(out)

    # ------------------------------------------------------------ pages
    def type_page(self, key: str) -> None:
        s, t = self.s, self.s.complex[key]
        uses = self.used_by.get(key, [])
        parts = [f"<h1>{escape(t.label if key != ROOT_TYPE else '<' + s.root + '>')}</h1>"]
        if key == ROOT_TYPE:
            parts.append(f'<p class="sub">The document element. Its type is anonymous.</p>')
        elif uses:
            by: dict[str, list[str]] = {}
            for u in uses:
                if u.parent not in by.setdefault(u.element, []):
                    by[u.element].append(u.parent)
            chips = []
            for el, parents in by.items():
                links = ", ".join(self.kref(k, 1) for k in parents)
                where = (f"<details><summary>in {len(parents)} types</summary>{links}</details>"
                         if len(parents) > 6 else f"in {links}")
                chips.append(f"<code>&lt;{escape(el)}&gt;</code> {where}")
            parts.append('<div class="sub">Type of ' + "; ".join(chips) + "</div>")
        else:
            parts.append('<p class="sub">Not used by any element (base type or unused).</p>')
        parts.append(self.doc(t.doc))
        if t.base:
            parts.append(f"<p>Extends {self.tref(t.base, 1)}.</p>")
        subs = sorted(k for k, o in s.complex.items() if o.base == key)
        if subs:
            parts.append("<p>Extended by " + ", ".join(self.tref(k, 1) for k in subs) + ".</p>")
        parts.append("<h2>Content</h2>")
        if t.simple_base:
            parts.append(f"<p>Text content: {self.tref(t.simple_base, 1)}.</p>")
        elif t.content is not None or t.base:
            chain = []
            b = t
            while b is not None:
                chain.append(b)
                b = s.complex.get(b.base) if b.base else None
            for b in reversed(chain):
                if b.content is None:
                    continue
                head = f"<h3>From {self.tref(b.key, 1)}</h3>" if b is not t else ""
                parts.append(head + f'<ul class="model">{self.model(b.content, 1)}</ul>')
            if t.mixed:
                parts.append("<p>Text may appear between the child elements.</p>")
        else:
            parts.append("<p>Empty: attributes only.</p>")
        parts.append("<h2>Attributes</h2>")
        attrs = s.all_attributes(key)
        order = lambda a: (a.inherited is not None, a.origin is not None)
        parts.append(self.attr_table(sorted(attrs, key=order), 1, anchors=True))
        rules = self.rules_for.get(key, [])
        if rules:
            parts.append("<h2>Schematron rules</h2>")
            parts.append(self.rules_html(rules, 1))
        self.page(type_href(key), t.label if key != ROOT_TYPE else f"<{s.root}>", "\n".join(parts), depth=1)

    def elements_page(self) -> None:
        by: dict[tuple[str, str | None], list[str]] = {}
        for u in self.s.usages:
            by.setdefault((u.element, u.type), [])
            if u.parent not in by[(u.element, u.type)]:
                by[(u.element, u.type)].append(u.parent)
        rows = [f'<tr><td class="n"><a href="{type_href(ROOT_TYPE)}"><code>&lt;{escape(self.s.root)}&gt;</code></a></td>'
                f"<td>anonymous</td><td>document element</td></tr>"]
        for (name, typ), parents in sorted(by.items(), key=lambda kv: (kv[0][0].lower(), kv[0][1] or "")):
            ps = ", ".join(self.kref(p, 0) for p in sorted(parents, key=lambda k: (k != ROOT_TYPE, k.lower())))
            el = (f'<a href="{type_href(typ)}"><code>&lt;{escape(name)}&gt;</code></a>' if typ in self.s.complex
                  else f"<code>&lt;{escape(name)}&gt;</code>")
            rows.append(f'<tr id="e-{escape(name)}-{escape(slug(typ or "none"))}"><td class="n">{el}</td>'
                        f"<td>{self.tref(typ, 0)}</td><td>{ps}</td></tr>")
        body = (f"<h1>Elements</h1><p class=\"sub\">{len(rows)} element declarations, A–Z. An element name "
                "declared with different types in different places is listed once per type.</p>"
                '<div class="wrap"><table><thead><tr><th>Element</th><th>Type</th><th>Appears in</th></tr></thead>'
                "<tbody>" + "\n".join(rows) + "</tbody></table></div>")
        self.page("elements.html", "Elements", body)

    def types_page(self) -> None:
        rows = []
        for key in sorted((k for k in self.s.complex if k != ROOT_TYPE), key=str.lower):
            t = self.s.complex[key]
            n = len(self.s.all_attributes(key))
            rows.append(f"<tr><td class=\"n\">{self.tref(key, 0)}</td><td>{n}</td>"
                        f"<td>{inline(first_sentence(t.doc))}</td></tr>")
        body = ("<h1>Complex types</h1>"
                f"<p class=\"sub\">{len(rows)} named types, A–Z. Each element's page is its type's page.</p>"
                '<div class="wrap"><table><thead><tr><th>Type</th><th>Attributes</th><th>Summary</th></tr></thead>'
                "<tbody>" + "\n".join(rows) + "</tbody></table></div>")
        self.page("types.html", "Types", body)

    def simple_page(self) -> None:
        parts = [f"<h1>Simple types</h1><p class=\"sub\">{len(self.s.simple)} named value types, A–Z.</p>",
                 '<ul class="cols">' + "".join(f'<li><a href="#{escape(n)}"><code>{escape(n)}</code></a></li>'
                                               for n in sorted(self.s.simple, key=str.lower)) + "</ul>"]
        users: dict[str, list[str]] = {}
        for key in self.s.complex:
            for a in self.s.all_attributes(key):
                if a.type in self.s.simple and key not in users.setdefault(a.type, []):
                    users[a.type].append(key)
        for n in sorted(self.s.simple, key=str.lower):
            st = self.s.simple[n]
            parts.append(f'<h2 id="{escape(n)}"><code>{escape(n)}</code></h2>')
            parts.append(self.doc(st.doc))
            parts.append(f"<p>{self.simple_desc(st, 0, open_enums=True)}</p>")
            docs = [(v, d) for v, d in st.enums if d]
            if docs:
                parts.append('<div class="wrap"><table><tbody>' + "".join(
                    f"<tr><td class=\"n\"><code>{escape(v)}</code></td><td>{self.doc(d)}</td></tr>" for v, d in docs)
                             + "</tbody></table></div>")
            u = sorted(users.get(n, []), key=str.lower)
            if u:
                shown = ", ".join(self.tref(k, 0) for k in u[:30]) + (f" and {len(u) - 30} more" if len(u) > 30 else "")
                parts.append(f'<p class="lbl">Used by {shown}.</p>')
        self.page("simple-types.html", "Simple types", "\n".join(parts))

    def groups_page(self) -> None:
        parts = ["<h1>Groups</h1><p class=\"sub\">Element groups are reusable content models; attribute groups "
                 "are reusable attribute sets. Type pages show both expanded.</p>", "<h2>Element groups</h2>"]
        for n in sorted(self.s.groups, key=str.lower):
            g = self.s.groups[n]
            parts.append(f'<h3 id="{escape(n)}"><code>{escape(n)}</code></h3>{self.doc(g.doc)}'
                         f'<ul class="model">{self.model(g.content, 0, (n,))}</ul>')
        parts.append("<h2>Attribute groups</h2>")
        for n in sorted(self.s.attr_groups, key=str.lower):
            g = self.s.attr_groups[n]
            parts.append(f'<h3 id="{escape(n)}"><code>{escape(n)}</code></h3>{self.doc(g.doc)}'
                         + self.attr_table([Attribute(**{**a.__dict__, "origin": None if a.origin == n else a.origin})
                                            for a in g.attributes], 0, anchors=False))
        self.page("groups.html", "Groups", "\n".join(parts))

    def rules_page(self) -> None:
        s = self.s
        if not s.rules:
            self.page("rules.html", "Rules", "<h1>Schematron rules</h1><p>No Schematron file was given.</p>")
            return
        n = sum(len(r.asserts) for r in s.rules)
        parts = [f"<h1>Schematron rules</h1><p class=\"sub\">{escape(s.sch_title)}. {len(s.rules)} rules, {n} "
                 "assertions, checked after XSD validation. A document is valid when every assertion holds.</p>"]
        anchored: set[str] = set()
        for r in s.rules:
            keys = m.rule_types(s, r.context)
            applies = ", ".join(self.kref(k, 0) for k in keys[:12]) + (f" and {len(keys) - 12} more" if len(keys) > 12 else "")
            parts.append(self.rules_html([r], 0, f'<p class="lbl">Applies to {applies}.</p>' if keys else "",
                                         anchor=r.pattern not in anchored))
            anchored.add(r.pattern)
        self.page("rules.html", "Rules", "\n".join(parts))

    def index_page(self) -> None:
        s = self.s
        nattr = sum(len(t.attributes) for t in s.complex.values()) + sum(len(g.attributes) for g in s.attr_groups.values())
        stats = (f"{len(s.complex) - 1} complex types, {len(s.simple)} simple types, {len({u.element for u in s.usages}) + 1} "
                 f"element names, {len(s.groups)} element groups, {len(s.attr_groups)} attribute groups, "
                 f"{sum(len(r.asserts) for r in s.rules)} Schematron assertions")
        expanded: set[str] = set()

        def tree(key: str, name: str, p: Particle | None, depth: int) -> str:
            occ = self.occurs(p) if p else ""
            link = f'<a href="{type_href(key)}"><code>&lt;{escape(name)}&gt;</code></a>{occ}'
            kids = [c for c in s.children(key) if c.type in s.complex]
            if not kids:
                return f"<li>{link}</li>"
            if key in expanded:
                return f'<li>{link} <span class="lbl">(children above)</span></li>'
            expanded.add(key)
            inner = "".join(tree(c.type, c.name, c, depth + 1) for c in kids)
            return f"<li><details{' open' if depth == 0 else ''}><summary>{link}</summary><ul class=\"tree\">{inner}</ul></details></li>"

        body = (f"<h1>{escape(self.title)}</h1><p class=\"sub\">{stats}.</p>"
                f"<p>Downloads: <a href=\"{escape(s.xsd_name)}\"><code>{escape(s.xsd_name)}</code></a>"
                + (f", <a href=\"{escape(s.sch_name)}\"><code>{escape(s.sch_name)}</code></a>" if s.sch_name else "")
                + ". Validate with the XSD first, then the Schematron rules.</p>"
                "<h2>Conventions</h2>" + (f"<pre>{escape(s.doc)}</pre>" if s.doc else "<p>None.</p>")
                + "<h2>Document tree</h2><p class=\"sub\">Every element reachable from the document element. "
                  "A type's children are expanded where it first appears.</p>"
                + f'<ul class="tree">{tree(ROOT_TYPE, s.root, None, 0)}</ul>')
        self.page("index.html", "Overview", body)

    def search_index(self) -> None:
        entries = []
        seen = set()
        entries.append([f"<{self.s.root}>", type_href(ROOT_TYPE), "document element"])
        for u in sorted(self.s.usages, key=lambda u: (u.element.lower(), u.type or "", u.parent)):
            if u.type in self.s.complex and (u.element, u.type) not in seen:
                seen.add((u.element, u.type))
                entries.append([f"<{u.element}>", type_href(u.type), f"element · {self.s.complex[u.type].label}"])
        for key in sorted(self.s.complex, key=str.lower):
            if key != ROOT_TYPE:
                entries.append([key, type_href(key), "type"])
        for key in sorted(self.s.complex, key=str.lower):
            label = f"<{self.s.root}>" if key == ROOT_TYPE else key
            for a in self.s.all_attributes(key):
                if a.name != "*":
                    entries.append([f"@{a.name}", f"{type_href(key)}#a-{a.name}", label])
        for n in sorted(self.s.simple, key=str.lower):
            entries.append([n, f"simple-types.html#{n}", "simple type"])
        for n in sorted(self.s.groups, key=str.lower):
            entries.append([n, f"groups.html#{n}", "element group"])
        for n in sorted(self.s.attr_groups, key=str.lower):
            entries.append([n, f"groups.html#{n}", "attribute group"])
        for r in self.s.rules:
            for a in r.asserts:
                if a.id:
                    entries.append([a.id, f"rules.html#{r.pattern}", "rule · " + a.message[:60]])
        self.files["search-index.js"] = ("window.SR_INDEX=" + json.dumps(entries, ensure_ascii=False, separators=(",", ":"))
                                         + ";\n")

    def build(self) -> dict[str, str]:
        for key in self.s.complex:
            self.type_page(key)
        self.elements_page()
        self.types_page()
        self.simple_page()
        self.groups_page()
        self.rules_page()
        self.index_page()
        self.search_index()
        self.files["style.css"] = CSS
        self.files["search.js"] = SEARCH_JS
        return dict(sorted(self.files.items()))


# ------------------------------------------------------------------ text
def textwrap_dedent(s: str) -> str:
    import textwrap
    return textwrap.dedent(s)


def first_sentence(text: str) -> str:
    t = " ".join(text.split())
    m_ = re.match(r"(.+?[.;:])(\s|$)", t)
    return (m_.group(1) if m_ else t)[:220]


def inline(text: str) -> str:
    """Escape text and render `backticks` as code."""
    out, pos = [], 0
    for mm in re.finditer(r"`([^`]+)`", text):
        out.append(escape(text[pos:mm.start()]))
        out.append(f"<code>{escape(mm.group(1))}</code>")
        pos = mm.end()
    out.append(escape(text[pos:]))
    return "".join(out)


def inline_msg(text: str) -> str:
    """A Schematron message: {xpath} placeholders become code."""
    out, pos = [], 0
    for mm in re.finditer(r"\{([^}]+)\}", text):
        out.append(escape(text[pos:mm.start()]))
        out.append(f"<code>{{{escape(mm.group(1))}}}</code>")
        pos = mm.end()
    out.append(escape(text[pos:]))
    return "".join(out)


def build(s: Schema) -> dict[str, str]:
    """Every output file, path -> text."""
    return Site(s).build()
