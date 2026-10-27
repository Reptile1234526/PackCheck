#!/usr/bin/env python3
"""
Build the static GitHub Pages demo into docs/.

Takes the real web UI out of app.py and swaps the Flask API for an in-browser
fake backend (demo/backend.js), so the app can be tried without a Pi or reader.
Run it again after changing the UI in app.py:

    python demo/build.py
"""

import ast
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = ROOT / "demo"
OUT_DIR = ROOT / "docs"


def read_app_strings():
    """Return the module-level string constants in app.py, without importing Flask."""
    tree = ast.parse((ROOT / "app.py").read_text())
    strings = {}
    for node in tree.body:
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant):
            if isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        strings[target.id] = node.value.value
    return strings


def replace(html, old, new):
    if old not in html:
        raise SystemExit(f"build.py: expected to find {old!r} in the app's HTML; update demo/build.py")
    return html.replace(old, new)


HEAD_INJECT = """<link rel="stylesheet" href="demo/ui.css">
<script src="demo/backend.js"></script>
</head>"""


def make_page(html, page):
    html = replace(html, 'href="/favicon.svg"', 'href="favicon.svg"')
    html = replace(html, 'href="/icon.svg"', 'href="icon.svg"')
    html = replace(html, "</head>", HEAD_INJECT)
    html = replace(html, "<body>", f'<body data-demo-page="{page}">')
    html = replace(html, "</body>", '<script src="demo/ui.js"></script>\n</body>')
    return html


def main():
    s = read_app_strings()

    app = s["HTML_TEMPLATE"]
    app = replace(app, '<link rel="manifest" href="/manifest.json">\n', "")
    app = replace(app, "<title>RFID // PACKCHECK</title>", "<title>PackCheck Demo</title>")
    app = replace(app, "if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js');\n", "")
    app = replace(app, "location.origin + '/quickcheck'", "new URL('quickcheck.html', location.href).href")
    app = make_page(app, "app")

    quick = s["QUICKCHECK_TEMPLATE"]
    quick = replace(quick, "<title>PackCheck</title>", "<title>PackCheck Quick Check Demo</title>")
    quick = make_page(quick, "quickcheck")

    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    (OUT_DIR / "demo").mkdir(parents=True)
    (OUT_DIR / "index.html").write_text(app.lstrip())
    (OUT_DIR / "quickcheck.html").write_text(quick.lstrip())
    (OUT_DIR / "icon.svg").write_text(s["ICON_SVG"])
    (OUT_DIR / "favicon.svg").write_text(s["FAVICON_SVG"])
    (OUT_DIR / ".nojekyll").write_text("")
    for name in ("backend.js", "ui.js", "ui.css"):
        shutil.copy(DEMO_DIR / name, OUT_DIR / "demo" / name)
    print(f"Demo built in {OUT_DIR.relative_to(ROOT)}/")


if __name__ == "__main__":
    main()
