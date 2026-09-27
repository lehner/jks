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
# Data flows: a DAG of database states, one node per jks_* step, stored as a
# bash script that replays the flow without jks_gui.  No GUI dependencies.
#
# File format (one "#@jks {json}" line and one command per node, in an order
# where every node comes after the nodes it reads):
#
#   #@jks {"id": "raw"}
#   jks_source raw ../data/C_sp.jks
#   #@jks {"id": "grid", "label": "omega grid"}
#   jks_step grid raw jks_add @ omega0 "np.linspace(0.23, 1.2, 60)"
#   #@jks {"id": "sub"}
#   jks_step sub - jks_take @ @grid "C*"
#
# In a step, "@" is the node's own database and "@id" the database of node id.
# The second word after jks_step is the node the database is copied from before
# the script runs ("-": the script writes it from scratch).  Other comment lines
# are kept with the node that follows them.  Paths are relative to the flow file.
#
# Storage (<flow>.work/): store/<key>.jks holds a full database, or
# store/<key>.delta.jks only the tags that differ from the node's parent; every
# delta is checked to reconstruct the script's output exactly before it is kept.
# Keys hash the script file, argv, env, the keys of the nodes read and the
# content of external databases (size/mtime of glob-matched files).
#
import asyncio, datetime, glob, hashlib, json, os, pickle, re, shlex, shutil, time
import lz4.frame
import numpy as np
import jks
from jks.gui import registry, runner

FORMAT = "jks-flow 1"
ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
REF = re.compile(r"^@([A-Za-z0-9_][A-Za-z0-9_.-]*)?$")
CHECKPOINT = 8  # a full copy after this many deltas in a row

HEADER = """#!/usr/bin/env bash
# %s
#
# Data flow of jks_* steps (designed with jks_gui).  "jks_flow run %s" runs it
# incrementally with a cache; "bash %s" replays every step (JKS_FLOW_WORK sets
# the directory of the replayed databases).  One "#@jks {json}" line and one
# command per node; "@" is the node's database, "@id" the one of node id.
#
set -euo pipefail
cd "$(dirname "$0")"
W="${JKS_FLOW_WORK:-%s}/files"
mkdir -p "$W"
# results must not depend on the caller's environment (steps set their own variables)
for v in $(compgen -e); do case $v in JKS_*|%s) unset "$v" ;; esac; done
jks_source() { rm -f "$W/$1.jks"; ln -s "$(cd "$(dirname "$2")" && pwd)/$(basename "$2")" "$W/$1.jks"; }
jks_step() {
  local id=$1 parent=$2 script=$3 a
  shift 3
  local args=()
  for a in "$@"; do
    if [[ $a == @ ]]; then args+=("$W/$id.jks")
    elif [[ $a =~ ^@[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]]; then args+=("$W/${a#@}.jks")
    else args+=("$a"); fi
  done
  rm -f "$W/$id.jks"
  if [[ $parent != - ]]; then cp "$W/$parent.jks" "$W/$id.jks"; fi
  "$script" "${args[@]}"
}
"""


class FlowError(Exception):
    pass


class node:
    def __init__(self, id, parent=None, name=None, argv=(), env=None, source=None, meta=None, notes=()):
        # a source node has source (a path) and nothing else
        self.id, self.parent, self.name = id, parent, name
        self.argv, self.env = list(argv), dict(env or {})
        self.source = source
        self.meta = dict(meta or {})
        self.meta["id"] = id
        self.notes = list(notes)

    def is_source(self):
        return self.source is not None

    def spec(self):
        return registry.BY_NAME[self.name]

    def values(self):
        return self.spec().parse(self.argv)

    def refs(self):
        # nodes whose databases the step reads through @id
        out = []
        for a in self.argv:
            m = REF.match(a)
            if m and m.group(1) and m.group(1) not in out:
                out.append(m.group(1))
        return out

    def inputs(self):
        # all nodes this node depends on
        return ([self.parent] if self.parent else []) + [r for r in self.refs() if r != self.parent]

    def command(self):
        if self.is_source():
            return "jks_source %s %s" % (self.id, registry.quote(self.source))
        words = ["%s=%s" % (k, registry.quote(v)) for k, v in sorted(self.env.items())]
        words += ["jks_step", self.id, self.parent or "-", self.name] + [registry.quote(a) for a in self.argv]
        return " ".join(words)

    def definition(self):
        return {"source": self.source} if self.is_source() else \
            {"name": self.name, "parent": self.parent, "argv": self.argv, "env": self.env}


