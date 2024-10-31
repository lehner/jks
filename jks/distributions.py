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
import scipy.special


# p-value
def p_value_right_tail(chi2, dof):
    return 1.0 - scipy.special.gammainc(dof / 2.0, chi2 / 2.0)


def p_value_left_tail(chi2, dof):
    return 1.0 - p_value_right_tail(chi2, dof)


def p_value(chi2, dof):
    # if chi2 > dof:
    return p_value_right_tail(chi2, dof)
    # else:
    #    return p_value_left_tail(chi2,dof)
