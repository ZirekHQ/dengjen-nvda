# coding: utf-8

# Copyright (c) 2023 Musharraf Omer
# This file is covered by the GNU General Public License.

"""NVDA discovers this add-on's synth driver by importing this package and
reading `SynthDriver` at the top level (synthDriverHandler.getSynth) -- this
re-export is load-bearing, not decorative."""

from .adapters.nvda.synth_driver import SynthDriver

__all__ = ["SynthDriver"]
