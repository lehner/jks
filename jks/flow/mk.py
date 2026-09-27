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
# Import of an mk driver (a bash script of jks_* calls on database files) as a flow.
#
# The driver is read with a small bash lexer (quotes, escapes, continuation lines,
# comments, $var/${var}, $(...)) and a parser for simple commands and for loops.
# Every database file is followed through the script: the node that holds its
# current state changes with every step that writes it, so a later command on the
# same file starts from that node.  What cannot be mapped is reported (and kept as
# a comment in the flow file), never guessed.
#
import os, re
from jks.flow import core, registry

NAME = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
IGNORED = ("echo", "set", "true", ":", "mkdir", "date", "sleep")  # no effect on databases
SINKS_NOTE = "prints only; not part of a flow"


class Unsupported(Exception):
    def __init__(self, msg, block=True):
        # block: the statement may still become a bash block
        Exception.__init__(self, msg)
        self.block = block


# ---- lexer ----
class word:
    # parts: ("lit", text, quoted), ("var", name, quoted), ("cmd", text, quoted)
    def __init__(self, start, line):
        self.parts, self.start, self.end, self.line = [], start, start, line

    def add(self, kind, text, quoted):
        if kind == "lit" and self.parts and self.parts[-1][0] == "lit" and self.parts[-1][2] == quoted:
            self.parts[-1] = ("lit", self.parts[-1][1] + text, quoted)
        else:
            self.parts.append((kind, text, quoted))

    def literal(self):
        # the text if the word has no expansions
        if all(p[0] == "lit" for p in self.parts):
            return "".join(p[1] for p in self.parts)
        return None


OPS = ["<<<", "&&", "||", ">>", "<<", ";;", ">&", "&>", ";", "&", "|", "<", ">", "(", ")"]


def lex(src):
    # -> tokens ("word", word) | ("op", text, start, line) | ("nl", None, start, line)
    toks, i, line, n = [], 0, 1, len(src)
    cur = None

    def end():
        nonlocal cur
        if cur is not None:
            cur.end = i
            toks.append(("word", cur))
            cur = None

    def w():
        nonlocal cur
        if cur is None:
            cur = word(i, line)
        return cur

    def dollar(j, quoted):
        # $... at src[j] -> (part, next index)
        nonlocal line
        if j + 1 < n and src[j + 1] == "{":
            k = src.find("}", j + 2)
            if k < 0:
                raise Unsupported("line %d: ${ is not closed" % line)
            name = src[j + 2 : k]
            if not NAME.fullmatch(name):
                return ("cmd", "${%s}" % name, quoted), k + 1
            return ("var", name, quoted), k + 1
        if j + 1 < n and src[j + 1] == "(":
            depth, k, q = 0, j + 1, None
            while k < n:
                c = src[k]
                if q:
                    if c == q:
                        q = None
                elif c in "'\"":
                    q = c
                elif c == "(":
                    depth += 1
                elif c == ")":
                    depth -= 1
                    if depth == 0:
                        break
                if c == "\n":
                    line += 1
                k += 1
            if k >= n:
                raise Unsupported("line %d: $( is not closed" % line)
            return ("cmd", src[j + 2 : k], quoted), k + 1
        m = NAME.match(src, j + 1)
        if m:
            return ("var", m.group(0), quoted), m.end()
        if j + 1 < n and src[j + 1] in "0123456789@*#?$!-":
            return ("cmd", "$" + src[j + 1], quoted), j + 2
        return ("lit", "$", quoted), j + 1

    while i < n:
        c = src[i]
        if c == "\\":
            if i + 1 < n and src[i + 1] == "\n":
                i, line = i + 2, line + 1
                continue
            if i + 1 < n:
                w().add("lit", src[i + 1], True)
                i += 2
                continue
            i += 1
            continue
        if c in " \t":
            end()
            i += 1
            continue
        if c == "\n":
            end()
            toks.append(("nl", None, i, line))
            i, line = i + 1, line + 1
            continue
        if c == "#" and cur is None:
            while i < n and src[i] != "\n":
                i += 1
            continue
        if c == "'":
            k = src.find("'", i + 1)
            if k < 0:
                raise Unsupported("line %d: ' is not closed" % line)
            text = src[i + 1 : k]
            w().add("lit", text, True)
            line += text.count("\n")
            i = k + 1
            continue
        if c == '"':
            w()
            j = i + 1
            if j < n and src[j] == '"':
                cur.add("lit", "", True)
            while j < n and src[j] != '"':
                d = src[j]
                if d == "\\" and j + 1 < n and src[j + 1] in '$`"\\\n':
                    if src[j + 1] == "\n":
                        line += 1
                    else:
                        cur.add("lit", src[j + 1], True)
                    j += 2
                elif d == "$":
                    part, j = dollar(j, True)
                    cur.add(*part)
                elif d == "`":
                    raise Unsupported("line %d: backquotes are not supported" % line)
                else:
                    if d == "\n":
                        line += 1
                    cur.add("lit", d, True)
                    j += 1
            if j >= n:
                raise Unsupported("line %d: \" is not closed" % line)
            i = j + 1
            continue
        if c == "$":
            part, i = dollar(i, False)
            w().add(*part)
            continue
        if c == "`":
            raise Unsupported("line %d: backquotes are not supported" % line)
        op = next((o for o in OPS if src.startswith(o, i)), None)
        if op:
            end()
            toks.append(("op", op, i, line))
            i += len(op)
            continue
        w().add("lit", c, False)
        i += 1
    end()
    return toks


