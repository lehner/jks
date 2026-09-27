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
# Run one jks_* step on a copy, cache the result by content hash, diff and commit.
# No GUI dependencies.
#
# Work directory layout (default: .jks_work next to the database):
#   nodes/<key>.jks, nodes/<key>.json   results and their metadata
#   tmp/                                runs in progress
#   backup/                             databases replaced by a commit (hard links)
#   history.sh                          committed steps as shell commands
#
# The key hashes the script file, the argv with the written database replaced by
# a placeholder, the environment of the step, the content of every database read
# and the size/mtime of every file matched by a glob argument.
#
import asyncio, datetime, glob, hashlib, json, os, shlex, shutil, subprocess, sys, time
import numpy as np
import jks
from jks.flow import registry

_hashes = {}


def file_hash(path):
    # sha256 of the content, cached by stat
    st = os.stat(path)
    k = (os.path.abspath(path), st.st_ino, st.st_size, st.st_mtime_ns)
    if k not in _hashes:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for b in iter(lambda: f.read(1 << 22), b""):
                h.update(b)
        _hashes[k] = h.hexdigest()
    return _hashes[k]


def clone(src, dst):
    # copy-on-write copy where the filesystem supports it
    cmd = ["cp", "-c", src, dst] if sys.platform == "darwin" else ["cp", "--reflink=auto", src, dst]
    if subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode != 0:
        shutil.copyfile(src, dst)


def clean_env(env):
    # the step's own variables only; stray JKS_* settings must not change results
    e = dict((k, v) for k, v in os.environ.items()
             if not k.startswith("JKS_") and k not in registry.ENV_ALL)
    root = os.path.dirname(os.path.dirname(os.path.abspath(jks.__file__)))
    e["PYTHONPATH"] = root + (os.pathsep + e["PYTHONPATH"] if e.get("PYTHONPATH") else "")
    e["PYTHONUNBUFFERED"] = "1"
    e.update(env)
    return e


async def execute(name, argv, env, cwd, log=lambda line: None, procs=None):
    # run a jks script with the step's environment -> (exit code, output lines)
    cmd = [sys.executable, registry.script_path(name)] + list(argv)
    lines = []
    proc = await asyncio.create_subprocess_exec(*cmd, cwd=cwd, env=clean_env(env),
                                                stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.STDOUT)
    if procs is not None:
        procs.append(proc)
    try:
        while True:
            b = await proc.stdout.readline()
            if not b:
                break
            line = b.decode(errors="replace").rstrip("\n")
            lines.append(line)
            log(line)
        rc = await proc.wait()
    finally:
        if procs is not None and proc in procs:
            procs.remove(proc)
    return rc, lines


class step:
    def __init__(self, name, argv, env=None, base=None):
        self.name, self.argv, self.env = name, list(argv), dict(env or {})
        self.base = os.path.abspath(base or os.getcwd())
        self.spec = registry.BY_NAME[name]
        self.values = self.spec.parse(self.argv)

    @staticmethod
    def from_command(line, base=None):
        env, name, argv = registry.split_command(line)
        return step(name, argv, env, base)

    def command(self):
        return registry.join_command(self.env, self.name, self.argv)

    def path(self, p):
        return os.path.normpath(os.path.join(self.base, os.path.expanduser(p)))

    def primary(self):
        return self.path(self.spec.get_primary(self.values))

    def parent(self):
        # database copied before the run (None: the script starts from scratch)
        k, p = self.spec.primary_kind(), self.primary()
        if k == "db" or (k == "db_maybe" and os.path.exists(p)):
            return p
        return None

    def reference(self):
        # database the result is compared with
        p = self.parent()
        if p is None:
            ins = self.spec.databases_in(self.values)
            p = self.path(ins[0]) if ins else None
        return p

    def inputs(self):
        d = {"script": file_hash(registry.script_path(self.name))}
        if self.parent() is not None:
            d["parent"] = file_hash(self.parent())
        d["db_in"] = [file_hash(self.path(p)) for p in self.spec.databases_in(self.values)]
        files = []
        for g in self.spec.globs(self.values):
            for f in sorted(glob.glob(self.path(g))):
                st = os.stat(f)
                files.append([os.path.relpath(f, self.base), st.st_size, st.st_mtime_ns])
        d["files"] = files
        return d

    def key(self, inputs=None):
        argv = self.spec.build(self.spec.set_primary(self.values, "@OUT"))
        k = {"name": self.name, "argv": argv, "env": self.env, "inputs": inputs or self.inputs()}
        return hashlib.sha256(json.dumps(k, sort_keys=True).encode()).hexdigest()[:32]

    def check(self, db=None):
        # problems visible before running: missing inputs, existing output tags
        msgs = []
        k = self.spec.primary_kind()
        if k == "db" and not os.path.isfile(self.primary()):
            msgs.append("database %s does not exist" % self.primary())
        for p in self.spec.databases_in(self.values):
            if not os.path.isfile(self.path(p)):
                msgs.append("input database %s does not exist" % p)
        for g in self.spec.globs(self.values):
            if not glob.glob(self.path(g)):
                msgs.append("no file matches %s" % g)
        if db is not None and k in ("db", "db_maybe"):
            have = set(db.keys())
            out = [t for t in self.spec.tags_out(self.values) if "*" not in t]
            for t in out:
                if t in have:
                    msgs.append("tag %s exists already" % t)
            for t in self.spec.tags_in(self.values):
                if t not in have and t not in out:
                    msgs.append("tag %s not found" % t)
        return msgs


