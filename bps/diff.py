# This program is free software. It comes without any warranty, to
# the extent permitted by applicable law. You can redistribute it
# and/or modify it under the terms of the Do What The Fuck You Want
# To Public License, Version 2, as published by Sam Hocevar. See
# the COPYING file included with this distribution or
# http://sam.zoy.org/wtfpl/COPYING for more details.

"""
Tools for creating BPS patches.

For more information about the basic algorithm used here, see the article
"Intro to Delta Encoding":

	https://gitorious.org/python-blip/pages/IntroToDeltaEncoding

"""
from zlib import crc32
from bps import operations as ops
from bps.util import BlockMap

def iter_blocks(data, blocksize):
	offset = 0

	while offset < len(data):
		block = data[offset:offset+blocksize]

		yield (block, offset)
		offset += len(block)


def measure_op(pendingTargetReadSize, blocksrc, sourceoffset, target,
		targetoffset, op):
	"""
	Measure the match between blocksrc and target at these offsets.
	"""
	# The various parameters line up something like this:
	#
	#    v-- sourceoffset
	# ...ABCDEFGHI... <-- blocksrc
	#
	#    ___- pendingTargetReadSize
	# ...xxxABCDEF... <-- target
	#       ^-- targetOffset
	#

	result = []

	# Measure how far back the source and target files match from these
	# offsets.
	backspan = 0

	maxspan = min(sourceoffset, targetoffset, pendingTargetReadSize+1)

	for backspan in range(maxspan):
		if blocksrc[sourceoffset-backspan-1] != target[targetoffset-backspan-1]:
			break

	sourceoffset -= backspan
	targetoffset -= backspan
	pendingTargetReadSize -= backspan

	if pendingTargetReadSize:
		result.append(ops.TargetRead(
				target[targetoffset-pendingTargetReadSize:targetoffset]
			))

	# Measure how far forward the source and target files are aligned.
	forespan = 0

	sourcespan = len(blocksrc) - sourceoffset
	targetspan = len(target) - targetoffset
	maxspan = min(sourcespan, targetspan)

	for forespan in range(maxspan):
		if blocksrc[sourceoffset+forespan] != target[targetoffset+forespan]:
			break
	else:
		# We matched right up to the end of the file.
		forespan += 1

	if op is ops.SourceCopy and sourceoffset == targetoffset:
		result.append(ops.SourceRead(forespan))
	else:
		result.append(op(forespan, sourceoffset))

	return result


def op_efficiency(oplist, lastSourceCopyOffset, lastTargetCopyOffset):
	total_bytespan = 0
	total_encoding_size = 0

	for op in oplist:
		total_bytespan += op.bytespan
		total_encoding_size += len(
				op.encode(lastSourceCopyOffset, lastTargetCopyOffset)
			)

	return total_bytespan / total_encoding_size


def diff_bytearrays(source, target, metadata=""):
	"""
	Yield a sequence of patch operations that transform source to target.
	"""
	# Smaller block-sizes make for more efficient diffs, but a larger number of
	# blocks uses more memory. Since we need to keep the block map for the
	# source and target in memory at the same time, calculate a block-size that
	# will give us about a 64-byte block on a 32MB file (since I know from
	# experience that fits in my RAM).
	blocksize = (len(source) + len(target)) // 1000000 + 1

	yield ops.Header(len(source), len(target), metadata)

	# We assume the entire source file will be available when applying this
	# patch, so load the entire thing into the block map.
	sourcemap = BlockMap()
	for block, offset in iter_blocks(source, blocksize):
		sourcemap.add_block(block, offset)

	# Points at the part of the target buffer we're trying to encode.
	targetWriteOffset = 0

	# Points at the byte after the last byte written by the most recent
	# SourceCopy operation.
	lastSourceCopyOffset = 0

	# Points at the byte after the last byte written by the most recent
	# TargetCopy operation.
	lastTargetCopyOffset = 0

	# Keep track of blocks seen in the part of the target buffer before
	# targetWriteOffset. Because targetWriteOffset does not always advance by
	# an even multiple of the blocksize, there can be some lag between when
	# targetWriteOffset moves past a particular byte, and when that byte's
	# block is added to targetmap.
	targetmap = BlockMap()
	targetblocks = iter_blocks(target, blocksize)

	# Points to the byte just beyond the most recent block added to targetmap;
	# the difference between this and targetWriteOffset measures the 'some lag'
	# described above.
	nextTargetBlockOffset = 0

	# The number of bytes to be added to be written via TargetRead.
	pendingTargetReadSize = 0

	while targetWriteOffset + pendingTargetReadSize < len(target):
		# The best list of operations we've seen so far.
		bestOpList = None
		bestOpEfficiency = 0

		for extraOffset in range(blocksize):
			blockstart = targetWriteOffset + pendingTargetReadSize + extraOffset
			blockend = blockstart + blocksize
			block = target[blockstart:blockend]

			for sourceOffset in sourcemap.get(block, []):
				candidate = measure_op(
						pendingTargetReadSize + extraOffset,
						source, sourceOffset,
						target, blockstart,
						ops.SourceCopy,
					)

				efficiency = op_efficiency(candidate,
						lastSourceCopyOffset, lastTargetCopyOffset)

				if efficiency > bestOpEfficiency:
					bestOpList = candidate
					bestOpEfficiency = efficiency

			for targetOffset in targetmap.get(block, []):
				candidate = measure_op(
						pendingTargetReadSize + extraOffset,
						target, targetOffset,
						target, blockstart,
						ops.TargetCopy,
					)

				efficiency = op_efficiency(candidate,
						lastSourceCopyOffset, lastTargetCopyOffset)

				if efficiency > bestOpEfficiency:
					bestOpList = candidate
					bestOpEfficiency = efficiency

		if bestOpList is None:
			# We can't find a way to encode this block, so we'll have to issue
			# a TargetRead... later. Because the extraOffset loop above has
			# tested up to (blocksize-1) blocks forward, we can advance by
			# blocksize.
			pendingTargetReadSize += blocksize
			continue

		for op in bestOpList:
			yield op

			targetWriteOffset += op.bytespan

			if isinstance(op, ops.TargetCopy):
				lastTargetCopyOffset = op.offset + op.bytespan
			if isinstance(op, ops.SourceCopy):
				lastSourceCopyOffset = op.offset + op.bytespan

		pendingTargetReadSize = 0

		# If it's been more than BLOCKSIZE bytes since we added a block to
		# targetmap, process the backlog.
		while (targetWriteOffset - nextTargetBlockOffset) >= blocksize:
			newblock, offset = next(targetblocks)
			targetmap.add_block(newblock, offset)
			nextTargetBlockOffset = offset + len(newblock)

	if targetWriteOffset < len(target):
		# Our pendingTargetReadSize goes all the way up to the end of the file.
		yield ops.TargetRead(target[targetWriteOffset:])

	yield ops.SourceCRC32(crc32(source))
	yield ops.TargetCRC32(crc32(target))