# ---- parser ----
class cmd_stmt:
    def __init__(self, assigns, words, line, start, end, redirect):
        self.assigns, self.words, self.line, self.start, self.end = assigns, words, line, start, end
        self.redirect = redirect  # the command has redirections


class for_stmt:
    def __init__(self, var, values, body, line, start, end):
        self.var, self.values, self.body, self.line, self.start, self.end = var, values, body, line, start, end


class other_stmt:
    # a construct the importer does not map (if, while, pipelines, functions, ...)
    def __init__(self, what, line, start, end):
        self.what, self.line, self.start, self.end = what, line, start, end


ASSIGN = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)=")
BLOCKS = {"if": "fi", "while": "done", "until": "done", "case": "esac", "{": "}", "select": "done"}


class parser:
    def __init__(self, src):
        self.src, self.toks, self.k = src, lex(src), 0

    def peek(self):
        return self.toks[self.k] if self.k < len(self.toks) else None

    def lit(self, t):
        return t[1].literal() if t and t[0] == "word" else None

    def start(self, t):
        return t[1].start if t[0] == "word" else t[2]

    def line(self, t):
        return t[1].line if t[0] == "word" else t[3]

    def skip_separators(self):
        while self.peek() and (self.peek()[0] == "nl" or (self.peek()[0] == "op" and self.peek()[1] == ";")):
            self.k += 1

    def statements(self, until=None):
        out = []
        while True:
            self.skip_separators()
            t = self.peek()
            if t is None:
                if until:
                    raise Unsupported("%s is missing at the end" % until)
                return out
            if until and self.lit(t) == until:
                self.k += 1
                return out
            out.append(self.statement())

    def rest_of_line(self, t0, what):
        # an unsupported statement: everything up to the end of the line
        start, line = self.start(t0), self.line(t0)
        while self.peek() and self.peek()[0] != "nl":
            self.k += 1
        end = self.start(self.peek()) if self.peek() else len(self.src)
        return other_stmt(what, line, start, end)

    def block(self, t0, what, close):
        # an unsupported compound statement up to its closing word (nested ones counted)
        start, line, depth = self.start(t0), self.line(t0), 0
        opener = self.lit(t0)
        self.k += 1
        while self.peek():
            t = self.peek()
            self.k += 1
            x = self.lit(t)
            if x == opener or (opener in ("while", "until", "select", "for") and x in ("while", "until", "for", "select")):
                depth += 1
            elif x == close:
                if depth == 0:
                    end = t[1].end
                    return other_stmt(what, line, start, end)
                depth -= 1
        raise Unsupported("line %d: %s is not closed with %s" % (line, opener, close))

    def statement(self):
        t0 = self.peek()
        x = self.lit(t0)
        if x == "for":
            return self.for_statement()
        if x in BLOCKS:
            return self.block(t0, "%s ... %s" % (x, BLOCKS[x]), BLOCKS[x])
        if t0[0] == "op":
            return self.rest_of_line(t0, "a line starting with %s" % t0[1])
        assigns, words, redirect = [], [], False
        start, line = self.start(t0), self.line(t0)
        while True:
            t = self.peek()
            if t is None or t[0] == "nl" or (t[0] == "op" and t[1] in (";", "&")):
                break
            if t[0] == "op" and t[1] in ("|", "&&", "||"):
                return self.rest_of_line(t0, "a pipeline or && / || list")
            if t[0] == "op" and t[1] == "(" and words:
                return self.block(t0, "a function definition", "}")
            if t[0] == "op" and t[1] in ("(", ")", ";;"):
                return self.rest_of_line(t0, "a subshell or case")
            if t[0] == "op":
                # a redirection and its target
                redirect = True
                self.k += 1
                if self.peek() and self.peek()[0] == "word":
                    self.k += 1
                continue
            wd = t[1]
            first = wd.parts[0] if wd.parts else None
            m = ASSIGN.match(first[1]) if first and first[0] == "lit" and not first[2] else None
            if not words and m:
                v = word(wd.start, wd.line)
                rest = first[1][m.end():]
                if rest:
                    v.add("lit", rest, False)
                for p in wd.parts[1:]:
                    v.add(*p)
                assigns.append((m.group(1), v))
            else:
                words.append(wd)
            self.k += 1
        end = self.start(self.peek()) if self.peek() else len(self.src)
        return cmd_stmt(assigns, words, line, start, end, redirect)

    def for_statement(self):
        t0 = self.peek()
        start, line = self.start(t0), self.line(t0)
        self.k += 1
        v = self.lit(self.peek())
        if not v or not NAME.fullmatch(v):
            raise Unsupported("line %d: for needs a variable name" % line)
        self.k += 1
        if self.lit(self.peek()) != "in":
            raise Unsupported("line %d: only 'for %s in ...' is supported" % (line, v))
        self.k += 1
        values = []
        while self.peek() and self.peek()[0] == "word":
            values.append(self.peek()[1])
            self.k += 1
        self.skip_separators()
        if self.lit(self.peek()) != "do":
            raise Unsupported("line %d: expected do" % line)
        self.k += 1
        body = self.statements(until="done")
        end = self.toks[self.k - 1][1].end
        return for_stmt(v, values, body, line, start, end)


