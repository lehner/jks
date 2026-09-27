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
# Signatures of the jks_* scripts, no GUI dependencies.
#
# argv[1:] of a script is  head + repeat * k + tail + optional[:j]  with k >= 1 if
# the script has a repeat group (then it has no optional arguments) and
# 0 <= j <= len(optional).  All values are kept as the exact argv strings.
#
# Argument kinds:
#   db        database modified in place (the primary database)
#   db_new    database written from scratch (primary; any old file is replaced)
#   db_maybe  database modified in place, created if missing (primary)
#   db_in     database read only
#   glob      external input files (shell pattern, expanded by the script)
#   tag_in    existing tag            tag_out    new tag
#   tags_out  python list of new tags
#   pattern   fnmatch pattern of tags
#   weights   python list, int t -> exp(-t omega), string -> tag on the grid
#   expr      python expression (jks_add: of r[tag])
#   value     other python expression (list, guess, ranges)
#   int, float, str
#
import os, re, shlex, shutil

PRIMARY = ("db", "db_new", "db_maybe")
DATABASES = PRIMARY + ("db_in",)


class arg:
    def __init__(self, name, kind, help="", default=None):
        self.name, self.kind, self.help, self.default = name, kind, help, default


class script:
    def __init__(self, name, group, help, head=(), repeat=(), tail=(), optional=(),
                 env=(), produces=None):
        self.name, self.group, self.help = name, group, help
        self.head, self.repeat, self.tail = list(head), list(repeat), list(tail)
        self.optional = list(optional)
        assert not (self.repeat and self.optional)
        self.env = list(env)  # (variable, help)
        self.produces = produces  # values -> list of tag names or fnmatch patterns

    def args(self):
        return self.head + self.repeat + self.tail + self.optional

    def primary(self):
        # (section, index) of the database the script writes
        for sec in ("head", "tail"):
            for i, a in enumerate(getattr(self, sec)):
                if a.kind in PRIMARY:
                    return sec, i
        raise ValueError("%s writes no database" % self.name)

    def primary_kind(self):
        sec, i = self.primary()
        return getattr(self, sec)[i].kind

    def parse(self, argv):
        # argv without the script name -> values
        n, fixed = len(argv), len(self.head) + len(self.tail)
        if self.repeat:
            g = len(self.repeat)
            if n < fixed + g or (n - fixed) % g != 0:
                raise ValueError("%s: expected %d + %d*k arguments, got %d" % (self.name, fixed, g, n))
            k = (n - fixed) // g
            h, r, t = argv[: len(self.head)], argv[len(self.head) : len(self.head) + k * g], argv[n - len(self.tail) :]
            return {"head": list(h), "repeat": [list(r[i * g : (i + 1) * g]) for i in range(k)],
                    "tail": list(t), "optional": []}
        if not fixed <= n <= fixed + len(self.optional):
            raise ValueError("%s: expected %d to %d arguments, got %d" % (self.name, fixed, fixed + len(self.optional), n))
        return {"head": list(argv[: len(self.head)]), "repeat": [],
                "tail": list(argv[len(self.head) : fixed]), "optional": list(argv[fixed:])}

    def build(self, values):
        v = values
        assert len(v["head"]) == len(self.head) and len(v["tail"]) == len(self.tail)
        assert all(len(r) == len(self.repeat) for r in v["repeat"])
        assert not self.repeat or len(v["repeat"]) >= 1
        assert len(v["optional"]) <= len(self.optional)
        return list(v["head"]) + [x for r in v["repeat"] for x in r] + list(v["tail"]) + list(v["optional"])

    def empty(self):
        return {"head": [a.default or "" for a in self.head],
                "repeat": [[a.default or "" for a in self.repeat]] if self.repeat else [],
                "tail": [a.default or "" for a in self.tail], "optional": []}

    def items(self, values):
        # (arg, value, (section, index, sub)) in argv order
        for i, a in enumerate(self.head):
            yield a, values["head"][i], ("head", i, None)
        for k, r in enumerate(values["repeat"]):
            for j, a in enumerate(self.repeat):
                yield a, r[j], ("repeat", k, j)
        for i, a in enumerate(self.tail):
            yield a, values["tail"][i], ("tail", i, None)
        for i, x in enumerate(values["optional"]):
            yield self.optional[i], x, ("optional", i, None)

    def get_primary(self, values):
        sec, i = self.primary()
        return values[sec][i]

    def set_primary(self, values, path):
        sec, i = self.primary()
        values = {k: [list(x) if isinstance(x, list) else x for x in v] for k, v in values.items()}
        values[sec][i] = path
        return values

    def databases_in(self, values):
        return [x for a, x, _ in self.items(values) if a.kind == "db_in"]

    def globs(self, values):
        return [x for a, x, _ in self.items(values) if a.kind == "glob"]

    def tags_out(self, values):
        # tag names and fnmatch patterns this step is expected to write
        out = []
        for a, x, _ in self.items(values):
            if a.kind == "tag_out":
                out.append(x)
            elif a.kind == "tags_out":
                out += re.findall(r"""['"]([^'"]+)['"]""", x)
        if self.produces:
            out += self.produces(values)
        return out

    def tags_in(self, values):
        # tags the step reads from the primary database (best effort for expressions)
        out = []
        for a, x, _ in self.items(values):
            if a.kind == "tag_in":
                out.append(x)
            elif a.kind == "expr":
                out += re.findall(r"""r\[\s*['"]([^'"]+)['"]\s*\]""", x)
            elif a.kind == "weights":
                out += re.findall(r"""['"]([^'"]+)['"]""", x)
        return out


