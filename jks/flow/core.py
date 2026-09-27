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
# Data flows: a DAG of database states, one node per jks_* step or loop of
# steps, stored as a bash script that replays the flow without jks_gui.
# No GUI dependencies.
#
# File format (a "#@jks {json}" line before every node; nodes come after the
# nodes they read):
#
#   #@jks {"id": "raw"}
#   jks_source raw ../data/C_sp.jks
#   #@jks {"id": "grid", "label": "omega grid"}
#   jks_step grid raw jks_add @ omega0 "np.linspace(0.23, 1.2, 60)"
#   #@jks {"id": "sub"}
#   jks_step sub - jks_take @ @grid "C*"
#   #@jks {"id": "tags"}
#   jks_list tags C Crec
#   #@jks {"id": "int"}
#   jks_begin int grid
#   for tag in $(jks_list_values tags); do
#     jks_apply int jks_add @ "int.$tag" "[ r['$tag'][t] * t**4 for t in range(40) ]"
#   done
#
# "@" is the node's own database, "@id" the database of node id (input databases
# only).  jks_step copies its parent ("-": the script writes a new database) and
# runs one script.  A loop node copies its parent once (jks_begin) and applies
# the body (jks_apply lines) for every combination of the loop values: literal
# words, $(seq ...), $(jks_values @node tag) (a constant tag, preferably of a side
# node) or $(jks_list_values list).  A loop over rows reads several variables:
#   for row in 'C 14' 'Crec 16'; do
#     read -r tag t0 <<< "$row"
# Loop variables are used as $var or ${var} in double-quoted arguments.  Other
# comment lines stay with the node that follows them.  Paths are relative to the
# flow file.
#
# Loops run their iterations independently on the parent ("map") if each only
# appends tags and none reads what another writes, which gives the same result
# as the sequential bash loop; otherwise one after the other ("sequence").
# Every iteration is cached, so editing one value recomputes one iteration.
#
# Storage (<flow>.work/): store/<key>.jks holds a full database, or
# store/<key>.delta.jks only the tags that differ from the base (the parent, a
# previous iteration, or a snapshot of a source); every delta is checked to
# reconstruct the result exactly before it is kept.  Keys hash the script
# files, the jks library, the definition, the keys of the nodes read and the
# content of external databases (size/mtime of glob-matched files).
#
import asyncio, copy, datetime, fnmatch, glob, hashlib, itertools, json, os, pickle, re, shlex, shutil, \
    subprocess, sys, time
import lz4.frame
import numpy as np
import jks
from jks.flow import registry, runner

FORMAT = "jks-flow 1"
ID = re.compile(r"^[A-Za-z0-9_][A-Za-z0-9_.-]*$")
REF = re.compile(r"^@([A-Za-z0-9_][A-Za-z0-9_.-]*)?$")
VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}|\$([A-Za-z_][A-Za-z0-9_]*)")
CHECKPOINT = 8  # a full copy after this many deltas in a row

HEADER = """#!/usr/bin/env bash
# %s
#
# Data flow of jks_* steps (designed with jks_gui).  "jks_flow run %s" runs it
# incrementally with a cache; "bash %s" replays every step (JKS_FLOW_WORK sets
# the directory of the replayed databases).  A "#@jks {json}" line before every
# node; "@" is the node's database, "@id" the one of node id.
#
set -euo pipefail
cd "$(dirname "$0")"
W="${JKS_FLOW_WORK:-$(basename "$0" .sh).work}/files"
mkdir -p "$W"
# results must not depend on the caller's environment (steps set their own variables)
for v in $(compgen -e); do case $v in JKS_*|%s) unset "$v" ;; esac; done
_jks_map() {
  local id=$1 a
  shift
  _jks_a=()
  for a in "$@"; do
    if [[ $a == @ ]]; then _jks_a+=("$W/$id.jks")
    elif [[ $a =~ ^@[A-Za-z0-9_][A-Za-z0-9_.-]*$ ]]; then _jks_a+=("$W/${a#@}.jks")
    else _jks_a+=("$a"); fi
  done
}
jks_source() { rm -f "$W/$1.jks"; ln -s "$(cd "$(dirname "$2")" && pwd)/$(basename "$2")" "$W/$1.jks"; }
jks_step() {
  local id=$1 parent=$2 script=$3
  shift 3
  _jks_map "$id" "$@"
  rm -f "$W/$id.jks"
  if [[ $parent != - ]]; then cp "$W/$parent.jks" "$W/$id.jks"; fi
  "$script" "${_jks_a[@]}"
}
jks_begin() { rm -f "$W/$1.jks"; cp "$W/$2.jks" "$W/$1.jks"; }
jks_apply() {
  local id=$1 script=$2
  shift 2
  _jks_map "$id" "$@"
  "$script" "${_jks_a[@]}"
}
jks_list() { local n=$1; shift; printf '%%s\\n' "$@" > "$W/$n.list"; }
jks_list_values() { cat "$W/$1.list" || kill $$; }
jks_values() {
  local out
  out=$(command jks_values "$W/${1#@}.jks" "$2") || { printf '%%s\\n' "$out" >&2; kill $$; }
  printf '%%s\\n' "$out"
}
"""


class FlowError(Exception):
    pass


class NotReady(Exception):
    # a loop whose values come from a node that is not computed yet
    pass


_code = None