# ---- conversion ----
class importer:
    def __init__(self, mk, flow_path):
        self.mk = os.path.abspath(mk)
        self.dir = os.path.dirname(self.mk)
        self.src = open(self.mk).read()
        self.fl = core.flow(flow_path)
        self.files = {}  # absolute database path -> node holding its current state
        self.globals = {}  # shell variables with a known value
        self.exported = {}  # exported JKS_* etc. (steps take those their script uses)
        self.export_names = set()  # all exported variables (blocks export them again)
        self.report = []  # (line, text)
        self.pending = []  # comment lines for the next node

    # ---- paths ----
    def abs(self, p):
        return os.path.normpath(os.path.join(self.dir, os.path.expanduser(p)))

    def rel(self, p):
        # a path of the mk as seen from the flow file
        return os.path.relpath(self.abs(p), self.fl.base)

    # ---- messages ----
    def note(self, s, text, keep=True):
        # keep: the statement is copied into the flow file as a comment
        self.report.append((s.line, text))
        if keep:
            self.pending.append("# jks_flow import, %s line %d: %s" % (os.path.basename(self.mk), s.line, text))
            for l in self.src[s.start : s.end].rstrip().split("\n"):
                self.pending.append("#   " + l)

    def add(self, n):
        n.notes = self.pending + n.notes
        self.pending = []
        self.fl.add(n)
        return n.id

    # ---- expansion ----
    def expand(self, wd, loop=()):
        out = []
        for kind, text, quoted in wd.parts:
            if kind == "lit":
                if "$" in text:
                    raise Unsupported("a literal $ in %r (bash would not expand it)" % text)
                if not quoted and not out and text.startswith("~"):
                    text = os.path.expanduser(text)
                out.append(text)
            elif kind == "var":
                if text in loop:
                    out.append("${%s}" % text)
                elif text in self.globals:
                    out.append(self.globals[text])
                elif text == "HOME":
                    out.append(os.path.expanduser("~"))
                else:
                    raise Unsupported("$%s has no value known to the importer" % text)
            else:
                raise Unsupported("$(%s) cannot be imported" % text if not text.startswith("$") else
                                  "%s cannot be imported" % text)
        return "".join(out)

    def expand_words(self, wd, loop=()):
        # with word splitting of an unquoted variable
        if len(wd.parts) == 1 and wd.parts[0][0] == "var" and not wd.parts[0][2] and wd.parts[0][1] not in loop:
            return self.expand(wd, loop).split()
        return [self.expand(wd, loop)]

    # ---- sources ----
    def state_of(self, path, s, modified):
        # node of the current state of a database file; a new source node for a file the
        # driver has not written
        p = self.abs(path)
        if p in self.files:
            return self.files[p]
        if modified:
            self.report.append((s.line, "%s is modified before the driver creates it: imported as a source with "
                                        "its content now (if that is an output of an earlier run, point the "
                                        "source at the original input)" % path))
        base = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.basename(p)[:-4] if p.endswith(".jks") else os.path.basename(p))
        i = self.add(core.node(core.unique_id(self.fl, base or "source"), "source", source=self.rel(path)))
        self.files[p] = i
        return i

    # ---- statements ----
    def run(self):
        stmts = parser(self.src).statements()
        for s in stmts:
            try:
                self.statement(s)
            except (Unsupported, core.FlowError) as e:
                why = str(e)
                if getattr(e, "block", True):
                    try:
                        return_id = self.as_block(s, why)
                    except Unsupported as f:
                        why += "; not a block either: %s" % f
                    else:
                        if return_id:
                            continue
                self.note(s, "not imported: %s" % why)
        self.fl.trailer = self.pending
        self.pending = []
        return self

    def statement(self, s):
        if isinstance(s, other_stmt):
            raise Unsupported("%s is not supported" % s.what)
        if isinstance(s, for_stmt):
            return self.loop(s)
        if not s.words:
            for name, v in s.assigns:
                try:
                    self.globals[name] = self.expand(v)
                except Unsupported:
                    self.globals.pop(name, None)
                    raise
            return
        name = self.expand(s.words[0])
        if name == "export":
            return self.export(s)
        if name == "unset":
            for wd in s.words[1:]:
                k = wd.literal()
                self.globals.pop(k, None)
                self.exported.pop(k, None)
                self.export_names.discard(k)
            return
        args = [x for wd in s.words[1:] for x in self.expand_words(wd)]
        env = dict((k, self.expand(v)) for k, v in s.assigns)
        if name in ("cp", "mv"):
            return self.copy(s, name, args)
        if name == "rm":
            for a in args:
                self.files.pop(self.abs(a), None)
            return
        if name == "cd":
            raise Unsupported("cd changes the meaning of every later path", block=False)
        if name in IGNORED:
            self.report.append((s.line, "%s: skipped (no effect on databases)" % name))
            return
        if name in core.PLOTTERS:
            return self.plot(s, name, args)
        if name in registry.BY_NAME:
            if s.redirect:
                raise Unsupported("redirections of %s are not supported" % name)
            return self.step(s, name, args, env)
        if name.startswith("jks_") or name in ("dump-corrs", "list-corrs"):
            self.note(s, "%s: %s" % (name, SINKS_NOTE), keep=False)
            return
        raise Unsupported("%s is not a jks script" % name)

    def as_block(self, s, why):
        # the statement as a bash block on the one database file it names (None: it names none)
        text = self.src[s.start : s.end].rstrip()
        found = []  # (path, [(start, end)])
        for p in list(self.files):
            names = [re.escape(os.path.relpath(p, self.dir))]
            names += [r"\$%s\b|\$\{%s\}" % (k, k) for k, v in self.globals.items() if self.abs(v) == p]
            spans = [m.span() for m in re.finditer(r"(?<![A-Za-z0-9_./-])(?:%s)(?![A-Za-z0-9_.-])" % "|".join(names), text)]
            if spans:
                found.append((p, spans))
        if not found:
            return None
        if len(found) > 1:
            raise Unsupported("it names several databases (%s)" % ", ".join(os.path.relpath(p, self.dir) for p, _ in found))
        p, spans = found[0]
        quote = _quote_state(text)
        if any(quote[a] == "'" for a, _ in spans):
            raise Unsupported("the database name is inside single quotes")
        for a, b in reversed(spans):
            text = text[:a] + "${DB}" + text[b:]
        # the variables it uses, and the exported ones of the jks scripts
        pre = []
        for k, v in self.globals.items():
            if k in self.exported or re.search(r"\$%s\b|\$\{%s\}" % (k, k), text):
                pre.append(("export %s=%s" if k in self.export_names else "%s=%s") % (k, registry.quote(v)))
        parent = self.files[p]
        i = core.unique_id(self.fl, "block")
        self.add(core.node(i, "block", parent=parent, notes=[
            "# jks_flow import, %s line %d: a bash block (%s); check it, and declare the files it reads" %
            (os.path.basename(self.mk), s.line, why)],
            block={"script": "\n".join(pre + [text]) + "\n", "inputs": []}))
        self.files[p] = i
        self.report.append((s.line, "imported as block node %s on %s (%s): check it" % (i, os.path.relpath(p, self.dir), why)))
        return i

    def export(self, s):
        for wd in s.words[1:]:
            first = wd.parts[0] if wd.parts else ("", "", False)
            m = ASSIGN.match(first[1]) if first[0] == "lit" else None
            if not m:
                continue
            k = m.group(1)
            if k == "PATH":
                self.report.append((s.line, "export PATH: skipped (flows run the scripts of this jks)"))
                continue
            v = word(wd.start, wd.line)
            if first[1][m.end():]:
                v.add("lit", first[1][m.end():], first[2])
            for p in wd.parts[1:]:
                v.add(*p)
            self.globals[k] = self.expand(v)
            self.export_names.add(k)
            if k in registry.ENV_ALL:
                self.exported[k] = self.globals[k]

    def copy(self, s, name, args):
        args = [a for a in args if not a.startswith("-")]
        if len(args) != 2:
            raise Unsupported("%s with %d file arguments" % (name, len(args)))
        a, b = args
        if not (a.endswith(".jks") or self.abs(a) in self.files):
            raise Unsupported("%s of a file that is not a database" % name)
        if os.path.isdir(self.abs(b)):
            b = os.path.join(b, os.path.basename(a))
        self.files[self.abs(b)] = self.state_of(a, s, False)
        if name == "mv":
            self.files.pop(self.abs(a), None)

    def env_for(self, spec, env):
        e = dict((k, v) for k, v in self.exported.items() if k in [x[0] for x in spec.env])
        e.update(env)
        return e

    def bind(self, s, name, args, loop=()):
        # the command with its databases replaced by @ / @id -> (command, file written, parent)
        spec = registry.BY_NAME[name]
        try:
            v = spec.parse(args)
        except ValueError as e:
            raise Unsupported(str(e))
        kind = spec.primary_kind()
        out, parent = None, None
        for a, x, (sec, i, sub) in list(spec.items(v)):
            if a.kind in registry.DATABASES and core.VAR.search(x):
                raise Unsupported("a database name with a loop variable (%s)" % x)
            new = x
            if a.kind in registry.PRIMARY:
                out = x
                if kind == "db" or (kind == "db_maybe" and self.abs(x) in self.files):
                    parent = self.state_of(x, s, True)
                new = "@"
            elif a.kind == "db_in":
                new = "@" + self.files[self.abs(x)] if self.abs(x) in self.files else self.rel(x)
            elif a.kind == "glob":
                new = self.rel(x)
            if sub is None:
                v[sec][i] = new
            else:
                v[sec][i][sub] = new
        return spec.build(v), out, parent

    def step(self, s, name, args, env):
        argv, out, parent = self.bind(s, name, args)
        c = core.command(name, argv, self.env_for(registry.BY_NAME[name], env))
        i = self.add(core.node(core.new_id(self.fl, name, argv), "step", parent=parent, cmd=c))
        self.files[self.abs(out)] = i

    def plot(self, s, name, args):
        args = [a for a in args if a != "-k"]
        if len(args) < 3:
            raise Unsupported("%s needs out.pdf in.jks and commands" % name)
        out, db, cmds = args[0], args[1], args[2:]
        if not out.endswith(".pdf"):
            raise Unsupported("the figure %s is not a .pdf" % out)
        parent = self.state_of(db, s, False)
        base = re.sub(r"[^A-Za-z0-9_.-]", "_", os.path.splitext(os.path.basename(out))[0])
        self.add(core.node(core.unique_id(self.fl, "plot." + base), "plot", parent=parent,
                           plot={"script": name, "out": self.rel(out), "cmds": cmds}))

    def loop(self, s):
        # nested for loops whose innermost body holds the jks_* calls of one database
        levels, body = [], None
        cur, names = s, []
        while True:
            level = self.loop_level(cur, names)
            levels.append(level)
            names += level["vars"]
            inner = cur.body
            if len(inner) == 1 and isinstance(inner[0], for_stmt):
                cur = inner[0]
                continue
            body = inner
            break
        if body and isinstance(body[0], cmd_stmt) and self.is_read(body[0], levels[-1]):
            r = [self.expand(wd) for wd in body[0].words[2:]]
            levels[-1]["row"] = levels[-1]["vars"][0]
            levels[-1]["vars"] = r
            names = [x for l in levels for x in l["vars"]]
            body = body[1:]
        cmds, db, skipped = [], None, []
        for b in body:
            if not isinstance(b, cmd_stmt) or not b.words:
                raise Unsupported("the loop body may only hold jks_* calls")
            name = self.expand(b.words[0])
            if name in core.PLOTTERS or (name.startswith("jks_") and name not in registry.BY_NAME) or name in IGNORED:
                skipped.append(name)
                continue
            if name not in registry.BY_NAME:
                raise Unsupported("%s in the loop body is not a jks script" % name)
            spec = registry.BY_NAME[name]
            if spec.primary_kind() == "db_new":
                raise Unsupported("%s writes a new database; only in-place steps can be looped" % name)
            args = [x for wd in b.words[1:] for x in self.expand_words(wd, names)]
            env = dict((k, self.expand(v, names)) for k, v in b.assigns)
            argv, out, parent = self.bind(b, name, args, names)
            if db is not None and self.abs(out) != db:
                raise Unsupported("the loop body writes several databases (%s and %s)" % (db, self.abs(out)))
            db, start = self.abs(out), parent
            cmds.append(core.command(name, argv, self.env_for(spec, env)))
        if not cmds:
            raise Unsupported("the loop runs no jks_* step")
        if skipped:
            self.note(s, "inside the loop, %s skipped (plots and printing are not repeated in flows)" %
                      ", ".join(sorted(set(skipped))), keep=True)
        plain = [re.sub(r"[.]?\$\{?[A-Za-z_][A-Za-z0-9_]*\}?", "", a) for a in cmds[0].argv]
        i = self.add(core.node(core.new_id(self.fl, cmds[0].name, plain), "loop", parent=start,
                               loops=levels, body=cmds))
        self.files[db] = i

    def is_read(self, b, level):
        # read -r a b <<< "$row" as the first line of a row loop
        w = [x.literal() for x in b.words]
        return (len(w) >= 3 and w[0] == "read" and w[1] == "-r" and len(level["vars"]) == 1 and b.redirect)

    def loop_level(self, s, outer):
        words = []
        for wd in s.values:
            if len(wd.parts) == 1 and wd.parts[0][0] == "cmd":
                t = wd.parts[0][1].split()
                if t and t[0] == "seq" and 2 <= len(t) <= 4 and all(re.fullmatch(r"-?\d+", x) for x in t[1:]):
                    if len(s.values) != 1:
                        raise Unsupported("$(seq ...) mixed with other loop values")
                    return {"vars": [s.var], "kind": "seq", "seq": [int(x) for x in t[1:]]}
                raise Unsupported("loop values from $(%s)" % wd.parts[0][1])
            for x in self.expand_words(wd):
                if core.VAR.search(x):
                    raise Unsupported("loop values that depend on another loop")
                words.append(x)
        return {"vars": [s.var], "kind": "words", "words": words}

    def lists(self):
        # a word list used by several loops becomes a list node (edit it in one place)
        use = {}
        for n in self.fl.nodes.values():
            for l in n.loops:
                if l["kind"] == "words" and len(l["vars"]) == 1:
                    use.setdefault(tuple(l["words"]), []).append((n, l))
        made = {}
        for words, where in use.items():
            if len(where) < 2 or any(re.search(r"\s", w) or w == "" for w in words):
                continue
            i = core.unique_id(self.fl, where[0][1]["vars"][0] + "s")
            made[i] = core.node(i, "list", values=list(words))
            self.fl.nodes = dict(list({i: made[i]}.items()) + list(self.fl.nodes.items()))
            for n, l in where:
                l.pop("words")
                l.update(kind="list", list=i)
        return list(made)