class work:
    def __init__(self, root):
        self.root = os.path.abspath(root)

    def dir(self, *p):
        d = os.path.join(self.root, *p)
        os.makedirs(d, exist_ok=True)
        return d

    def node(self, key):
        return os.path.join(self.root, "nodes", key + ".jks")

    def meta(self, key):
        p = os.path.join(self.root, "nodes", key + ".json")
        if os.path.isfile(p) and os.path.isfile(self.node(key)):
            with open(p) as f:
                return json.load(f)
        return None

    async def run(self, st, log=lambda line: None, procs=None):
        # returns the metadata of the result; log receives the output line by line
        inputs = st.inputs()
        key = st.key(inputs)
        m = self.meta(key)
        if m is not None and m["ok"]:
            log("(cached result of %s)" % m["created"])
            for line in m["log"].splitlines():
                log(line)
            m["cached"] = True
            return m
        tmp = os.path.join(self.dir("tmp"), "%s-%d" % (key, os.getpid()))
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        out = os.path.join(tmp, os.path.basename(st.primary()))
        if st.parent() is not None:
            clone(st.parent(), out)
        before = file_hash(out) if os.path.exists(out) else None
        argv = st.spec.build(st.spec.set_primary(st.values, out))
        t0 = time.time()
        rc, lines = await execute(st.name, argv, st.env, st.base, log, procs)
        m = {"key": key, "name": st.name, "argv": st.argv, "env": st.env, "base": st.base,
             "command": st.command(), "inputs": inputs, "returncode": rc,
             "seconds": round(time.time() - t0, 3), "created": str(datetime.datetime.now()),
             "log": "\n".join(lines), "cached": False, "ok": False, "error": None,
             "parent": st.parent(), "reference": st.reference(), "primary": st.primary(),
             "kind": st.spec.primary_kind()}
        if rc != 0:
            m["error"] = "%s failed (exit code %d)" % (st.name, rc)
        elif not os.path.exists(out):
            m["error"] = "%s wrote no database (did it print its usage?)" % st.name
        elif before is not None and file_hash(out) == before:
            m["error"] = "%s left the database unchanged (did it print its usage?)" % st.name
        else:
            try:
                jks.resamples(out)
            except Exception as e:
                m["error"] = "result is not readable: %s" % e
        if m["error"] is None:
            os.replace(out, os.path.join(self.dir("nodes"), key + ".jks"))
            m["ok"] = True
            with open(os.path.join(self.dir("nodes"), key + ".json"), "w") as f:
                json.dump(m, f, indent=1)
        shutil.rmtree(tmp, ignore_errors=True)
        return m

    def commit(self, m, target=None, overwrite=False):
        # inplace steps replace their database, others are saved to target
        src = self.node(m["key"])
        if m["kind"] in ("db", "db_maybe") and target is None:
            target = m["primary"]
            if m["parent"] is not None:
                if file_hash(target) != m["inputs"]["parent"]:
                    raise RuntimeError("%s changed since the preview; run the step again" % target)
                stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
                bk = os.path.join(self.dir("backup"), "%s.%s.%s" % (os.path.basename(target), stamp, m["key"][:8]))
                try:
                    os.link(target, bk)
                except OSError:
                    clone(target, bk)
            elif os.path.exists(target):
                raise RuntimeError("%s appeared since the preview; run the step again" % target)
        else:
            target = os.path.abspath(os.path.join(m["base"], os.path.expanduser(target or m["primary"])))
            if os.path.exists(target) and not overwrite:
                raise FileExistsError("%s exists" % target)
        part = target + ".jks_gui_part"
        clone(src, part)
        os.replace(part, target)
        with open(os.path.join(self.root, "history.sh"), "a") as f:
            f.write("# %s  %s\n" % (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), m["key"]))
            argv = list(m["argv"])
            if os.path.abspath(target) != m["primary"]:
                st = step(m["name"], argv, m["env"], m["base"])
                argv = st.spec.build(st.spec.set_primary(st.values, os.path.relpath(target, m["base"])))
            f.write("(cd %s && %s)\n" % (shlex.quote(m["base"]), registry.join_command(m["env"], m["name"], argv)))
        return target


