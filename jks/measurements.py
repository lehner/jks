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
import math
import random
import numpy
import sys
import copy


#
# Helper
#
def _read_files(fns, prepare):
    # read lines
    if prepare == None:
        data = [
            [[float(v) for v in l.split(" ") if v != ""] for l in open(f).readlines()]
            for f in fns
        ]
    else:
        data = [
            prepare(
                [
                    [float(v) for v in l.split(" ") if v != ""]
                    for l in open(f).readlines()
                ]
            )
            for f in fns
        ]

    return data


#
# Measurements
#
class measurements:

    #
    # Data type
    #
    np_datatype = numpy.float64

    # self.data is array of array
    #
    # Examples:
    #  data = [0,2,3,5,1]
    #  data = [ [0,1],  [2,1],  [3,1],  [4,2] ]
    #  data = "filename"
    #  data = [ "filename1", "filename2" ]
    #
    def __init__(self, data, prepare_file=None):

        # import data from files
        if type(data) == type(""):
            data = _read_files([data], prepare_file)[0]
        elif type(data) == type([]) and len(data) > 0 and type(data[0]) == type(""):
            data = _read_files(data, prepare_file)

        # if data is a dict, save configuration tags
        if type(data) == type({}):
            self.config_tags = sorted(
                list(data.keys())
            )  # should be a list but make sure no future version gives a set
            data = [data[c] for c in self.config_tags]
        else:
            self.config_tags = [("n/a-%6.6d" % i) for i in range(len(data))]
        # no need to save tags if we cannot do a jackknife error
        if len(self.config_tags) == 1:
            self.config_tags = []

        # make python array
        self.projectors = {}
        if type(data) == type([]) and len(data) > 0:
            if type(data[0]) == type([]):
                self._NF = len(data[0])
                self.data = data
            elif type(data[0]) == type({}):
                self._init_projectors(data[0])
                self.data = [self._transform_projected(d) for d in data]
                self._NF = len(self.data[0])
            else:
                self._NF = 1
                self.data = [[d] for d in data]

        else:
            self._NF = 0
            self.data = []

        # make numpy array
        self.ndata = numpy.array(self.data, self.np_datatype)
        self._NR = len(self.data)

    def keys(self):
        return self.projectors.keys()

    def _init_projectors(self, d):
        self.projectors = {}
        n = 0
        for k in sorted(d.keys()):
            l = len(d[k])
            self.projectors[k] = (n, n + l)
            n += l

        self.n_proj_max = n

    def _transform_projected(self, d):
        ret = []
        for k in sorted(self.projectors.keys()):
            ret = ret + d[k]
        return ret

    def proj(self, data, k):
        return data[self.projectors[k][0] : self.projectors[k][1]]

    # skip elements
    def skip(self, nr):
        return self.subset(range(0, self._NR, nr))

    # subset
    def subset(self, r):
        m = measurements([[dd for dd in self.data[i]] for i in r])
        m.projectors = self.projectors
        m.config_tags = [self.config_tags[i] for i in r]
        return m

    # block measurements
    def block(self, size):
        data = []
        if self._NR % size != 0:
            raise Exception(
                "Blocksize must divide number of measurements (%d / %d)"
                % (self._NR, size)
            )
        for i in range(int(self._NR / size)):
            t = numpy.array([0 for ii in range(self._NF)], self.np_datatype)
            for j in range(size):
                t += self.ndata[i * size + j]
            t /= float(size)
            data.append(t.tolist())
        m = measurements(data)
        m.projectors = self.projectors
        return m

    # mean
    def mean(self):
        return numpy.mean(self.ndata, axis=0).tolist()

    # covariance matrix Cij
    def cov(self):
        return numpy.cov(
            m=self.ndata, rowvar=0, ddof=1
        ).tolist()  # unbiased estimate of covariance

    # correlation matrix Pij = Cij / sqrt(Cii * Cjj)
    def cor(self):
        return numpy.corrcoef(
            x=self.ndata, rowvar=0, ddof=1
        ).tolist()  # unbiased estimate of covariance

    # central moments (not necessarily bias-free, returns numpy array)
    def central_moment_biased(self, n):
        m = numpy.mean(self.ndata, axis=0).tolist()
        return numpy.mean(
            numpy.array([numpy.power(d - m, n) for d in self.ndata], self.np_datatype),
            axis=0,
        )

    # second central moment (bias free)
    def cm2(self):
        N = float(self._NR)
        return ((N / (N - 1)) * self.central_moment_biased(2)).tolist()

    # third central moment (bias free)
    def cm3(self):
        N = float(self._NR)
        return ((N**2 / (N - 1) / (N - 2)) * self.central_moment_biased(3)).tolist()

    # fourth and second central moment squared (bias free), returns (cm4,cm2^2) tupel
    def cm4(self):
        N = float(self._NR)
        I4 = self.central_moment_biased(4)
        I22 = self.central_moment_biased(2) ** 2.0
        d0 = N**2 - 5 * N + 6
        cm4 = (
            N * (9 - 6 * N) / (N - 1) / d0 * I22
            + N * (3 - 2 * N + N**2) / (N - 1) / d0 * I4
        )
        cm2sqr = N * (3 - 3 * N + N**2) / (N - 1) / d0 * I22 - N / d0 * I4
        return (cm4.tolist(), cm2sqr.tolist())

    # statistics beyond the central limit theorem up to order in 1/sqrt{N}
    def ci(self):
        cm2 = self.cm2()
        cm3 = self.cm3()
        cm4, cm2sqr = self.cm4()

        N = len(cm4)
        sigma = [math.sqrt(cm2[i]) for i in range(N)]
        del3 = cm3
        del4 = [cm4[i] - 3.0 * cm2sqr[i] for i in range(N)]  # this is unbiased
        del3sqr = [
            cm3[i] ** 2 for i in range(N)
        ]  # TODO: should use unbiased estimator of cm3sqr

        # the following is biased but there is no unbiased estimator
        L1_1sigma = [0.274787 * del3[i] / cm2[i] for i in range(N)]
        L1_2sigma = [1.73151 * del3[i] / cm2[i] for i in range(N)]

        L2_1sigma = [
            0.212683 * del3sqr[i] / math.pow(sigma[i], 5.0)
            - 0.08333333 * del4[i] / math.pow(sigma[i], 3.0)
            for i in range(N)
        ]
        L2_2sigma = [
            2.17095 * del3sqr[i] / math.pow(sigma[i], 5.0)
            + 0.08333333 * del4[i] / math.pow(sigma[i], 3.0)
            for i in range(N)
        ]

        # construct return values
        left_err1_0 = [-sigma[i] for i in range(N)]
        left_err1_1 = [left_err1_0[i] + L1_1sigma[i] for i in range(N)]
        left_err1_2 = [left_err1_1[i] - L2_1sigma[i] for i in range(N)]

        left_err2_0 = [-2.0 * sigma[i] for i in range(N)]
        left_err2_1 = [left_err2_0[i] + L1_2sigma[i] for i in range(N)]
        left_err2_2 = [left_err2_1[i] - L2_2sigma[i] for i in range(N)]

        right_err1_0 = [sigma[i] for i in range(N)]
        right_err1_1 = [right_err1_0[i] + L1_1sigma[i] for i in range(N)]
        right_err1_2 = [right_err1_1[i] + L2_1sigma[i] for i in range(N)]

        right_err2_0 = [2.0 * sigma[i] for i in range(N)]
        right_err2_1 = [right_err2_0[i] + L1_2sigma[i] for i in range(N)]
        right_err2_2 = [right_err2_1[i] + L2_2sigma[i] for i in range(N)]

        return [
            [
                (left_err1_0, right_err1_0),
                (left_err1_1, right_err1_1),
                (left_err1_2, right_err1_2),
            ],
            [
                (left_err2_0, right_err2_0),
                (left_err2_1, right_err2_1),
                (left_err2_2, right_err2_2),
            ],
        ]

    #
    # auto-correlator
    #
    # parameter delta can be a single delta or a list of deltas
    #
    # the following is a biased estimate (http://en.wikipedia.org/wiki/Autocorrelation#Estimation)
    #
    def ac(self):
        # calculate for single value
        ret = []
        m = self.mean()
        for j in range(self._NF):
            t = self.ndata[:, j] - m[j]
            c = numpy.correlate(t, t, "full")[t.size - 1 :]
            ret.append(c / c[0])
        return [[ret[j][i] for j in range(self._NF)] for i in range(self._NR)]

    #
    # auto-correlation time (time: index in data series)
    #
    # integrates up to a relative change of 1%
    #
    # TODO: find a more pythonic way of writing the code below
    #
    def act(self):
        ac = self.ac()
        delta = 0
        sum = [0 for i in range(self._NF)]
        while delta < self._NR / 2:
            val = ac[delta]
            delta += 1
            tot_rel = 0
            for i in range(self._NF):
                sum[i] += val[i]
                tot_rel += val[i] * val[i] / (sum[i] * sum[i])
            if math.sqrt(tot_rel) < 0.01:
                break
        return sum

    #
    # return a resample of the current measurements
    #
    def resample(self):
        N = self._NR
        return self.subset([random.randint(0, self._NR - 1) for i in range(N)])

    #
    # eliminate
    #
    def eliminate(self, i0, i1=0):
        a = list(range(self._NR))
        if i1 == 0:
            i1 = i0 + 1
        for i in reversed(range(i0, i1)):
            a.pop(i)
        return self.subset(a)

    #
    # jackknife estimates
    #
    class _jackknife:
        # set
        class _jk_resamples:
            def __init__(self, phi, jk=None):
                if jk == None:
                    self.orig = numpy.array(phi["orig"])
                    self.blocks = numpy.array(phi["blocks"])
                    self.tags = phi["tags"]
                    self.info = phi["info"]
                    assert len(self.blocks) == len(self.tags)
                else:
                    self.orig = numpy.array(phi(jk.master))
                    if jk.N > 1:
                        self.blocks = numpy.array(
                            [
                                phi(
                                    jk.master.eliminate(
                                        i * jk.blocksize, (i + 1) * jk.blocksize
                                    )
                                )
                                for i in range(jk.N)
                            ]
                        )
                    else:
                        self.blocks = numpy.array([])
                    self.tags = jk.master.config_tags
                    assert len(self.tags) == len(self.blocks)
                    assert len(list(filter(lambda x: x[0] == "!", self.tags))) == 0
                    self.info = {}
                self.N = len(self.blocks)
                self._clone_type_str = "measurements._jackknife._jk_resamples"

            def expand(self, all_tags):
                new_blocks = []
                idx = dict([(self.tags[i], i) for i in range(len(self.tags))])

                for i in range(len(all_tags)):
                    t = all_tags[i]
                    if t in idx:
                        new_blocks.append(self.blocks[idx[t]])
                    else:
                        new_blocks.append(self.orig)

                self.blocks = numpy.array(new_blocks)
                self.tags = all_tags
                self.hash_tags = hash(tuple(self.tags))
                self.N = len(self.blocks)

            def addvar(self, tag, data, desc):
                phi = {
                    "orig": self.orig,
                    "blocks": copy.copy(self.blocks),
                    "tags": copy.copy(self.tags),
                    "info": copy.copy(self.info),
                }

                etag = "!" + tag
                if etag not in phi["tags"]:
                    phi["tags"].append(etag)

                    if len(phi["blocks"]) == 0:
                        phi["blocks"] = numpy.array([data])
                    else:
                        phi["blocks"] = numpy.append(phi["blocks"], [data], axis=0)
                else:
                    phi["blocks"][phi["tags"].index(etag)] = data
                phi["info"][tag] = desc
                return measurements._jackknife._jk_resamples(phi)

            def vars(self):
                return [y[1:] for y in filter(lambda x: x[0] == "!", self.tags)]

            def mean(self):
                return self.orig

            def measurements(self):
                # this only does the statistical average, i.e., over tags that do not start with "!"
                phiN = numpy.array(self.orig, measurements.np_datatype)
                return measurements(
                    [
                        (
                            numpy.array(self.blocks[i], measurements.np_datatype) - phiN
                        ).tolist()
                        for i in range(self.N)
                        if self.tags[i][0] != "!"
                    ]
                )

            def scaled_measurements(self):
                # this only does the statistical average, i.e., over tags that do not start with "!"
                blocks = [i for i in range(self.N) if self.tags[i][0] != "!"]
                N = float(len(blocks))
                phiN = numpy.array(self.orig, measurements.np_datatype)
                r = measurements(
                    [
                        (
                            N * phiN
                            - (N - 1)
                            * numpy.array(self.blocks[i], measurements.np_datatype)
                        ).tolist()
                        for i in blocks
                    ]
                )
                r.config_tags = [t for t in self.tags]
                return r

            def bias(self):
                m = self.measurements()
                return (
                    numpy.array(m.mean(), measurements.np_datatype) * (m._NR - 1)
                ).tolist()

            def cov(self, var=None):
                if var == None:
                    # return ((self.N-1)**2.0/self.N*numpy.array(self.measurements().cov(), measurements.np_datatype)).tolist(), this one is correct and bias free for primary observables
                    sm = self.measurements()
                    if sm._NR == 0:
                        return [
                            [0.0 for i in range(len(self.orig))]
                            for j in range(len(self.orig))
                        ]
                    res = (
                        (sm._NR - 1) * numpy.array(sm.cov(), measurements.np_datatype)
                    ).tolist()
                else:
                    evar = "!" + var
                    assert evar in self.tags
                    res = (
                        4.0
                        * numpy.cov(
                            m=numpy.array(
                                [self.orig, self.blocks[self.tags.index(evar)]],
                                measurements.np_datatype,
                            ),
                            rowvar=0,
                            ddof=0,
                        )
                    ).tolist()
                if type(res) != type([]):
                    res = [[res]]
                return res

            def tcov(self):
                res = numpy.array(self.cov())
                for v in self.vars():
                    res = res + numpy.array(self.cov(v))
                res = res.tolist()
                if type(res) != type([]):
                    res = [[res]]
                return res

        # by default single elimination jackknife
        def __init__(self, master, blocksize):
            self.master = master
            if master._NR % blocksize != 0:
                raise Exception(
                    "Blocksize must divide number of measurements (%d / %d)"
                    % (master._NR, blocksize)
                )
            self.N = int(master._NR / blocksize)
            self.blocksize = blocksize

        # prepare
        def prepare(self, phi):
            return measurements._jackknife._jk_resamples(phi, self)

        # estimate the bias
        def bias(self, phi):  # = phiBAR - phiBAR_biascorrected
            return (
                (self.N - 1)
                * numpy.array(
                    self.prepare(phi).measurements().mean(), measurements.np_datatype
                )
            ).tolist()

        # estimate the covariance
        def cov(self, phi):  # equivalent to (N-1)/N \sum_i (phi_i - 1/n \sum_j phi_j)^2
            return self.prepare(phi).cov()

        # pseudoensemble used (apart from rescaling factor)
        def pe(self, phi):  # 1/(n-1)*\sum_i ( pe_i - <pe> )^2 = cov()
            phiN = numpy.array(phi(self.master), measurements.np_datatype)
            return [
                phiN
                + (self.N - 1)
                * (
                    phiN
                    - phi(
                        self.master.eliminate(
                            i * self.blocksize, (i + 1) * self.blocksize
                        )
                    )
                )
                / math.sqrt(self.N - 1)
                for i in range(self.N)
            ]

        # TODO: add estimator of higher moments (3,4)
        # TODO: option to save jackknife samples and load them

    #
    # jackknife instance
    #
    def jackknife(self, blocksize=1):
        return measurements._jackknife(self, blocksize)

    #
    # bootstrap estimates
    #
    class _bootstrap:
        # init
        def __init__(self, master, Npseudoexperiments):
            self.master = master
            self.Npe = Npseudoexperiments

        # helper
        def cov(self, fnc):
            return measurements(self.pe(fnc)).cov()

        # pseudoensemble
        def pe(self, fnc):
            return [fnc(self.master.resample()) for i in range(self.Npe)]

    #
    # bootstrap instance
    #
    def bootstrap(self, Npseudoexperiments):
        return measurements._bootstrap(self, Npseudoexperiments)


#
# Manual jackknife
#
def jackknife(orig, blocks, tags=None, info=None):
    if tags == None:
        tags = ["c%d" % i for i in range(len(blocks))]
    if info == None:
        info = tags
    return measurements._jackknife._jk_resamples(
        {"orig": orig, "blocks": blocks, "tags": tags, "info": info}
    )
