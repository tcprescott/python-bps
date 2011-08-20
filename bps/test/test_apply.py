#!/usr/bin/python3

# This program is free software. It comes without any warranty, to
# the extent permitted by applicable law. You can redistribute it
# and/or modify it under the terms of the Do What The Fuck You Want
# To Public License, Version 2, as published by Sam Hocevar. See
# the COPYING file included with this distribution or
# http://sam.zoy.org/wtfpl/COPYING for more details.

import unittest
from pkgutil import get_data
from io import BytesIO
from bps import operations as ops
from bps.apply import apply_to_bytearrays, apply_to_files
from bps.io import read_bps
from bps.validate import check_stream
from bps.test.util import find_bps, find_data

class TestApplyToByteArrays(unittest.TestCase):

	def _run_test(self, patchname, source):
		raw_patch = find_bps(patchname)
		iterable = check_stream(read_bps(BytesIO(raw_patch)))

		header = next(iterable)

		assert len(source) == header.sourceSize

		target = bytearray(header.targetSize)

		apply_to_bytearrays(iterable, source, target)

		return target

	def testIgnoresHeader(self):
		"""
		apply_to_bytearrays shouldn't crash if it gets a header opcode.
		"""
		raw_patch = find_bps("sourceread")
		iterable = read_bps(BytesIO(raw_patch))

		# I happen to know this particular patch has sourcesize and
		# targetsize equal to 1.
		target = bytearray(1)
		apply_to_bytearrays(iterable, b'A', target)

		self.assertSequenceEqual(target, b'A')

	def testEmptyPatch(self):
		"""
		The simplest possible patch can be processed correctly.
		"""
		target = self._run_test("empty", b'')

		self.assertSequenceEqual(b'', target)

	def testPatchWithSourceRead(self):
		"""
		We can process a patch with a SourceRead opcode.
		"""
		target = self._run_test("sourceread", b'A')

		self.assertSequenceEqual(b'A', target)

	def testPatchWithTargetRead(self):
		"""
		We can process a patch with a TargetRead opcode.
		"""
		target = self._run_test("targetread", b'')

		self.assertSequenceEqual(b'A', target)

	def testPatchWithSourceCopy(self):
		"""
		We can process a patch with a SourceCopy opcode.
		"""
		target = self._run_test("sourcecopy", b'AB')

		self.assertSequenceEqual(b'BA', target)

	def testPatchWithTargetCopy(self):
		"""
		We can process a patch with a TargetCopy opcode.
		"""
		target = self._run_test("targetcopy", b'')

		self.assertSequenceEqual(b'AAAA', target)

	def testPatchWithMultipleTargetCopies(self):
		"""
		Each TargetCopy updates writeOffset and targetCopyOffset correctly.
		"""
		iterable = check_stream([
				ops.Header(1, 5),
				ops.SourceRead(1),
				ops.TargetCopy(2, 0),
				ops.TargetCopy(2, 0),
				ops.SourceCRC32(0xD3D99E8B),
				ops.TargetCRC32(0x19F85109),
			])
		source = b'A'
		target = bytearray(5)

		apply_to_bytearrays(iterable, source, target)

		self.assertSequenceEqual(b'AAAAA', target)


class TestApplyToFiles(unittest.TestCase):

	def testPatchWithSourceCopy(self):
		"""
		We can process a patch with a SourceCopy opcode.
		"""
		patch = BytesIO(find_bps("sourcecopy"))
		source = BytesIO(find_data("sourcecopy.source"))
		expectedTarget = BytesIO(find_data("sourcecopy.target"))

		actualTarget = BytesIO()
		apply_to_files(patch, source, actualTarget)

		self.assertSequenceEqual(
				expectedTarget.getvalue(),
				actualTarget.getvalue(),
			)


if __name__ == "__main__":
	unittest.main()
