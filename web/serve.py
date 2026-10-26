"""Build ParaView Glance with the DisplayXR adapter and serve it on localhost.

    python web/serve.py [--paraview <ParaView install dir>] [--port 8765] [--build-only]

Glance itself is not in this repo: it is copied from the ParaView install
(share/paraview-<ver>/web/glance/www, ParaView Glance, BSD-3-Clause, Kitware) into web/_site/,
and one module script tag is added to its index.html. Nothing in Glance is modified otherwise.

Open:  http://127.0.0.1:8765/?name=disk_out_ref.vtp&url=data/disk_out_ref.vtp
"""
import argparse
import functools
import glob
import http.server
import os
import re
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "_site")
TAG = '<script type="module" src="displayxr/src/displayxr-glance.js"></script>'


def _version(path):
    """(major, minor, patch) from a share/paraview-<ver> path, for picking the newest."""
    m = re.search(r"paraview-(\d+)\.(\d+)(?:\.(\d+))?", path, re.IGNORECASE)
    return tuple(int(x or 0) for x in m.groups()) if m else (0, 0, 0)


def find_glance(pv):
    """Glance's www folder in the given ParaView install, else in PARAVIEW_EXE / PARAVIEW_HOME,
    else in the newest ParaView found where the launcher looks (tools/Find-ParaView.ps1)."""
    exe = os.environ.get("PARAVIEW_EXE")
    pv = pv or os.environ.get("PARAVIEW_HOME") or (os.path.dirname(os.path.dirname(exe)) if exe else None)
    roots = [pv] if pv else (
        glob.glob(os.path.join(os.environ.get("ProgramFiles", r"C:\Program Files"), "ParaView *"))
        + glob.glob(os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ParaView*"))
        + glob.glob(os.path.expanduser(os.path.join("~", "ParaView-*")))
    )
    cands = []
    for root in roots:
        cands += glob.glob(os.path.join(root, "share", "paraview-*", "web", "glance", "www"))
    for c in sorted(cands, key=_version, reverse=True):
        if os.path.isfile(os.path.join(c, "index.html")):
            return c
    where = pv or "the installed ParaViews"
    sys.exit(f"ParaView Glance not found in {where}: pass --paraview <ParaView install dir> "
             "or set PARAVIEW_HOME")


def build(pv):
    src = find_glance(pv)
    if os.path.isdir(SITE):
        shutil.rmtree(SITE)
    shutil.copytree(src, SITE)
    # Glance's service worker would cache the page and hide adapter updates: drop it.
    for f in ("serviceWorker.js",):
        p = os.path.join(SITE, f)
        if os.path.exists(p):
            os.remove(p)
    for sub in ("src", "vendor"):
        shutil.copytree(os.path.join(HERE, sub), os.path.join(SITE, "displayxr", sub))
    shutil.copytree(os.path.join(HERE, "data"), os.path.join(SITE, "data"))
    idx = os.path.join(SITE, "index.html")
    with open(idx, encoding="utf-8") as fh:
        html = fh.read()
    # The two external chunks index.html names are not shipped with ParaView (404s); Workbox
    # would register the service worker. Remove both tags.
    html = re.sub(r'\s*<script src="glance-external-[^"]+"></script>', "", html)
    html = html.replace("</body>", f"  {TAG}\n  </body>")
    with open(idx, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"built {SITE} from {src}")


class Handler(http.server.SimpleHTTPRequestHandler):
    extensions_map = {**http.server.SimpleHTTPRequestHandler.extensions_map, ".js": "text/javascript",
                      ".vtp": "application/octet-stream", ".vti": "application/octet-stream"}

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, fmt, *args):
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--paraview")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--build-only", action="store_true")
    a = ap.parse_args()
    build(a.paraview)
    if a.build_only:
        return
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", a.port), functools.partial(Handler, directory=SITE))
    print(f"serving http://127.0.0.1:{a.port}/?name=disk_out_ref.vtp&url=data/disk_out_ref.vtp")
    srv.serve_forever()


if __name__ == "__main__":
    main()
