#
#    JKS - Measurement database system
#    Copyright (C) 2026  Christoph Lehner (christoph.lehner@ur.de, https://github.com/lehner/jks)
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License along
#    with this program; if not, write to the Free Software Foundation, Inc.,
#    51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.
#
# Read-only view of a database file, shared between browser sessions.
#
import os, threading, time
import numpy as np
import jks
from jks.gui.stats import tag_stats

_cache = {}
_lock = threading.Lock()


class database:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        st = os.stat(self.path)
        self.stamp = (st.st_mtime_ns, st.st_size)
        t0 = time.time()
        self.res = jks.resamples(self.path)
        self.load_time = time.time() - t0
        self.origin = self.res.origin or {}
        self.tags = self.res.tags or []
        self.configs = [t for t in self.tags if t[0] != "!"]
        self.variations = [t[1:] for t in self.tags if t[0] == "!"]
        self.info = self.res.info or {}
        self._rows = None

    def changed_on_disk(self):
        try:
            st = os.stat(self.path)
        except FileNotFoundError:
            return True
        return (st.st_mtime_ns, st.st_size) != self.stamp

    def keys(self):
        return list(self.res.keys())

    def stats(self, tag, convention="info"):
        jk = self.res.get(tag)
        return tag_stats(jk.orig, jk.blocks, self.tags, convention)

    def rows(self):
        # one summary row per tag for the tag table
        if self._rows is None:
            rows = []
            for tag in self.keys():
                try:
                    s = self.stats(tag)
                    m, e = s.mean, s.tot_err()
                    with np.errstate(divide="ignore", invalid="ignore"):
                        rel = np.where(m != 0.0, e / np.abs(m), np.nan)
                    rel = np.nanmax(rel) if np.any(np.isfinite(rel)) else float("nan")
                    shape = "x".join(str(x) for x in s.shape) if s.shape else "scalar"
                    rows.append(
                        {
                            "tag": tag,
                            "shape": shape,
                            "n": len(m),
                            "vars": ", ".join(s.vars()),
                            "relerr": "" if not np.isfinite(rel) else "%.2e" % rel,
                        }
                    )
                except Exception as e:
                    # non-numeric payload: list it, but do not analyze it
                    rows.append(
                        {"tag": tag, "shape": "?", "n": 0, "vars": "", "relerr": str(e)[:40]}
                    )
            self._rows = rows
        return self._rows


def load(path, force=False):
    # cached by path; reloaded when the file changed on disk or force is set
    path = os.path.abspath(path)
    with _lock:
        db = _cache.get(path)
    if db is not None and not force and not db.changed_on_disk():
        return db
    db = database(path)
    db.rows()
    with _lock:
        _cache[path] = db
    return db
