#
#    JKS - Measurement database system
#    Copyright (C) 2024  Christoph Lehner (christoph.lehner@ur.de, https://github.com/lehner/jks)
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
import lz4.frame

# import h5py
import math
import random
import numpy
import datetime
import time
import socket
import sys
import os
import pickle
import fnmatch
from stats.measurements import measurements

t0 = 0
t1 = 0
t2 = 0


# Resamples
class resamples:
    def __init__(self, fn=None):
        self.set = {}
        self.N = None
        self.tags = None
        self.info = None
        if fn != None:
            self.load(fn)

    def add(self, n, s):
        if self.N == None:
            self.N = s.N
            self.tags = s.tags
            self.info = s.info
            self._clone_type_str = s._clone_type_str
            self.set[n] = s
        else:
            assert self._clone_type_str == s._clone_type_str
            all_tags = sorted(set(self.tags) | set(s.tags))

            # Adding more measurements of existing n not possible beyond
            # primary data.
            # How do we go from f(1/n sum_{i=1}^n x_i) and f(1/m sum_{i=1}^m y_i)
            # to f(1/(n+m) (\sum_i x_i + \sum_j y_j)) ?
            assert n not in self.set

            # Do I need to update existing tags to make room for new tags required by s?
            update_existing_tags = all_tags != self.tags

            self.N = len(all_tags)
            self.tags = all_tags

            for t in s.info:
                if t not in self.info:
                    self.info[t] = s.info[t]
                elif self.info[t] != s.info[t]:
                    # print("Merge ", self.info[t], s.info[t])
                    if len(self.info[t]) > 1024:
                        self.info[t] = self.info[t][0:1024] + "..."
                    self.info[t] = self.info[t] + "\n" + s.info[t]
            s.info = self.info

            # Enlarge all existing sets if needed
            if update_existing_tags:
                for nn in self.set:
                    if self.set[nn].tags != self.tags:
                        self.set[nn].expand(self.tags)

            # Enlarge to-be-added
            if s.tags != self.tags:
                s.expand(self.tags)

            self.set[n] = s

    def add_gaussian(self, n, m, e):
        fnc = self._clone_type_fnc()
        # TODO: add new tags
        self.set[n] = fnc(
            m, [random.gauss(m, e / math.sqrt(self.N - 1)) for i in range(self.N)]
        )

    def cut(self, i, keep_fixed=None):
        if i == -1:
            return dict([(t, self.set[t].orig) for t in self.set.keys()])
        else:
            if keep_fixed != None:
                return dict(
                    [
                        (
                            t,
                            (
                                self.set[t].blocks[i]
                                if t not in keep_fixed
                                else self.set[t].orig
                            ),
                        )
                        for t in self.set.keys()
                    ]
                )
            else:
                return dict([(t, self.set[t].blocks[i]) for t in self.set.keys()])

    def _clone_type_fnc(self):
        return eval(
            "lambda a,b,c,d: "
            + self._clone_type_str
            + "({ 'orig' : a, 'blocks' : b, 'tags' : c, 'info' : d })"
        )

    def apply(self, phi, keep_fixed=None, scale=1.0):
        f = self._clone_type_fnc()
        if scale == 1.0:
            return f(
                phi(self.cut(-1)),
                [phi(self.cut(i, keep_fixed)) for i in range(self.N)],
                self.tags,
                self.info,
            )
        else:
            x = self.cut(-1)
            y = numpy.array(phi(x))
            yi0 = [
                phi(
                    dict(
                        [
                            (
                                t,
                                (numpy.array(xi) - numpy.array(x[t])) * scale
                                + numpy.array(x[t]),
                            )
                            for t, xi in self.cut(i, keep_fixed).items()
                        ]
                    )
                )
                for i in range(self.N)
            ]
            yi = [(numpy.array(yi0[i]) - y) / scale + y for i in range(self.N)]
            return f(y, yi, self.tags, self.info)

    def get(self, n):
        return self.set[n]

    def take(self, other, pat):
        for n in other.set:
            if fnmatch.fnmatch(n, pat):
                self.add(n, other.get(n))

    def keys(self):
        return self.set.keys()

    def match(self, pat):
        return [k for k in self.set if fnmatch.fnmatch(k, pat)]

    def save(self, fn, compress=True):

        t0 = time.time()
        s = {
            "N": self.N,
            "set": {},
            "_clone_type_str": self._clone_type_str,
            "tags": self.tags,
            "info": self.info,
            "origin": {
                "argv": sys.argv,
                "pwd": os.getcwd(),
                "hostname": socket.gethostname(),
                "user": os.getlogin(),
                "date": str(datetime.datetime.now()),
                "argv[0].mtime": str(
                    datetime.datetime.fromtimestamp(os.path.getmtime(sys.argv[0]))
                ),
            },
        }
        for f in self.set:
            s["set"][f] = {
                "orig": self.set[f].orig,
                "blocks": self.set[f].blocks,
                "N": self.set[f].N,
            }

        t1 = time.time()

        if compress:
            with lz4.frame.open(fn, mode="wb") as f:
                pickle.dump(s, f, pickle.HIGHEST_PROTOCOL)
        else:
            with open(fn, "wb") as f:
                pickle.dump(s, f, pickle.HIGHEST_PROTOCOL)
        # jksIO.save(fn,s)
        t2 = time.time()
        # print "Time: %g(prep) %g(wr)" % (t1-t0,t2-t1)

    def load(self, fn, pre=""):
        assert self.N == None
        try:
            with lz4.frame.open(fn, mode="rb") as f:
                s = pickle.load(f, encoding="latin1", errors="")
        except:
            with open(fn, "rb") as f:
                s = pickle.load(f, encoding="latin1", errors="")
        #
        self.N = s["N"]
        if "tags" in s:
            self.tags = s["tags"]
        else:
            # old versions did not save tags
            self.tags = ["n/a-%6.6d" % i for i in range(self.N)]
        if "info" in s:
            self.info = s["info"]
        else:
            self.info = {}
        self._clone_type_str = s["_clone_type_str"]
        fnc = self._clone_type_fnc()
        for f in s["set"]:
            self.set[pre + f] = fnc(
                s["set"][f]["orig"], s["set"][f]["blocks"], self.tags, self.info
            )

    def used(self):
        used = set([])
        for f in self.set:
            o = numpy.nan_to_num(self.set[f].orig)
            b = numpy.nan_to_num(self.set[f].blocks)
            for i in range(len(b)):
                if not numpy.array_equal(o, b[i]):
                    used.add(i)
        return list(used)

    def compress(self, verbose=False):
        used = sorted(self.used())
        N = len(used)
        for i in range(len(self.tags)):
            if i not in used:
                if self.tags[i][0] == "!":
                    t = self.tags[i][1:]
                    del self.info[t]
                    if verbose:
                        print("Delete variation", t)
                else:
                    if verbose:
                        print("Delete config", self.tags[i])
        self.tags = [self.tags[i] for i in used]
        self.N = N
        for f in self.set:
            self.set[f].blocks = [self.set[f].blocks[i] for i in used]
            self.set[f].N = N
            self.set[f].tags = self.tags

    def prepend_tags(self, pre):
        self.tags = [pre + t if t[0] != "!" else t for t in self.tags]

    def summary(self, phi):
        rss = self.apply(phi)
        mn = rss.mean()
        cv0 = rss.cov()
        res = {}
        for k in self.keys():
            rss = self.apply(phi, [k])
            cvk = rss.cov()
            if cvk != cv0:
                res[cvk] = k
        sk = sorted(res.keys())
        print("----------------------------------")
        print(" Summary of error contributions ")
        print("----------------------------------")
        print(" - %g original" % math.sqrt(cv0))
        for s in sk:
            print(" - %g for %s fixed" % (math.sqrt(s), res[s]))
        print("----------------------------------")
