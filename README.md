# ICL_Comet_tape_reader

Process audio from ICL/Metanic COMET computer tapes into SIMH-TAP files

For more about ICL/Metanic COMET computers:

	https://datamuseum.dk/wiki/ICL/Comet

Input is .WAV files, 16bit little endian, 44100 samples per second.

All audio-channels will be analyzed until one finds data.

Output is SIMH-TAP file and template Datamuseum.dk BitArchive .meta file

Usage:

	python3 -u ICL_Comet_tape_reader.py *.wav

/phk