A = arg
_spectral_in = [A("database", "db"), A("tag_in", "tag_in", "input data, laid out like the input weights"),
                A("weights_in", "weights", "e.g. [14,16,18] or list(range(4,30))"),
                A("weights_out", "weights", "e.g. list(range(40))"),
                A("omega_grid", "tag_in", "grid tag, e.g. omega0")]
_strength = ("JKS_CORRELATION_STRENGTH", "shrinkage of the input correlations toward the diagonal")
_fit_env = [("JKS_FIT_TOL", "fit tolerance"), ("JKS_PVAL", "set to append the p-value"),
            ("JKS_HESSIAN_EPS", "step for the Hessian estimate")]
_gevp_env = [("STATS_KEEP_FIXED", "comma separated tag patterns kept fixed in the resampling")]


def _fit_produces(v):
    return ["%s.%s.input.*" % (v["tail"][1], r[0]) for r in v["repeat"]]


def _gevp_produces(v):
    f = v["head"][4]
    return [f.replace("%s", "*")] if "%s" in f else []


SCRIPTS = [
    script("jks_add", "build", "Add tags computed by python expressions of r[tag] (evaluated on every block).",
           head=[A("database", "db")],
           repeat=[A("tag", "tag_out"), A("expression", "expr", "e.g. [ r['C'][t] * t**4 for t in range(40) ]")]),
    script("jks_add_from", "import", "Copy tags from another database (renaming them); compresses the result.",
           head=[A("database", "db_maybe"), A("from", "db_in")],
           repeat=[A("tag_in", "str", "tag in the other database"), A("tag_as", "tag_out")]),
    script("jks_add_parameter", "build", "Add scalar parameters; a nonzero error becomes a variation named like the parameter.",
           head=[A("database", "db")],
           repeat=[A("name", "tag_out"), A("value", "float"), A("error", "float", default="0")]),
    script("jks_add_sys", "build", "Attach variations to a tag: shift tag's mean as the shifted value.",
           head=[A("database", "db"), A("tag", "tag_in", "tag that receives the variations")],
           repeat=[A("shift_tag", "tag_in"), A("variation", "str", "name of the new variation")]),
    script("jks_rescale_variance", "build", "Rescale the statistical variance of tags (modifies them).",
           head=[A("database", "db")],
           repeat=[A("tag", "tag_in"), A("scales", "str", "variance scale, or per element a;b;c")]),
    script("jks_set_variance", "build", "Scale a tag's fluctuations to a target relative error of one element (modifies it).",
           head=[A("database", "db")],
           repeat=[A("tag", "tag_in"), A("index", "int"), A("rel_err", "float")]),
    script("jks_correlator_reconstruct", "build", "Reconstruct a correlator from energies and overlaps.",
           head=[A("database", "db"), A("out_tag", "str", "results are stored as out_tag.recN"),
                 A("energy_tag", "tag_in"), A("c2_tag", "tag_in"), A("Tmax", "int")],
           produces=lambda v: [v["head"][1] + ".rec*"]),
    script("jks_model_average", "fit", "Model average of fit results.",
           head=[A("database", "db")], repeat=[A("model", "tag_in")],
           tail=[A("index", "int"), A("weight", "str", "aic, chi2 or flat", default="aic"),
                 A("variation", "str", "name of the model-average variation"), A("tag", "tag_out")]),
    script("jks_fit", "fit", "Correlated fit; one or several (tag, ranges, function) triples.",
           head=[A("database", "db")],
           repeat=[A("tag", "tag_in"), A("ranges", "value", "e.g. range(5,20) or [ range(i,20) for i in range(3,8) ]"),
                   A("function", "expr", "of x, p, r, e.g. p[0]*math.exp(-p[1]*x)")],
           tail=[A("guess", "value", "e.g. [1.0,0.5]"), A("fit_tag", "tag_out")],
           env=_fit_env, produces=_fit_produces),
    script("jks_slow_fit", "fit", "Like jks_fit with a slower, more robust minimizer.",
           head=[A("database", "db")],
           repeat=[A("tag", "tag_in"), A("ranges", "value"), A("function", "expr", "of x, p, r")],
           tail=[A("guess", "value"), A("fit_tag", "tag_out")],
           env=_fit_env[:1], produces=_fit_produces),
    script("jks_plsa", "spectral", "Positivity band of int rho w_out given the inputs (stat blocks + !band).",
           head=_spectral_in + [A("tag_out", "tag_out")], optional=[A("dchi2", "float", default="1")],
           env=[_strength]),
    script("jks_blsa", "spectral", "Positivity band with a box prior lower <= rho <= upper.",
           head=_spectral_in + [A("tag_lower", "tag_in"), A("tag_upper", "tag_in"), A("tag_out", "tag_out")],
           optional=[A("dchi2", "float", default="1")], env=[_strength]),
    script("jks_hlt", "spectral", "Hansen-Lupo-Tantalo linear estimate g.C (statistical error only).",
           head=_spectral_in + [A("tag_out", "tag_out"), A("lambda", "float")],
           optional=[A("alpha", "float", default="0"), A("p", "float", default="0")], env=[_strength]),
    script("jks_hlt_kernel", "spectral", "HLT kernels kbar on the grid, one tag per output weight.",
           head=_spectral_in + [A("tags_out", "tags_out", "e.g. ['k6','k8']"), A("lambda", "float")],
           optional=[A("alpha", "float", default="0"), A("p", "float", default="0")], env=[_strength]),
    script("jks_gevp_2pt", "fit", "GEVP of a correlator matrix; writes a new database.",
           head=[A("out", "db_new"), A("in", "db_in"), A("ops", "str", "comma separated operators"),
                 A("fmt_C", "str", "input tag format"), A("fmt_O", "str", "output tag format with %s"),
                 A("dt", "int")],
           optional=[A("jkscale", "float", default="1"), A("lenient_sign", "str", default="1")],
           env=_gevp_env, produces=_gevp_produces),
    script("jks_gevp_2pt_tref", "fit", "GEVP with a reference time; writes a new database.",
           head=[A("out", "db_new"), A("in", "db_in"), A("ops", "str"), A("fmt_C", "str"),
                 A("fmt_O", "str", "output tag format with %s"), A("dt", "int"), A("tref", "int")],
           optional=[A("jkscale", "float", default="1"), A("lenient_sign", "str", default="1")],
           env=_gevp_env, produces=_gevp_produces),
    script("jks_rm", "prune", "Remove tags matching any of the patterns.",
           head=[A("database", "db")], repeat=[A("pattern", "pattern")]),
    script("jks_compress", "prune", "Drop configurations and variations no tag uses; writes a new database.",
           head=[A("in", "db_in"), A("out", "db_new")]),
    script("jks_take", "prune", "New database with the tags matching the patterns; compresses the result.",
           head=[A("out", "db_new"), A("in", "db_in")], repeat=[A("pattern", "pattern")]),
    script("jks_merge", "import", "Merge databases into a new one.",
           head=[A("out", "db_new")], repeat=[A("in", "db_in")]),
    script("jks_tagged_merge", "import", "Merge databases, prefixing each one's tags with prefix/.",
           head=[A("out", "db_new")], repeat=[A("prefix", "str"), A("in", "db_in")]),
    script("jks_create_parameter", "import", "New database with scalar parameters.",
           head=[A("out", "db_new")], repeat=[A("name", "tag_out"), A("value", "float"), A("error", "float", default="0")]),
    script("jks_create_correlator_from_corrfile", "import", "New database from corrIO files, one ensemble per pattern.",
           head=[A("out", "db_new")], repeat=[A("ensemble", "str", "configuration tag prefix"),
                                              A("files", "glob", "one * for the configuration number")]),
    script("jks_create_correlator_from_corrfile_novar", "import", "As jks_create_correlator_from_corrfile (variant).",
           head=[A("out", "db_new")], repeat=[A("ensemble", "str"), A("files", "glob")]),
    script("jks_create_correlator_from_textfile", "import", "New database with one correlator from text files.",
           head=[A("out", "db_new"), A("ensemble", "str"), A("tag", "tag_out"), A("files", "glob")]),
    script("jks_create_correlator_from_multi_textfile", "import", "New database with one correlator from several ensembles of text files.",
           head=[A("out", "db_new"), A("tag", "tag_out")], repeat=[A("ensemble", "str"), A("files", "glob")]),
]