def code_hash():
    # the jks library (not jks.flow or jks.gui): a changed solver invalidates results like a changed script
    global _code
    if _code is None:
        root = os.path.dirname(os.path.abspath(jks.__file__))
        h = hashlib.sha256()
        for p in sorted(glob.glob(os.path.join(root, "*.py"))):
            h.update(os.path.basename(p).encode())
            h.update(runner.file_hash(p).encode())
        _code = h.hexdigest()[:32]
    return _code


def _hash(d):
    return hashlib.sha256(json.dumps(d, sort_keys=True).encode()).hexdigest()[:32]


def _qvar(x):
    # argument with loop variables: double quotes, only $var/${var} expand
    if not VAR.search(x):
        return registry.quote(x)
    return '"' + re.sub(r'([\\"`])', r"\\\1", x) + '"'


def _subst(x, it):
    return VAR.sub(lambda m: it[m.group(1) or m.group(2)], x)


def _vars(x):
    return [a or b for a, b in VAR.findall(x)]


def _dollar_in_single_quotes(line):
    q = None
    for c in line:
        if q is None and c in "'\"":
            q = c
        elif c == q:
            q = None
        elif c == "$" and q == "'":
            return True
    return False


def _refs(argv):
    out = []
    for a in argv:
        m = REF.match(a)
        if m and m.group(1) and m.group(1) not in out:
            out.append(m.group(1))
    return out


class command:
    # one jks_* call: environment, script, argv (may contain @, @id and loop variables)
    def __init__(self, name, argv, env=None):
        self.name, self.argv, self.env = name, list(argv), dict(env or {})

    def spec(self):
        return registry.BY_NAME[self.name]

    def values(self):
        return self.spec().parse(self.argv)

    def words(self, quote=registry.quote):
        return ["%s=%s" % (k, quote(v)) for k, v in sorted(self.env.items())], \
            [self.name] + [quote(a) for a in self.argv]

    def definition(self):
        return {"name": self.name, "argv": self.argv, "env": self.env}

    def instance(self, it):
        return command(self.name, [_subst(a, it) for a in self.argv],
                       dict((k, _subst(v, it)) for k, v in self.env.items()))


class node:
    # kind: source (a database file), list (words), step (one command), loop (commands per iteration)
    def __init__(self, id, kind, parent=None, cmd=None, source=None, values=None, loops=None, body=None,
                 meta=None, notes=()):
        self.id, self.kind, self.parent = id, kind, parent
        self.cmd = cmd
        self.source = source
        self.values = list(values or [])
        self.loops = list(loops or [])  # [{"vars": [..], "kind": words|seq|values|list, ...}]
        self.body = list(body or [])  # [command]
        self.meta = dict(meta or {})
        self.meta["id"] = id
        self.notes = list(notes)

    def is_source(self):
        return self.kind == "source"

    def has_db(self):
        return self.kind != "list"

    def commands(self):
        return [self.cmd] if self.kind == "step" else self.body

    def refs(self):
        return _refs([a for c in self.commands() for a in c.argv])

    def value_inputs(self):
        # nodes holding loop values (levels still being edited may not name one yet)
        out = [l.get("node") if l["kind"] == "values" else l.get("list") for l in self.loops
               if l["kind"] in ("values", "list")]
        return [r for r in out if r]

    def inputs(self):
        # all nodes this node depends on
        out = [self.parent] if self.parent else []
        for r in self.refs() + self.value_inputs():
            if r not in out:
                out.append(r)
        return out

    def loop_vars(self):
        return [v for l in self.loops for v in l["vars"]]

    def definition(self):
        if self.kind == "source":
            return {"source": self.source}
        if self.kind == "list":
            return {"list": self.values}
        if self.kind == "step":
            return dict(self.cmd.definition(), parent=self.parent)
        return {"parent": self.parent, "loops": self.loops, "body": [c.definition() for c in self.body]}

    def lines(self):
        if self.kind == "source":
            return ["jks_source %s %s" % (self.id, registry.quote(self.source))]
        if self.kind == "list":
            return ["jks_list %s" % self.id + "".join(" " + registry.quote(v) for v in self.values)]
        if self.kind == "step":
            env, words = self.cmd.words()
            return [" ".join(env + ["jks_step", self.id, self.parent or "-"] + words)]
        out = ["jks_begin %s %s" % (self.id, self.parent)]
        ind = ""
        for l in self.loops:
            var = l["vars"][0] if len(l["vars"]) == 1 else l.get("row", "row")
            if l["kind"] == "words":
                spec = " ".join(registry.quote(w) for w in l["words"])
            elif l["kind"] == "seq":
                spec = "$(seq %s)" % " ".join(str(x) for x in l["seq"])
            elif l["kind"] == "values":
                spec = "$(jks_values @%s %s)" % (l["node"], registry.quote(l["tag"]))
            else:
                spec = "$(jks_list_values %s)" % l["list"]
            out.append("%sfor %s in %s; do" % (ind, var, spec))
            ind += "  "
            if len(l["vars"]) > 1:
                out.append('%sread -r %s <<< "$%s"' % (ind, " ".join(l["vars"]), var))
        for c in self.body:
            env, words = c.words(_qvar)
            out.append(ind + " ".join(env + ["jks_apply", self.id] + words))
        for l in self.loops:
            ind = ind[:-2]
            out.append(ind + "done")
        return out


