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
import sys, os, struct, binascii, fnmatch, numpy


class writer:
    def __init__(self, fn):
        self.f = open(fn, "w+b")

    def write(self, t, cc):
        if self.f is not None:
            self.f.write(struct.pack("i", len(t) + 1))
            self.f.write((t + "\0").encode("utf-8"))
            ln = len(cc)
            ccr = [fff for sublist in ((c.real, c.imag) for c in cc) for fff in sublist]
            bindata = struct.pack("d" * 2 * ln, *ccr)
            crc32comp = binascii.crc32(bindata) & 0xFFFFFFFF
            self.f.write(struct.pack("II", crc32comp, ln))
            self.f.write(bindata)
            self.f.flush()

    def close(self):
        if self.f is not None:
            self.f.close()
            self.f = None


def count(fn):
    n = 0
    f = open(fn, "rb")
    while True:
        rd = f.read(4)
        if len(rd) == 0:
            break
        ntag = struct.unpack("i", rd)[0]
        f.read(ntag)
        (crc32, ln) = struct.unpack("II", f.read(4 * 2))

        f.read(16 * ln)
        n += 1
    f.close()
    return n


def tags(fn, filter=lambda x: x):
    n = 0
    tags = []
    f = open(fn, "rb")
    while True:
        rd = f.read(4)
        if len(rd) == 0:
            break
        ntag = struct.unpack("i", rd)[0]
        tag = f.read(ntag).decode("utf-8")[0:-1]
        (crc32, ln) = struct.unpack("II", f.read(4 * 2))

        data = f.read(16 * ln)

        crc32comp = binascii.crc32(data) & 0xFFFFFFFF

        if crc32comp != crc32:
            raise Exception("Data corrupted!")

        corr = numpy.frombuffer(data, dtype=numpy.complex128, count=ln)

        x = filter(tag, corr)
        if x is not None:
            tags.append(x)
    f.close()
    return tags


class reader:
    def __init__(self, fn):
        self.tags = {}
        self.ntags = {}
        f = open(fn, "r+b")
        while True:
            rd = f.read(4)
            if len(rd) == 0:
                break
            ntag = struct.unpack("i", rd)[0]
            tag = f.read(ntag).decode("utf-8")
            (crc32, ln) = struct.unpack("II", f.read(4 * 2))

            data = f.read(16 * ln)
            crc32comp = binascii.crc32(data) & 0xFFFFFFFF

            if crc32comp != crc32:
                raise Exception("Data corrupted!")

            nt = tag[0:-1]
            self.tags[nt] = numpy.frombuffer(data, dtype=numpy.complex128, count=ln)
            if nt not in self.ntags:
                self.ntags[nt] = 1
            else:
                self.ntags[nt] += 1
        f.close()

    def glob(self, pattern):
        return filter(lambda k: fnmatch.fnmatch(k, pattern), self.tags.keys())