BY_NAME = dict((s.name, s) for s in SCRIPTS)
GROUPS = ["build", "spectral", "fit", "import", "prune"]
ENV_ALL = sorted(set(e for s in SCRIPTS for e, _ in s.env) | {"JKS_DIST", "BIN", "JKS_INFO_HUMAN_READABLE"})


def split_command(line):
    # shell command line -> (env assignments, script name, argv); accepts paths and line continuations
    words = shlex.split(line.replace("\\\n", " "), comments=True)
    env = {}
    while words and re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", words[0]):
        k, v = words.pop(0).split("=", 1)
        env[k] = v
    if not words:
        raise ValueError("empty command")
    name = os.path.basename(words[0])
    if name not in BY_NAME:
        raise ValueError("%s is not a known jks script" % name)
    return env, name, words[1:]


def quote(x):
    # like shlex.quote, but "..." for python code with '...' strings inside
    if "'" in x and not re.search(r'[$`\\"!]', x):
        return '"%s"' % x
    return shlex.quote(x)


def join_command(env, name, argv):
    return " ".join(["%s=%s" % (k, quote(v)) for k, v in sorted(env.items())] +
                    [name] + [quote(x) for x in argv])


def script_path(name):
    # prefer the scripts next to the imported jks package (source tree), then PATH
    import jks
    root = os.path.dirname(os.path.dirname(os.path.abspath(jks.__file__)))
    p = os.path.join(root, "scripts", name)
    if os.path.isfile(p):
        return p
    p = shutil.which(name)
    if p is None:
        raise FileNotFoundError("cannot find %s" % name)
    return p
