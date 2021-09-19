#!/usr/bin/env python3
#
# SPDX-License-Identifier: BSD-2-Clause
#
# Copyright (c) 2021, Datamuseum.DK
# All rights reserved.
#
# Author: Poul-Henning Kamp
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

'''
    Extract data from ICL/METANIC COMET tapes
    =========================================
'''

import os
import sys
import wave
import struct

import crcmod

crcfunc = crcmod.predefined.mkPredefinedCrcFun("crc-16")

# Zero-crossing threshold (not sensitive)
THRESHOLD = 2500

# PLL bit-time averaging
AVG = 2

# Decision threshold as fraction of bit-time
EDGE = 0.72

# A priori sample-rate
BPS = (300 + 150) / 2

class CometTape():

    ''' One logical tape (ie: one track of sound) '''

    def __init__(self, filename, track, debug=False):
        self.filename = filename
        self.fnpfx = filename + ".%d" % track.track_no
        self.track = track
        self.bits = []
        self.records = []
        self.debug = debug

        self.analyze()
        if self.records:
            self.write_tapfile()
            self.write_metafile()

    def analyze(self):
        ''' Analyze zero-crossings into bits '''

        if self.debug:
            dbgfile = open(self.fnpfx + ".snd_", "w")
        else:
            dbgfile = open("/dev/null", "w")

        self.tbit = self.track.rate / BPS

        self.bits = []
        nbr_priv = 0
        nbr = 0
        for nbr, sign in self.track:
            pulse_width = nbr - nbr_priv
            if pulse_width > 4 * self.tbit:
                pulse_width = 0
                self.add_record(nbr)
                if sign == 1:
                    dbgfile.write(
                        "A %d %2d %d %.3f %.3f\n" % (
                            nbr, sign, pulse_width, pulse_width / self.tbit, self.tbit
                        )
                    )
                    nbr_priv = nbr
                    self.bits = ['0']
                    self.tbit = self.track.rate / BPS
                else:
                    dbgfile.write(
                        "B %d %2d %d %.3f %.3f\n" % (
                            nbr, sign, pulse_width, pulse_width / self.tbit, self.tbit
                        )
                    )
            elif pulse_width < EDGE * self.tbit and len(self.bits) > 7:
                dbgfile.write(
                    "C %d %2d %d %.3f %.3f\n" % (
                        nbr, sign, pulse_width, pulse_width / self.tbit, self.tbit
                    )
                )
            else:
                dbgfile.write(
                    "D %d %2d %d %.3f %.3f\n" % (
                        nbr, sign, pulse_width, pulse_width / self.tbit, self.tbit
                    )
                )
                nbr_priv = nbr
                self.tbit += (pulse_width - self.tbit) / AVG
                if sign > 0:
                    self.bits.append('0')
                else:
                    self.bits.append('1')
        self.add_record(nbr)

    def add_record(self, _nbr):
        ''' Turn bits into records '''
        nbits = len(self.bits)
        if nbits < 48:
            self.bits = []
            return
        octets = []
        for i in range(0, len(self.bits), 8):
            octets.append(int("".join(self.bits[i:i+8][::-1]), 2))
        octets = bytearray(octets)
        if not octets[-1]:
            octets = octets[:-1]
        print("RECORD", self.report_record(octets))
        sys.stdout.flush()
        self.records.append(octets)
        self.bits = []

    def report_record(self, octets):
        ''' Summarize a tape record '''
        crc = crcfunc(octets[1:-1])
        text = "%5d bytes" % len(octets)
        text += " ["
        if len(octets) <= 8:
            text += octets.hex()
        else:
            text += octets[:4].hex() + "…" +octets[-4:].hex()
        text += "]"
        if octets[0] != 0xaa:
            text += " Bad_preamble"
        if octets[-1] != 0xaa:
            text += " Bad_postamble"
        if crc:
            text += " Bad_CRC"
        return text

    def write_tapfile(self, filename=None):
        ''' Write a SIMH-TAP file '''
        if filename is None:
            filename = self.filename + ".TAP"
        with open(filename, "wb") as tap:
            for rec in self.records:
                reclen = struct.pack("<L", len(rec))
                tap.write(reclen)
                tap.write(rec)
                if len(rec) & 1:
                    tap.write(b'\x00')
                tap.write(reclen)
            tap.write(b'\xff\xff\xff\xff')

    def ds2089(self,text):
        ''' DS2089 character set '''
        for i, j in (
            ("[", "Æ"),
            ("\\", "Ø"),
            ("]", "Å"),
            ("{", "æ"),
            ("|", "ø"),
            ("}", "å"),
        ):
            text = text.replace(i, j)
        return text

    def interpret_tape_header(self):
        ''' Interpret the tape header (and damn the CRC) '''
        head = self.records[0]
        if head[0] != 0xaa:
            return
        if head[1] != 0:
            return
        if head[2] != 0:
            return
        index = 4
        label = head[index:index+50].decode('ASCII').rstrip()
        yield "Tape label:"
        yield "\t" + label
        index += 50
        index += 13
        yield "File list:"
        while 0x20 < head[index] < 0x6e and index <= len(head) - 29:
            try:
                filename = head[index:index+10].decode('ASCII').rstrip()
                extension = head[index+10:index+13].decode('ASCII').rstrip()
            except UnicodeDecodeError as error:
                print("Börk", error)
                print(head[index:index+26].hex())
                break
            index += 26
            yield "\t" + filename + "." + extension

    def write_metafile(self, filename=None):
        ''' Write a Datamuseum.dk Bitstore Metadata file '''
        if filename is None:
            filename = self.filename + ".TAP.meta"
        with open(filename, "w") as meta:

            meta.write("%s:\n" % "BitStore.Metadata_version")
            meta.write("\t%s\n" % "1.0")
            meta.write("\n")

            meta.write("%s:\n" % "BitStore.Filename")
            meta.write("\t%s\n" % (os.path.basename(self.filename) + ".TAP"))
            meta.write("\n")

            meta.write("%s:\n" % "BitStore.Format")
            meta.write("\t%s\n" % "SIMH-TAP")
            meta.write("\n")

            meta.write("%s:\n" % "BitStore.Access")
            meta.write("\t%s\n" % "public")
            meta.write("\n")

            meta.write("%s:\n" % "BitStore.Last_edit")
            meta.write("\t%s\n" % "YYYYMMDD NN")
            meta.write("\n")

            meta.write("%s:\n" % "DDHF.Keyword")
            meta.write("\t%s\n" % "COMPANY/ICL/COMET/TAPE")
            meta.write("\n")

            meta.write("%s:\n" % "Media.Summary")
            meta.write("\t%s\n" % "XXX")
            meta.write("\n")

            meta.write("%s:\n" % "Media.Type")
            meta.write("\t%s\n" % "Mini-Cassette")
            meta.write("\n")

            meta.write("%s:\n" % "Media.Description")
            for i in self.interpret_tape_header():
                meta.write("\t%s\n" % self.ds2089(i))
            meta.write("\tTape Records:\n")
            for rec in self.records:
                meta.write("\t\t%s\n" % self.report_record(rec))
            meta.write("\n")
            meta.write("*END*\n")