class flow:
    def __init__(self, path):
        self.path = os.path.abspath(path)
        self.base = os.path.dirname(self.path)
        self.nodes = {}  # id -> node, in file order
        self.trailer = []  # comment lines after the last node

    # ---- file format ----
    @staticmethod
    def load(path):
        f = flow(path)
        with open(path) as fh:
            lines = fh.read().split("\n")
        # logical lines (backslash continuations joined) with line numbers
        logical, i = [], 0
        while i < len(lines):
            no, line = i + 1, lines[i]
            i += 1
            while line.endswith("\\") and not line.lstrip().startswith("#") and i < len(lines):
                line = line[:-1] + " " + lines[i].strip()
                i += 1
            logical.append((no, line))
        meta, notes, header, k = None, [], True, 0
        while k < len(logical):
            no, line = logical[k]
            k += 1
            s = line.strip()
            where = "%s:%d" % (path, no)
            if s.startswith("#@jks"):
                if meta is not None:
                    raise FlowError("%s: #@jks line without a command before it" % where)
                try:
                    meta = json.loads(s[5:])
                    assert isinstance(meta, dict) and "id" in meta
                except (ValueError, AssertionError):
                    raise FlowError("%s: #@jks needs a JSON object with an id" % where)
                header = False
                continue
            if meta is None:
                if header or s == "":
                    continue
                if s.startswith("#"):
                    notes.append(line)
                    continue
                raise FlowError("%s: command without a #@jks line before it" % where)
            if s.startswith("jks_begin"):
                n, k = f.parse_loop(logical, k - 1, meta, notes, path)
            else:
                n = f.parse_command(s, meta, notes, where)
            f.add(n)
            meta, notes = None, []
        if meta is not None:
            raise FlowError("%s: #@jks line %s without a command" % (path, meta.get("id")))
        f.trailer = notes
        return f

    @staticmethod
    def split(s, where):
        try:
            words = shlex.split(s)
        except ValueError as e:
            raise FlowError("%s: %s" % (where, e))
        env = {}
        while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
            k, v = words.pop(0).split("=", 1)
            env[k] = v
        return env, words

    def parse_command(self, s, meta, notes, where):
        env, words = self.split(s, where)
        if len(words) == 3 and words[0] == "jks_source" and not env:
            n = node(words[1], "source", source=words[2], meta=meta, notes=notes)
        elif len(words) >= 2 and words[0] == "jks_list" and not env:
            n = node(words[1], "list", values=words[2:], meta=meta, notes=notes)
        elif len(words) >= 4 and words[0] == "jks_step":
            if any("$" in x for x in list(env.values()) + words):
                raise FlowError("%s: variables are only allowed inside loops" % where)
            n = node(words[1], "step", None if words[2] == "-" else words[2], command(words[3], words[4:], env),
                     meta=meta, notes=notes)
        else:
            raise FlowError("%s: expected jks_source, jks_list, jks_step or jks_begin" % where)
        if n.id != meta["id"]:
            raise FlowError("%s: the command is for %s but #@jks names %s" % (where, n.id, meta["id"]))
        return n

    def parse_loop(self, logical, k, meta, notes, path):
        no, line = logical[k]
        env, words = self.split(line.strip(), "%s:%d" % (path, no))
        if env or len(words) != 3:
            raise FlowError("%s:%d: expected jks_begin id parent" % (path, no))
        id, parent = words[1], words[2]
        if id != meta["id"]:
            raise FlowError("%s:%d: the loop is for %s but #@jks names %s" % (path, no, id, meta["id"]))
        loops, body, depth = [], [], 0
        k += 1
        while True:
            if k >= len(logical):
                raise FlowError("%s: loop %s is not closed with done" % (path, id))
            no, line = logical[k]
            k += 1
            s = line.strip()
            where = "%s:%d" % (path, no)
            if s == "" or (s.startswith("#") and not s.startswith("#@jks")):
                continue
            m = re.match(r"^for\s+([A-Za-z_][A-Za-z0-9_]*)\s+in\s+(.*?)\s*;\s*do$", s)
            if m:
                if body:
                    raise FlowError("%s: a loop inside the body of another loop must come first" % where)
                loops.append(self.parse_spec(m.group(1), m.group(2), where))
                depth += 1
                # a row loop reads its variables in the next line
                if k < len(logical):
                    r = re.match(r'^read\s+-r\s+([A-Za-z_][A-Za-z0-9_ ]*?)\s*<<<\s*"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?"$',
                                 logical[k][1].strip())
                    if r:
                        if r.group(2) != m.group(1):
                            raise FlowError("%s:%d: read must use $%s" % (path, logical[k][0], m.group(1)))
                        loops[-1]["vars"] = r.group(1).split()
                        loops[-1]["row"] = m.group(1)
                        k += 1
                continue
            if s == "done":
                if not body:
                    raise FlowError("%s: loop %s has no jks_apply line" % (where, id))
                depth -= 1
                if depth == 0:
                    break
                continue
            if depth == 0:
                raise FlowError("%s: expected a for line after jks_begin" % where)
            if _dollar_in_single_quotes(s):
                raise FlowError("%s: loop variables need double quotes (bash does not expand '$...')" % where)
            env, words = self.split(s, where)
            if len(words) < 3 or words[0] != "jks_apply" or words[1] != id:
                raise FlowError("%s: expected jks_apply %s script ..." % (where, id))
            body.append(command(words[2], words[3:], env))
        if depth != 0:
            raise FlowError("%s: loop %s: for and done do not match" % (path, id))
        return node(id, "loop", parent, loops=loops, body=body, meta=meta, notes=notes), k

    @staticmethod
    def parse_spec(var, spec, where):
        l = {"vars": [var]}
        m = re.match(r"^\$\(seq((?:\s+-?\d+){1,3})\)$", spec)
        if m:
            l.update(kind="seq", seq=[int(x) for x in m.group(1).split()])
            return l
        m = re.match(r"^\$\(jks_values\s+(.*)\)$", spec)
        if m:
            w = shlex.split(m.group(1))
            if len(w) != 2 or not REF.match(w[0]) or w[0] == "@":
                raise FlowError("%s: expected $(jks_values @node tag)" % where)
            l.update(kind="values", node=w[0][1:], tag=w[1])
            return l
        m = re.match(r"^\$\(jks_list_values\s+(\S+)\)$", spec)
        if m:
            l.update(kind="list", list=m.group(1))
            return l
        if "$" in spec or "`" in spec:
            raise FlowError("%s: loop values must be words, $(seq ...), $(jks_values @node tag) "
                            "or $(jks_list_values list)" % where)
        try:
            l.update(kind="words", words=shlex.split(spec))
        except ValueError as e:
            raise FlowError("%s: %s" % (where, e))
        return l

    def text(self):
        name = os.path.basename(self.path)
        extra = "|".join(v for v in registry.ENV_ALL if not v.startswith("JKS_"))
        out = [HEADER % (FORMAT, name, name, extra)]
        for n in self.nodes.values():
            out += n.notes
            out.append("#@jks " + json.dumps(n.meta, sort_keys=True))
            out += n.lines()
        out += self.trailer
        return "\n".join(out) + "\n"

    def save(self, path=None):
        path = os.path.abspath(path or self.path)
        tmp = path + ".tmp%d" % os.getpid()
        with open(tmp, "w") as fh:
            fh.write(self.text())
        os.chmod(tmp, 0o755)
        os.replace(tmp, path)

    def copy(self):
        # same file and work directory, independent list of nodes (for previews)
        f = flow(self.path)
        f.nodes, f.trailer = dict(self.nodes), list(self.trailer)
        return f

    # ---- editing ----
    def check(self, n, before):
        # before: ids of the nodes that may be read
        if not ID.match(n.id):
            raise FlowError("invalid node id %r" % n.id)
        for r in n.inputs():
            if r not in before:
                raise FlowError("%s: reads %s, which is not defined before it" % (n.id, r))
            if r in self.nodes and not self.nodes[r].has_db() and r not in n.value_inputs():
                raise FlowError("%s: %s is a list, not a database" % (n.id, r))
        if n.kind == "source":
            return
        if n.kind == "list":
            for v in n.values:
                if v == "" or re.search(r"\s", v):
                    raise FlowError("%s: list values must be words without spaces" % n.id)
            return
        if n.kind == "loop":
            if n.parent is None:
                raise FlowError("%s: a loop needs the node it starts from" % n.id)
            names = n.loop_vars()
            if len(set(names)) != len(names) or "W" in names:
                raise FlowError("%s: loop variables must be distinct (and not W)" % n.id)
            for l in n.loops:
                if l["kind"] == "values" and not (l.get("node") and l.get("tag")):
                    raise FlowError("%s: choose the node and the tag the loop values come from" % n.id)
                if l["kind"] == "list" and not l.get("list"):
                    raise FlowError("%s: choose the list the loop runs over" % n.id)
                if l["kind"] == "seq" and not l.get("seq"):
                    raise FlowError("%s: seq needs first, step and last" % n.id)
                if l["kind"] == "values" and l["node"] in self.nodes and not self.nodes[l["node"]].has_db():
                    raise FlowError("%s: jks_values needs a database node" % n.id)
                if l["kind"] == "list" and (l["list"] not in self.nodes or self.nodes[l["list"]].kind != "list"):
                    raise FlowError("%s: %s is not a list" % (n.id, l["list"]))
                if l["kind"] == "seq" and (len(l["seq"]) == 3 and l["seq"][1] == 0):
                    raise FlowError("%s: seq with increment 0" % n.id)
        for c in n.commands():
            self.check_command(n, c)

    def check_command(self, n, c):
        if c.name not in registry.BY_NAME:
            raise FlowError("%s: %s is not a known jks script" % (n.id, c.name))
        spec = c.spec()
        try:
            v = spec.parse(c.argv)
        except ValueError as e:
            raise FlowError("%s: %s" % (n.id, e))
        if spec.get_primary(v) != "@":
            raise FlowError("%s: the database %s writes must be @" % (n.id, c.name))
        kind = spec.primary_kind()
        if n.kind == "loop":
            if kind == "db_new":
                raise FlowError("%s: %s writes a new database and cannot be applied in a loop" % (n.id, c.name))
        elif kind == "db" and n.parent is None:
            raise FlowError("%s: %s modifies a database; give the node it starts from" % (n.id, c.name))
        elif kind == "db_new" and n.parent is not None:
            raise FlowError("%s: %s writes a new database; its parent must be -" % (n.id, c.name))
        for a, x, _ in spec.items(v):
            if REF.match(x) and x != "@" and a.kind != "db_in":
                raise FlowError("%s: %s can only be used for an input database" % (n.id, x))
        allowed = set(n.loop_vars())
        for x in c.argv + list(c.env.values()):
            for var in _vars(x):
                if var not in allowed:
                    raise FlowError("%s: $%s is not a loop variable" % (n.id, var))
            if "$" in VAR.sub("", x) or "`" in x:
                raise FlowError("%s: only loop variables may use $ (in %r)" % (n.id, x))

    def add(self, n):
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

    def rebase(self, id, parent):
        # node id (and everything after it) starts from parent instead; the file is reordered
        # if parent comes later
        n = self.nodes.get(id)
        if n is None or n.kind not in ("step", "loop") or n.parent is None:
            raise FlowError("%s does not start from another node" % id)
        if parent not in self.nodes or not self.nodes[parent].has_db():
            raise FlowError("%s is not a database node" % parent)
        if parent == id or parent in self.descendants(id):
            raise FlowError("%s comes after %s: rebasing would make a cycle" % (parent, id))
        m = copy.copy(n)  # nodes may be shared with copies of the flow
        m.parent = parent
        self.nodes[id] = m
        self.reorder()

    def reorder(self):
        # stable topological order: every node after the nodes it reads
        todo, placed, out = list(self.nodes), set(), []
        while todo:
            for k, i in enumerate(todo):
                if all(r in placed for r in self.nodes[i].inputs()):
                    break
            else:
                raise FlowError("the flow has a cycle through %s" % ", ".join(todo))
            out.append(todo.pop(k))
            placed.add(out[-1])
        self.nodes = dict((i, self.nodes[i]) for i in out)
        before = set()
        for i, n in self.nodes.items():
            self.check(n, before)
            before.add(i)

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