def is_driver(path):
    # a bash script calling jks scripts that is not a flow (an mk driver to import)
    if path.endswith((".jks", "~")) or not os.path.isfile(path) or os.path.getsize(path) > 1 << 20:
        return False
    try:
        with open(path, "rb") as f:
            text = f.read(1 << 16).decode()
    except (OSError, UnicodeDecodeError):
        return False
    return core.FORMAT not in text[:200] and (path.endswith(".sh") or text.startswith("#!")) and \
        core.SCRIPT_NAME.search(text) is not None


def _quote_state(text):
    # the quote each character is in (None, ' or ")
    out, q, i = [], None, 0
    while i < len(text):
        c = text[i]
        if q is None and c == "\\":
            out += [None, None]
            i += 2
            continue
        if q is None and c in "'\"":
            q = c
        elif c == q and not (q == '"' and i > 0 and text[i - 1] == "\\"):
            q = None
            out.append(c)
            i += 1
            continue
        out.append(q)
        i += 1
    return out + [None]


def import_mk(mk, flow_path):
    # -> (flow, report [(line, text)], files {path: node}, lists made)
    im = importer(mk, flow_path).run()
    made = im.lists()
    im.fl.reorder()  # checks every node once more
    return im.fl, im.report, dict((os.path.relpath(p, im.fl.base), i) for p, i in im.files.items()), made