class WAVTrack():
    ''' Iterator over zero crossings in a WAV-file track '''

    def __init__(self, track_no, sound, offset, span, rate):
        self.track_no = track_no
        self.sound = sound
        self.offset = offset
        self.span = span
        self.rate = rate

    def __iter__(self):
        sign = 0
        prev_sign = 0
        for nbr in range(self.offset, len(self.sound), self.span):
            samp= self.sound[nbr] + self.sound[nbr+1] * 256
            if samp > 32767:
                samp -= 65536

            if samp > THRESHOLD:
                sign = 1
            elif samp < -THRESHOLD:
                sign = -1
            if sign != prev_sign:
                yield nbr, sign
            prev_sign = sign

class WAVFile():
    ''' Iterator over tracks in a WAV-file '''

    def __init__(self, filename):
        self.filename = filename

        wavfile = wave.open(self.filename, 'rb')
        self.wav_param = wavfile.getparams()
        print("WAV file parameters:", self.wav_param)
        assert self.wav_param.sampwidth == 2
        assert self.wav_param.framerate == 44100
        self.sound = wavfile.readframes(wavfile.getnframes())

    def trackcount(self):
        ''' return number of sound channels '''
        return self.wav_param.nchannels

    def __iter__(self):
        for chan in range(self.wav_param.nchannels):
            yield WAVTrack(
                chan,
                self.sound,
                chan * 2,
                self.wav_param.nchannels * 2,
                self.wav_param.framerate
           )

def do_wavfile(filename, **kwargs):
    ''' Process one .WAV file '''
    wavfile = WAVFile(filename)
    for track in wavfile:
        print("=" * 80)
        print(filename, "TRACK", track.track_no)
        print("=" * 80)
        tape = CometTape(filename, track, **kwargs)
        if tape.records:
            break

if __name__ == "__main__":

    for fn in sys.argv[1:]:
        do_wavfile(fn)