class flow:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.base = os.path.dirname(self.path)
        self.nodes = {}  # id -> node, in file order

    # ---- file format ----
    @staticmethod
    def load(path):
        f = flow(path)
        with open(path) as fh:
            lines = fh.read().split("\n")
        meta, notes, i, header = None, [], 0, True
        while i < len(lines):
            line, no = lines[i], i + 1
            i += 1
            s = line.strip()
            if s.startswith("#@jks"):
                try:
                    meta = json.loads(s[5:])
                    assert isinstance(meta, dict) and "id" in meta
                except (ValueError, AssertionError):
                    raise FlowError("%s:%d: #@jks needs a JSON object with an id" % (path, no))
                header = False
                continue
            if meta is None:
                if header or s == "":
                    continue
                if s.startswith("#"):
                    notes.append(line)
                    continue
                raise FlowError("%s:%d: command without a #@jks line before it" % (path, no))
            # the command, with backslash continuations
            cmd = line
            while cmd.endswith("\\") and i < len(lines):
                cmd = cmd[:-1] + " " + lines[i].strip()
                i += 1
            f.add(f.parse_command(cmd, meta, notes, "%s:%d" % (path, no)))
            meta, notes = None, []
        if meta is not None:
            raise FlowError("%s: #@jks line %s without a command" % (path, meta.get("id")))
        return f

    def parse_command(self, cmd, meta, notes, where):
        try:
            words = shlex.split(cmd)
        except ValueError as e:
            raise FlowError("%s: %s" % (where, e))
        env = {}
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            k, v = words.pop(0).split("=", 1)
            env[k] = v
        if len(words) == 3 and words[0] == "jks_source" and not env:
            n = node(words[1], source=words[2], meta=meta, notes=notes)
        elif len(words) >= 4 and words[0] == "jks_step":
            n = node(words[1], None if words[2] == "-" else words[2], words[3], words[4:], env, meta=meta, notes=notes)
        else:
            raise FlowError("%s: expected jks_source id path or jks_step id parent script ..." % where)
        if n.id != meta["id"]:
            raise FlowError("%s: the command is for %s but #@jks names %s" % (where, n.id, meta["id"]))
        return n

    def text(self):
        name = os.path.basename(self.path)
        work = os.path.splitext(name)[0] + ".work"
        extra = "|".join(v for v in registry.ENV_ALL if not v.startswith("JKS_"))
        out = [HEADER % (FORMAT, name, name, work, extra)]
        for n in self.nodes.values():
            out += n.notes
            out.append("#@jks " + json.dumps(n.meta, sort_keys=True))
            out.append(n.command())
        return "\n".join(out) + "\n"

    def save(self, path=None):
        path = os.path.abspath(path or self.path)
        tmp = path + ".tmp%d" % os.getpid()
        with open(tmp, "w") as fh:
            fh.write(self.text())
        os.chmod(tmp, 0o755)
        os.replace(tmp, path)

    # ---- editing ----
    def check(self, n, before):
        # before: ids that may be read
        if not ID.match(n.id) or n.id in ("-",):
            raise FlowError("invalid node id %r" % n.id)
        if n.is_source():
            return
        if n.name not in registry.BY_NAME:
            raise FlowError("%s: %s is not a known jks script" % (n.id, n.name))
        spec = n.spec()
        try:
            v = spec.parse(n.argv)
        except ValueError as e:
            raise FlowError("%s: %s" % (n.id, e))
        if spec.get_primary(v) != "@":
            raise FlowError("%s: the database %s writes must be @" % (n.id, n.name))
        kind = spec.primary_kind()
        if kind == "db" and n.parent is None:
            raise FlowError("%s: %s modifies a database; give the node it starts from" % (n.id, n.name))
        if kind == "db_new" and n.parent is not None:
            raise FlowError("%s: %s writes a new database; its parent must be -" % (n.id, n.name))
        for r in n.inputs():
            if r not in before:
                raise FlowError("%s: reads %s, which is not defined before it" % (n.id, r))
        for a, x, _ in spec.items(v):
            if REF.match(x) and x != "@" and a.kind not in ("db_in",):
                raise FlowError("%s: %s can only be used for an input database" % (n.id, x))

    def add(self, n, after=None):
        if n.id in self.nodes:
            raise FlowError("node %s exists already" % n.id)
        self.check(n, set(self.nodes))
        self.nodes[n.id] = n

    def replace(self, n):
        # new definition of an existing node, same position
        if n.id not in self.nodes:
            raise FlowError("no node %s" % n.id)
        ids = list(self.nodes)
        self.check(n, set(ids[: ids.index(n.id)]))
        self.nodes[n.id] = n

    def remove(self, id):
        users = [n.id for n in self.nodes.values() if id in n.inputs()]
        if users:
            raise FlowError("%s is read by %s" % (id, ", ".join(users)))
        del self.nodes[id]

    def children(self, id):
        return [n.id for n in self.nodes.values() if id in n.inputs()]

    def ancestors(self, ids):
        out, todo = set(), list(ids)
        while todo:
            i = todo.pop()
            if i not in out:
                out.add(i)
                todo += self.nodes[i].inputs()
        return out

    def descendants(self, id):
        out, todo = set(), [id]
        while todo:
            i = todo.pop()
            for c in self.children(i):
                if c not in out:
                    out.add(c)
                    todo.append(c)
        return out