def _aligned(jk, tags):
    # blocks of jk in the block order `tags`; missing blocks equal the mean (as expand)
    idx = dict((t, i) for i, t in enumerate(jk.tags))
    b = np.asarray(jk.blocks)
    o = np.asarray(jk.orig)
    return np.array([b[idx[t]] if t in idx else o for t in tags])


def diff(ref, res):
    # ref, res: jks.resamples (ref may be None) -> summary of what changed
    rk = set(ref.keys()) if ref is not None else set()
    nk = set(res.keys())
    d = {"added": sorted(nk - rk), "removed": sorted(rk - nk), "modified": []}
    for t in sorted(nk & rk):
        a, b = ref.get(t), res.get(t)
        try:
            same = np.array_equal(np.asarray(a.orig), np.asarray(b.orig), equal_nan=True) and \
                np.array_equal(_aligned(a, res.tags), np.asarray(b.blocks), equal_nan=True)
        except (TypeError, ValueError):
            same = False
        if not same:
            d["modified"].append(t)
    ot = ref.tags if ref is not None else []
    oc, nc = [t for t in ot if t[0] != "!"], [t for t in res.tags if t[0] != "!"]
    ov, nv = [t[1:] for t in ot if t[0] == "!"], [t[1:] for t in res.tags if t[0] == "!"]
    d["configs_added"] = [c for c in nc if c not in set(oc)] if ref is not None else []
    d["configs_removed"] = [c for c in oc if c not in set(nc)]
    d["variations_added"] = [v for v in nv if v not in set(ov)]
    d["variations_removed"] = [v for v in ov if v not in set(nv)]
    bad = []
    for t in d["added"] + d["modified"]:
        try:
            if not np.all(np.isfinite(np.asarray(res.get(t).blocks, dtype=np.float64))) or \
                    not np.all(np.isfinite(np.asarray(res.get(t).orig, dtype=np.float64))):
                bad.append(t)
        except (TypeError, ValueError):
            pass
    d["nonfinite"] = bad
    return d


def find_fit(w, fit):
    # most recent cached jks_fit/jks_slow_fit step writing the tag fit -> {data tag: function}, ranges, env
    best = None
    for p in glob.glob(os.path.join(w.root, "nodes", "*.json")):
        try:
            with open(p) as f:
                m = json.load(f)
        except (OSError, ValueError):
            continue
        if m.get("name") not in ("jks_fit", "jks_slow_fit") or not m.get("ok"):
            continue
        spec = registry.BY_NAME[m["name"]]
        v = spec.parse(m["argv"])
        if v["tail"][1] == fit and (best is None or m["created"] > best[0]["created"]):
            best = (m, v)
    if best is None:
        return None
    m, v = best
    return {"functions": dict((r[0], r[2]) for r in v["repeat"]), "ranges": dict((r[0], r[1]) for r in v["repeat"]),
            "env": m["env"], "command": m["command"]}