def _unchanged(a, b, tags):
    # tag a (of the base) equals tag b (of a database with block tags `tags`)
    try:
        return _same_array(a.orig, b.orig) and _same_array(runner._aligned(a, tags), b.blocks)
    except (ValueError, TypeError):
        return False


def make_delta(parent, child):
    # tags of child that differ from parent (blocks compared by block tag)
    changed = [t for t in child.keys() if t not in parent.set or not _unchanged(parent.set[t], child.set[t], child.tags)]
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


def appended(parent, res):
    # tags res appends to parent if that is all it changes (else None)
    pk = list(parent.keys())
    if list(res.keys())[: len(pk)] != pk or list(res.tags) != list(parent.tags) or res.info != parent.info:
        return None
    if not all(_same_array(parent.set[t].orig, res.set[t].orig) and _same_array(parent.set[t].blocks, res.set[t].blocks)
               for t in pk):
        return None
    return list(res.keys())[len(pk):]


class engine:
    def __init__(self, fl, work=None):
        self.flow = fl
        name = os.path.splitext(os.path.basename(fl.path))[0]
        self.work = os.path.abspath(work or os.environ.get("JKS_FLOW_WORK") or os.path.join(fl.base, name + ".work"))
        self.store = os.path.join(self.work, "store")
        self._memo = []  # (key, resamples), most recent last
        self._hashes = self._read_json("hashes.json")
        self._values = self._read_json("values.json")
        self._sources = {}  # source key -> path
        self._why = {}  # node id -> why its key is unknown

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

    # ---- keys ----
    def keys(self):
        # node id -> key, None where it cannot be known yet (see self._why)
        keys, self._why = {}, {}
        for n in self.flow.nodes.values():
            try:
                keys[n.id] = self.key(n, keys)
            except NotReady as e:
                keys[n.id], self._why[n.id] = None, str(e) or "values pending"
            except (OSError, FlowError) as e:
                keys[n.id], self._why[n.id] = None, "missing: %s" % e
        return keys

    def external(self, cmds):
        ext = {}
        for c in cmds:
            for a, x, _ in c.spec().items(c.values()):
                if a.kind == "db_in" and not REF.match(x):
                    ext[x] = self.file_hash(self.path(x))
                elif a.kind == "glob":
                    ext[x] = [[os.path.relpath(f, self.flow.base), os.stat(f).st_size, os.stat(f).st_mtime_ns]
                              for f in sorted(glob.glob(self.path(x)))]
        return ext

    def scripts(self, cmds):
        return [runner.file_hash(registry.script_path(c.name)) for c in cmds]

    def key(self, n, keys):
        if n.kind == "source":
            k = "s" + self.file_hash(self.path(n.source))[:31]
            self._sources[k] = self.path(n.source)
            return k
        if n.kind == "list":
            return "l" + _hash({"list": n.values})[:31]
        for r in n.inputs():
            if keys.get(r) is None:
                if r in self._why and self._why[r].startswith("missing"):
                    raise FlowError("input %s missing" % r)
                raise NotReady("waits for %s" % r)
        if n.kind == "step":
            d = {"script": self.scripts([n.cmd]), "code": code_hash(), "def": n.definition(),
                 "inputs": dict((r, keys[r]) for r in n.inputs()), "external": self.external([n.cmd])}
            return _hash(d)
        # a loop depends on the values, not on the nodes that hold them
        its = self.iterations(n, keys)
        cmds = [c.instance(it) for it in its for c in n.body]
        d = {"script": self.scripts(n.body), "code": code_hash(), "def": n.definition(), "values": its,
             "inputs": dict((r, keys[r]) for r in [n.parent] + n.refs()), "external": self.external(cmds)}
        return _hash(d)

    def loop_values(self, l, keys):
        if l["kind"] == "words":
            return l["words"]
        if l["kind"] == "seq":
            s = l["seq"]
            a, step, b = (1, 1, s[0]) if len(s) == 1 else (s[0], 1, s[1]) if len(s) == 2 else s
            return [str(x) for x in range(a, b + (1 if step > 0 else -1), step)]
        if l["kind"] == "list":
            return list(self.flow.nodes[l["list"]].values)
        k = keys[l["node"]]
        c = "%s|%s" % (k, l["tag"])
        if c not in self._values:
            if not self.have(k):
                raise NotReady("values of %s not computed" % l["node"])
            n = self.flow.nodes[l["node"]]
            tmp = os.path.join(self.work, "tmp", "values-%d" % os.getpid())
            os.makedirs(tmp, exist_ok=True)
            try:
                f = self.file_of(n, k, tmp)
                p = subprocess.run([sys.executable, registry.script_path("jks_values"), f, l["tag"]],
                                   env=runner.clean_env({}), capture_output=True, text=True)
            finally:
                shutil.rmtree(tmp, ignore_errors=True)
            if p.returncode != 0:
                raise FlowError("jks_values @%s %s: %s" % (l["node"], l["tag"], (p.stdout + p.stderr).strip()))
            self._values[c] = p.stdout.split()
            self._write_json("values.json", self._values)
        return list(self._values[c])

    def iterations(self, n, keys):
        # every combination of the loop values, outer loop first: [{var: value}]
        axes = []
        for l in n.loops:
            vals = self.loop_values(l, keys)
            if len(l["vars"]) == 1:
                axes.append([{l["vars"][0]: v} for v in vals])
            else:
                rows = []
                for v in vals:
                    f = v.split()
                    if len(f) != len(l["vars"]):
                        raise FlowError("%s: row %r does not have %d fields" % (n.id, v, len(l["vars"])))
                    rows.append(dict(zip(l["vars"], f)))
                axes.append(rows)
        return [dict(kv for d in combo for kv in d.items()) for combo in itertools.product(*axes)]

    def iteration_key(self, base, cmds, refs):
        return _hash({"iteration": [c.definition() for c in cmds], "base": base, "refs": refs,
                      "script": self.scripts(cmds), "code": code_hash(), "external": self.external(cmds)})

    # ---- status ----
    def meta(self, key):
        try:
            with open(os.path.join(self.store, key + ".json")) as f:
                return json.load(f)
        except (OSError, ValueError):
            return None

    def have(self, key):
        if key is None:
            return False
        if key[0] in "sl":
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
            r = {"id": n.id, "key": k, "built": built, "reason": "", "detail": ""}
            if k is None and self._why.get(n.id, "").startswith("missing"):
                r["status"], r["reason"] = "missing", self._why[n.id][9:]
            elif k is not None and self.have(k):
                r["status"] = "ok"
            elif k is not None and failed.get("key") == k:
                r["status"], r["reason"] = "failed", failed.get("error", "")
            elif built and self.have(built):
                r["status"] = "stale"
                bm = self.meta(built)
                if bm and bm.get("def") != n.definition():
                    r["reason"] = "definition changed"
                elif bm and (bm.get("code") != code_hash() or bm.get("script") != self.scripts(n.commands())):
                    r["reason"] = "code changed"
                elif bm and n.kind == "loop" and k is not None and bm.get("values") != self.iterations(n, keys):
                    r["reason"] = "values changed"
                else:
                    r["reason"] = "input changed"
            else:
                r["status"] = "new"
                if k is None:
                    r["reason"] = self._why.get(n.id, "")
            if n.kind == "loop":
                r["detail"] = self.loop_detail(n, keys, k) if k else self._why.get(n.id, "")
            out.append(r)
        return out

    def loop_detail(self, n, keys, k):
        m = self.meta(k)
        if m is not None:
            return "%d iterations, %s" % (len(m["iterations"]), m["mode"])
        # cached iterations of the map form, or of the longest cached start of the sequence
        its = self.iterations(n, keys)
        cmds = [[c.instance(it) for c in n.body] for it in its]
        refs = self.refkeys(n, keys)
        ks = [self.iteration_key(keys[n.parent], c, refs) for c in cmds]
        cached, prev = 0, keys[n.parent]
        for c in cmds:
            prev = self.iteration_key(prev, c, refs)
            if not self.have(prev):
                break
            cached += 1
        return "%d of %d iterations cached" % (max(cached, sum(self.have(x) for x in ks)), len(ks))

    def refkeys(self, n, keys):
        return dict((r, keys[r]) for r in n.refs())

    # ---- databases of nodes ----
    def snapshot(self, key):
        # store a copy of a source so that deltas against it survive changes of the file
        if self.meta(key) is None:
            os.makedirs(self.store, exist_ok=True)
            f = os.path.join(self.store, key + ".jks")
            runner.clone(self._sources[key], f)
            if "s" + runner.file_hash(f)[:31] != key:
                os.remove(f)
                raise FlowError("%s changed while it was copied" % self._sources[key])
            with open(os.path.join(self.store, key + ".json"), "w") as fh:
                json.dump({"key": key, "stored": "full", "file": key + ".jks", "snapshot": self._sources[key]}, fh)
        return key

    def load(self, key):
        # resamples of a stored result (reconstructed from deltas) or of a source
        for k, r in self._memo:
            if k == key:
                return r
        m = self.meta(key)
        if m is None:
            if key[0] == "s" and key in self._sources:
                r = jks.resamples(self._sources[key])
                self._remember(key, r)
                return r
            raise FlowError("no stored result for %s" % key)
        p = os.path.join(self.store, m["file"])
        if m["stored"] == "full":
            r = jks.resamples(p)
        else:
            r = apply_delta(self.load(m["base"]), jks.resamples(p), m["delta"])
        self._remember(key, r)
        return r

    def _remember(self, key, r):
        self._memo = [(k, x) for k, x in self._memo if k != key][-2:] + [(key, r)]

    def file_of(self, n, key, tmp):
        # a readable database file (the source itself, a full stored file or a reconstruction in tmp)
        if n.is_source():
            return self.path(n.source)
        return self.file_of_key(key, tmp)

    def file_of_key(self, key, tmp):
        if key[0] == "s" and key in self._sources and self.meta(key) is None:
            return self._sources[key]
        m = self.meta(key)
        if m["stored"] == "full":
            return os.path.join(self.store, m["file"])
        p = os.path.join(tmp, "in-%s.jks" % key)
        if not os.path.exists(p):
            _write(self.load(key), p)
        return p

    def export(self, id, target):
        keys = self.keys()
        k = keys.get(id)
        n = self.flow.nodes[id]
        if not n.has_db():
            raise FlowError("%s is a list" % id)
        if not self.have(k):
            raise FlowError("%s is not computed; run it first" % id)
        if n.is_source():
            shutil.copyfile(self.path(n.source), target)
        else:
            _write(self.load(k), target)

    def depth(self, key):
        # deltas in a row down to the next full copy
        d = 0
        while key and key[0] not in "sl":
            m = self.meta(key)
            if m is None or m["stored"] == "full":
                break
            d, key = d + 1, m["base"]
        return d

    # ---- running ----
    async def run(self, targets=None, jobs=1, log=lambda id, line: None, force=False, procs=None,
                  state=lambda id, s: None):
        # compute targets (default: all nodes) and what they need; returns id -> result
        # state(id, s) is told "running", "ok" and "failed"
        keys = self.keys()
        want = self.flow.ancestors(targets) if targets else set(self.flow.nodes)
        for i in want:
            if keys[i] is None and self._why.get(i, "").startswith("missing"):
                raise FlowError("%s: %s" % (i, self._why[i]))
        todo = [i for i in self.flow.nodes if i in want and
                (keys[i] is None or not self.have(keys[i]) or (force and targets and i in targets))]
        os.makedirs(self.store, exist_ok=True)
        self.sem = asyncio.Semaphore(jobs)
        loop = asyncio.get_running_loop()
        done = dict((i, loop.create_future()) for i in todo)
        results = {}

        async def one(i):
            n = self.flow.nodes[i]
            for r in n.inputs():
                if r in done and not await done[r]:
                    results[i] = {"ok": False, "error": "input %s failed" % r, "id": i}
                    done[i].set_result(False)
                    return
            try:
                if keys[i] is None:
                    keys[i] = self.key(n, keys)  # its inputs exist now
                if self.have(keys[i]) and not (force and targets and i in targets):
                    done[i].set_result(True)
                    return
                state(i, "running")
                if n.kind == "loop":
                    res = await self.build_loop(n, keys, lambda line: log(i, line), procs)
                else:
                    async with self.sem:
                        res = await self.build_step(n, keys, lambda line: log(i, line), procs)
            except (FlowError, NotReady, OSError) as e:
                res = {"ok": False, "error": str(e), "id": i, "key": keys.get(i)}
            results[i] = res
            self.record(n, keys[i], res)
            state(i, "ok" if res["ok"] else "failed")
            done[i].set_result(res["ok"])

        await asyncio.gather(*[one(i) for i in todo])
        return results

    def record(self, n, key, res):
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

    async def build_step(self, n, keys, log, procs):
        base = keys[n.parent] if n.parent else None
        return await self.execute(keys[n.id], base, [n.cmd], keys, log, procs,
                                  {"id": n.id, "command": " ".join(n.lines()), "def": n.definition()})

    async def execute(self, key, base, cmds, keys, log, procs, meta):
        # run cmds on a copy of base (None: none) and keep the result under key
        tmp = os.path.join(self.work, "tmp", "%s-%d" % (key, os.getpid()))
        shutil.rmtree(tmp, ignore_errors=True)
        os.makedirs(tmp)
        t0 = time.time()
        res = {"ok": False, "error": None, "key": key, "id": meta["id"], "log": ""}
        lines = []
        try:
            out = os.path.join(tmp, meta["id"] + ".jks")
            if base is not None:
                bm = self.meta(base)
                if bm is not None and bm["stored"] == "delta":
                    _write(self.load(base), out)
                else:
                    runner.clone(self.file_of_key(base, tmp), out)
            before = runner.file_hash(out) if os.path.exists(out) else None
            for c in cmds:
                argv = []
                for a in c.argv:
                    m = REF.match(a)
                    if a == "@":
                        argv.append(out)
                    elif m and m.group(1):
                        argv.append(self.file_of(self.flow.nodes[m.group(1)], keys[m.group(1)], tmp))
                    else:
                        argv.append(a)
                if len(cmds) > 1:
                    lines.append("$ " + " ".join(c.words()[0] + c.words()[1]))
                    log(lines[-1])
                rc, out_lines = await runner.execute(c.name, argv, c.env, self.flow.base, log, procs)
                lines += out_lines
                if rc != 0:
                    raise FlowError("%s failed (exit code %d)" % (c.name, rc))
            if not os.path.exists(out) or runner.file_hash(out) == before:
                raise FlowError("%s wrote no database (did it print its usage?)" % cmds[-1].name)
            child = jks.resamples(out)
            m = dict(meta, key=key, code=code_hash(), script=self.scripts(cmds),
                     created=str(datetime.datetime.now()), log="\n".join(lines))
            res.update(self.keep(key, base, child, m, out))
            res["ok"] = True
        except Exception as e:
            res["error"] = str(e) if isinstance(e, FlowError) else "%s: %s" % (type(e).__name__, e)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        res["log"] = "\n".join(lines)
        res["seconds"] = round(time.time() - t0, 3)
        return res

    async def build_loop(self, n, keys, log, procs):
        t0 = time.time()
        pk = keys[n.parent]
        refs = self.refkeys(n, keys)
        its = self.iterations(n, keys)
        cmds = [[c.instance(it) for c in n.body] for it in its]
        mode = n.meta.get("mode", "auto")
        if mode not in ("auto", "map", "sequence"):
            raise FlowError("%s: mode must be auto, map or sequence" % n.id)
        runs = []

        async def iteration(i, base, k):
            if self.have(k):
                return {"ok": True, "cached": True}
            async with self.sem:
                r = await self.execute(k, base, cmds[i], keys, lambda line: log("[%d] %s" % (i + 1, line)), procs,
                                       {"id": "%s[%d]" % (n.id, i + 1), "iteration": its[i], "loop": n.id})
            runs.append(r)
            if not r["ok"]:
                raise FlowError("iteration %d (%s) failed: %s\n%s" % (
                    i + 1, " ".join("%s=%s" % kv for kv in its[i].items()), r["error"], r["log"]))
            return r

        parent = self.load(self.snapshot(pk) if pk[0] == "s" else pk)
        used, ks, child = None, [], None
        if mode == "map" or (mode == "auto" and all(c.spec().appends for c in n.body) and self.independent(cmds)):
            ks = [self.iteration_key(pk, c, refs) for c in cmds]
            await asyncio.gather(*[iteration(i, pk, k) for i, k in enumerate(ks)])
            added, seen = [], set()
            for k in ks:
                a = appended(parent, self.load(k))
                if a is None or seen & set(a):
                    added = None
                    break
                seen |= set(a)
                added.append((k, a))
            if added is not None:
                child = _empty(parent, parent.tags, parent.info, parent.origin)
                for t in parent.keys():
                    child.set[t] = parent.set[t]
                for k, a in added:
                    r = self.load(k)
                    for t in a:
                        child.set[t] = r.set[t]
                used = "map"
            elif mode == "map":
                raise FlowError("%s: the iterations are not independent (they change more than new tags); "
                                "use \"mode\": \"sequence\"" % n.id)
        if used is None:
            ks, prev = [], pk
            for i, c in enumerate(cmds):
                k = self.iteration_key(prev, c, refs)
                await iteration(i, prev, k)
                ks.append(k)
                prev = k
            child = self.load(prev) if ks else parent
            used = "sequence"
        m = {"id": n.id, "key": keys[n.id], "command": "\n".join(n.lines()), "def": n.definition(), "code": code_hash(),
             "script": self.scripts(n.body), "values": its, "iterations": ks, "mode": used,
             "created": str(datetime.datetime.now()),
             "log": "\n".join("[%s] %s" % (r["id"], line) for r in runs for line in r["log"].splitlines())}
        res = {"ok": True, "key": keys[n.id], "id": n.id, "mode": used, "iterations": len(ks),
               "computed": len(runs), "log": m["log"]}
        res.update(self.keep(keys[n.id], pk, child, m))
        res["seconds"] = round(time.time() - t0, 3)
        return res

    def independent(self, cmds):
        # no iteration reads a tag another one writes (tags known from the script signatures)
        writes = [set(t for c in cs for t in c.spec().tags_out(c.values())) for cs in cmds]
        reads = [set(t for c in cs for t in c.spec().tags_in(c.values())) for cs in cmds]
        for i, r in enumerate(reads):
            for j, w in enumerate(writes):
                if i != j and any(fnmatch.fnmatchcase(t, p) for t in r for p in w):
                    return False
        return True

    def keep(self, key, base, child, m, out=None):
        # store child as a delta to base if that reproduces it exactly, else in full
        stored = "full"
        if base is not None:
            if base[0] == "s":
                self.snapshot(base)
            if self.depth(base) + 1 < CHECKPOINT:
                parent = self.load(base)
                d, dm = make_delta(parent, child)
                if len(d.set) < 0.5 * max(len(child.set), 1) and _same(apply_delta(parent, d, dm), child):
                    _write(d, os.path.join(self.store, key + ".delta.jks"))
                    m.update({"stored": "delta", "file": key + ".delta.jks", "base": base, "delta": dm,
                              "changed": list(d.set)})
                    stored = "delta"
        if stored == "full":
            f = os.path.join(self.store, key + ".jks")
            if out is not None:
                os.replace(out, f)
            else:
                _write(child, f)
            m.update({"stored": "full", "file": key + ".jks"})
        m["bytes"] = os.path.getsize(os.path.join(self.store, m["file"]))
        with open(os.path.join(self.store, key + ".json"), "w") as f:
            json.dump(m, f, indent=1)
        self._remember(key, child)
        return {"stored": stored, "bytes": m["bytes"]}

    def gc(self, dry=False):
        # remove stored results that no current or last built node needs (loop iterations
        # of those nodes are kept so that editing one value recomputes one iteration)
        keys, state = self.keys(), self._read_json("state.json")
        keep, todo = set(), [k for k in list(keys.values()) + list(state.get("built", {}).values()) if k]
        while todo:
            k = todo.pop()
            if k in keep:
                continue
            keep.add(k)
            m = self.meta(k)
            if m:
                if m.get("stored") == "delta":
                    todo.append(m["base"])
                todo += m.get("iterations", [])
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