# ---- database files without resamples.save (no os.getlogin, keeps origin) ----
def _write(res, path, origin=None):
    s = {"N": res.N, "set": {}, "_clone_type_str": res._clone_type_str, "tags": res.tags,
         "info": res.info, "origin": origin if origin is not None else (res.origin or {})}
    for t in res.set:
        s["set"][t] = {"orig": res.set[t].orig, "blocks": res.set[t].blocks, "N": res.set[t].N}
    tmp = path + ".part"
    with lz4.frame.open(tmp, mode="wb") as f:
        pickle.dump(s, f, pickle.HIGHEST_PROTOCOL)
    os.replace(tmp, path)


def _empty(like, tags, info, origin):
    res = jks.resamples()
    res.N, res.tags, res.info, res.origin = len(tags), list(tags), info, origin
    res._clone_type_str = like._clone_type_str
    return res


def _same_array(a, b):
    a, b = np.asarray(a), np.asarray(b)
    return a.shape == b.shape and a.dtype == b.dtype and np.array_equal(a, b, equal_nan=a.dtype.kind in "fc")


def _same(a, b):
    if list(a.keys()) != list(b.keys()) or list(a.tags) != list(b.tags) or a.info != b.info:
        return False
    return all(_same_array(a.set[t].orig, b.set[t].orig) and _same_array(a.set[t].blocks, b.set[t].blocks)
               for t in a.keys())


def make_delta(parent, child):
    # tags of child that differ from parent (blocks compared by block tag)
    changed = []
    for t in child.keys():
        if t not in parent.set:
            changed.append(t)
            continue
        a, b = parent.set[t], child.set[t]
        try:
            same = _same_array(a.orig, b.orig) and _same_array(runner._aligned(a, child.tags), b.blocks)
        except (ValueError, TypeError):
            same = False
        if not same:
            changed.append(t)
    d = _empty(child, child.tags, child.info, child.origin)
    for t in changed:
        d.set[t] = child.set[t]
    meta = {"order": list(child.keys()), "tags": list(child.tags), "info": child.info}
    return d, meta


