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
# Recently used values of the step panel's fields, kept in a JSON file
# (default ~/.config/jks_gui/history.json).  Keys are "script:argument",
# "env:VARIABLE" and "command"; the newest value comes first.
#
import json, os, threading

_lock = threading.Lock()


def default_path():
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.join(os.path.expanduser("~"), ".config")
    return os.path.join(base, "jks_gui", "history.json")


class history:
    def __init__(self, path=None, n=20):
        self.path = path or default_path()
        self.n = n
        self.data = self.read()

    def read(self):
        try:
            with open(self.path) as f:
                d = json.load(f)
            return dict((k, [x for x in v if isinstance(x, str)]) for k, v in d.items() if isinstance(v, list))
        except (OSError, ValueError, AttributeError):
            return {}

    def get(self, key):
        return list(self.data.get(key, []))

    def add(self, entries):
        # entries: list of (key, value); later entries count as more recent
        with _lock:
            # merge with what other jks_gui processes saved meanwhile
            data = self.read()
            for k, v in self.data.items():
                data.setdefault(k, v)
            for k, v in entries:
                if not v:
                    continue
                old = [x for x in data.get(k, []) if x != v]
                data[k] = ([v] + old)[: self.n]
            self.data = data
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            tmp = self.path + ".%d.tmp" % os.getpid()
            with open(tmp, "w") as f:
                json.dump(data, f, indent=1, sort_keys=True)
            os.replace(tmp, self.path)