def apply_delta(parent, d, meta):
    out = _empty(d, meta["tags"], meta["info"], d.origin)
    fnc = out._clone_type_fnc()
    for t in meta["order"]:
        j = d.set.get(t)
        if j is not None:
            out.set[t] = fnc(j.orig, j.blocks, out.tags, out.info)
        else:
            j = parent.set[t]
            out.set[t] = fnc(j.orig, runner._aligned(j, out.tags), out.tags, out.info)
    return out


class engine:
    def __init__(self, fl, work=None):
        self.flow = fl
        name = os.path.splitext(os.path.basename(fl.path))[0]
        self.work = os.path.abspath(work or os.environ.get("JKS_FLOW_WORK") or os.path.join(fl.base, name + ".work"))
        self.store = os.path.join(self.work, "store")
        self._memo = []  # (key, resamples), most recent last
        self._hashes = self._read_json("hashes.json")

    # ---- small helpers ----
    def _read_json(self, name, default=None):
        try:
            with open(os.path.join(self.work, name)) as f:
                return json.load(f)
        except (OSError, ValueError):
            return {} if default is None else default

    def _write_json(self, name, data):
        os.makedirs(self.work, exist_ok=True)
        p = os.path.join(self.work, name)
        with open(p + ".tmp%d" % os.getpid(), "w") as f:
            json.dump(data, f, indent=1, sort_keys=True)
        os.replace(p + ".tmp%d" % os.getpid(), p)

    def path(self, p):
        return os.path.normpath(os.path.join(self.flow.base, os.path.expanduser(p)))

    def file_hash(self, p):
        # content hash, remembered across runs by stat
        st = os.stat(p)
        k = "%s|%d|%d|%d" % (os.path.abspath(p), st.st_ino, st.st_size, st.st_mtime_ns)
        if k not in self._hashes:
            self._hashes[k] = runner.file_hash(p)
            self._write_json("hashes.json", self._hashes)
        return self._hashes[k]

    # ---- keys and status ----
    def keys(self):
        # node id -> key, None where an input is missing
        keys = {}
        for n in self.flow.nodes.values():
            try:
                keys[n.id] = self.key(n, keys)
            except (OSError, FlowError):
                keys[n.id] = None
        return keys

    def key(self, n, keys):
        if n.is_source():
            return "s" + self.file_hash(self.path(n.source))[:31]
        if any(keys.get(r) is None for r in n.inputs()):
            raise FlowError("input missing")
        spec, v = n.spec(), n.values()
        ext = {}
        for a, x, _ in spec.items(v):
            if a.kind == "db_in" and not REF.match(x):
                ext[x] = self.file_hash(self.path(x))
            elif a.kind == "glob":
                ext[x] = [[os.path.relpath(f, self.flow.base), os.stat(f).st_size, os.stat(f).st_mtime_ns]
                          for f in sorted(glob.glob(self.path(x)))]
        d = {"script": runner.file_hash(registry.script_path(n.name)), "def": n.definition(),
             "inputs": dict((r, keys[r]) for r in n.inputs()), "external": ext}
        return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:32]

    def meta(self, key):
        try:
            with open(os.path.join(self.store, key + ".json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def have(self, key):
        if key is None:
            return False
        if key[0] == "s":
            return True
        m = self.meta(key)
        return m is not None and os.path.exists(os.path.join(self.store, m["file"]))

    def status(self):
        # per node: ok, stale (an older result exists), new, failed, missing (input file)
        keys, state = self.keys(), self._read_json("state.json")
        out = []
        for n in self.flow.nodes.values():
            k = keys[n.id]
            built = state.get("built", {}).get(n.id)
            failed = state.get("failed", {}).get(n.id, {})
            r = {"id": n.id, "key": k, "built": built, "reason": ""}
            if k is None:
                r["status"] = "missing"
                r["reason"] = "input file not found" if n.is_source() or not any(
                    keys.get(i) is None for i in n.inputs()) else "input missing"
            elif self.have(k):
                r["status"] = "ok"
            elif failed.get("key") == k:
                r["status"], r["reason"] = "failed", failed.get("error", "")
            elif built and self.have(built):
                bm = self.meta(built)
                r["status"] = "stale"
                r["reason"] = "definition changed" if bm and bm.get("def") != n.definition() else "input changed"
            else:
                r["status"] = "new"
            out.append(r)
        return out

    # ---- databases of nodes ----
    def load(self, key):
        # resamples of a stored node (reconstructed from deltas)
        for k, r in self._memo:
            if k == key:
                return r
        if key[0] == "s":
            raise FlowError("sources are read from their file")
        m = self.meta(key)
        if m is None:
            raise FlowError("no stored result for %s" % key)
        p = os.path.join(self.store, m["file"])
        if m["stored"] == "full":
            r = jks.resamples(p)
        else:
            r = apply_delta(self.load(m["base"]), jks.resamples(p), m["delta"])
        self._remember(key, r)
        return r

    def _remember(self, key, r):
        self._memo = [(k, x) for k, x in self._memo if k != key][-1:] + [(key, r)]

    def file_of(self, n, key, tmp):
        # a readable database file of node n (the source itself, a full file of the store,
        # or a reconstruction in tmp)
        if n.is_source():
            return self.path(n.source)
        m = self.meta(key)
        if m["stored"] == "full":
            return os.path.join(self.store, m["file"])
        p = os.path.join(tmp, "in-%s.jks" % n.id)
        _write(self.load(key), p)
        return p

    def export(self, id, target):
        keys = self.keys()
        k = keys.get(id)
        if not self.have(k):
            raise FlowError("%s is not computed; run it first" % id)
        n = self.flow.nodes[id]
        if n.is_source():
            shutil.copyfile(self.path(n.source), target)
        else:
            _write(self.load(k), target)

    def depth(self, key):
        # deltas in a row down to the next full copy
        d = 0
        while key and key[0] != "s":
            m = self.meta(key)
            if m is None or m["stored"] == "full":
                break
            d, key = d + 1, m["base"]
        return d

    # ---- running ----
    async def run(self, targets=None, jobs=1, log=lambda id, line: None, force=False, procs=None):
        # compute targets (default: all nodes) and what they need; returns id -> result
        keys = self.keys()
        want = self.flow.ancestors(targets) if targets else set(self.flow.nodes)
        for i in want:
            if keys[i] is None:
                raise FlowError("%s: an input is missing (%s)" % (i, next((r["reason"] for r in self.status() if r["id"] == i), "")))
        todo = [i for i in self.flow.nodes if i in want and (not self.have(keys[i]) or (force and targets and i in targets))]
        os.makedirs(self.store, exist_ok=True)
        sem = asyncio.Semaphore(jobs)
        loop = asyncio.get_running_loop()
        done = dict((i, loop.create_future()) for i in todo)
        results = {}

        async def one(i):
            n = self.flow.nodes[i]
            for r in n.inputs():
                if r in done and not await done[r]:
                    results[i] = {"ok": False, "error": "input %s failed" % r}
                    done[i].set_result(False)
                    return
            async with sem:
                res = await self.build(n, keys, lambda line: log(i, line), procs)
            results[i] = res
            done[i].set_result(res["ok"])

        await asyncio.gather(*[one(i) for i in todo])
        return results

    async def build(self, n, keys, log, procs):
        key = keys[n.id]
        tmp = os.path.join(self.work, "tmp", "%s-%d" % (key, os.getpid()))
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        t0 = time.time()
        res = {"ok": False, "error": None, "key": key, "id": n.id}
        try:
            out = os.path.join(tmp, n.id + ".jks")
            parent = self.flow.nodes[n.parent] if n.parent else None
            if parent is not None:
                pm = None if parent.is_source() else self.meta(keys[parent.id])
                if pm is not None and pm["stored"] == "delta":
                    _write(self.load(keys[parent.id]), out)
                else:
                    runner.clone(self.file_of(parent, keys[parent.id], tmp), out)
            argv = []
            for a in n.argv:
                m = REF.match(a)
                if a == "@":
                    argv.append(out)
                elif m and m.group(1):
                    argv.append(self.file_of(self.flow.nodes[m.group(1)], keys[m.group(1)], tmp))
                else:
                    argv.append(a)
            before = runner.file_hash(out) if os.path.exists(out) else None
            rc, lines = await runner.execute(n.name, argv, n.env, self.flow.base, log, procs)
            res["log"] = "\n".join(lines)
            if rc != 0:
                raise FlowError("%s failed (exit code %d)" % (n.name, rc))
            if not os.path.exists(out) or runner.file_hash(out) == before:
                raise FlowError("%s wrote no database (did it print its usage?)" % n.name)
            res.update(self.keep(n, key, keys, out, res["log"]))
            res["ok"] = True
        except Exception as e:
            res["error"] = str(e) if isinstance(e, FlowError) else "%s: %s" % (type(e).__name__, e)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        res["seconds"] = round(time.time() - t0, 3)
        state = self._read_json("state.json")
        state.setdefault("built", {})
        state.setdefault("failed", {})
        if res["ok"]:
            state["built"][n.id] = key
            state["failed"].pop(n.id, None)
        else:
            state["failed"][n.id] = {"key": key, "error": res["error"],
                                     "log": "\n".join(res.get("log", "").splitlines()[-200:])}
        self._write_json("state.json", state)
        return res

    def keep(self, n, key, keys, out, log):
        # store out as a delta to the parent if that reproduces it exactly, else in full
        child = jks.resamples(out)
        m = {"key": key, "id": n.id, "command": n.command(), "def": n.definition(),
             "created": str(datetime.datetime.now()), "inputs": dict((r, keys[r]) for r in n.inputs()),
             "log": log}
        base = keys[n.parent] if n.parent else None
        stored = "full"
        if base is not None and base[0] != "s" and self.depth(base) + 1 < CHECKPOINT:
            parent = self.load(base)
            d, dm = make_delta(parent, child)
            if len(d.set) < 0.5 * max(len(child.set), 1) and _same(apply_delta(parent, d, dm), child):
                _write(d, os.path.join(self.store, key + ".delta.jks"))
                m.update({"stored": "delta", "file": key + ".delta.jks", "base": base, "delta": dm,
                          "changed": list(d.set)})
                stored = "delta"
        if stored == "full":
            os.replace(out, os.path.join(self.store, key + ".jks"))
            m.update({"stored": "full", "file": key + ".jks"})
        m["bytes"] = os.path.getsize(os.path.join(self.store, m["file"]))
        with open(os.path.join(self.store, key + ".json"), "w") as f:
            json.dump(m, f, indent=1)
        self._remember(key, child)
        return {"stored": stored, "bytes": m["bytes"]}

    def gc(self, dry=False):
        # remove stored results no current or last built node needs
        keys, state = self.keys(), self._read_json("state.json")
        keep, todo = set(), [k for k in list(keys.values()) + list(state.get("built", {}).values()) if k]
        while todo:
            k = todo.pop()
            if k in keep:
                continue
            keep.add(k)
            m = self.meta(k)
            if m and m.get("stored") == "delta":
                todo.append(m["base"])
        removed = 0
        for p in glob.glob(os.path.join(self.store, "*.json")):
            k = os.path.basename(p)[:-5]
            if k not in keep:
                m = self.meta(k)
                for f in [p] + ([os.path.join(self.store, m["file"])] if m else []):
                    if os.path.exists(f):
                        removed += os.path.getsize(f)
                        if not dry:
                            os.remove(f)
        return removed
