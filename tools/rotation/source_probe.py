#!/usr/bin/env python3
"""Arm or save one root-only source probe; never changes the display orientation."""
import argparse
import ctypes
import json
import os
from pathlib import Path
import struct
import zlib

CAPACITY = 160 + 640 * 640 * 4


def sysctl(name, new=None):
    libc = ctypes.CDLL(None, use_errno=True)
    call = libc.sysctlbyname
    call.argtypes = [ctypes.c_char_p, ctypes.c_void_p, ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_size_t]
    call.restype = ctypes.c_int
    output = ctypes.create_string_buffer(CAPACITY)
    length = ctypes.c_size_t(CAPACITY)
    value = ctypes.c_int(new) if new is not None else None
    if call(name.encode(), output, ctypes.byref(length), ctypes.byref(value) if value is not None else None,
            ctypes.sizeof(value) if value is not None else 0):
        code = ctypes.get_errno()
        raise OSError(code, os.strerror(code), name)
    return output.raw[:length.value]


def decode(data):
    if len(data) < 160:
        raise ValueError('Truncated source header')
    h = struct.unpack_from('<4IQ34I', data)
    magic, version, header_bytes, pixel_bytes, epoch = h[:5]
    if (magic, version, header_bytes) != (0x34524d4e, 1, 160):
        raise ValueError('Unknown source probe ABI')
    width, height, pitch = h[12:15]
    if not (0 < width <= 640 and 0 < height <= 640 and pitch == width*4 and pixel_bytes == pitch*height
            and len(data) == header_bytes + pixel_bytes):
        raise ValueError('Invalid source image size')
    fields = dict(zip(('surface_id','head','degrees','format','source_width','source_height','source_pitch',
                      'image_width','image_height','image_pitch','logical_width','logical_height','output_width','output_height',
                      'resource_width','resource_height','resource_pitch','reserved'), h[5:23]))
    fields.update(version=version, epoch=epoch)
    for key, start, count in [('source_rect',23,4),('destination_rect',27,4),('pipe_scaler',31,6)]:
        fields[key] = [struct.unpack('<f', struct.pack('<I', value))[0] for value in h[start:start+count]]
        fields[key+'_bits'] = list(h[start:start+count])
    return fields, data[160:]


def png(fields, pixels):
    width, height = fields['image_width'], fields['image_height']
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        for x in range(width):
            b,g,r,_ = pixels[(y*width+x)*4:(y*width+x+1)*4]
            raw.extend((r,g,b))
    def chunk(kind, payload):
        return struct.pack('>I',len(payload))+kind+payload+struct.pack('>I',zlib.crc32(kind+payload))
    return b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress(raw))+chunk(b'IEND',b'')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--arm',type=int,choices=[0,90,180,270],help='0 discards; a nonzero angle arms for 20 seconds')
    group.add_argument('--save',type=Path,help='New private directory for the raw probe, JSON metadata and PNG')
    args = parser.parse_args()
    if os.geteuid() != 0:
        parser.error('The source probe requires root access')
    if args.arm is not None:
        sysctl('debug.nvaccel_rotation_probe_arm',args.arm)
        print('Discarded' if not args.arm else f'Armed for one {args.arm} degree source in the next 20 seconds')
    else:
        data=sysctl('debug.nvaccel_rotation_probe')
        fields,pixels=decode(data)
        args.save.mkdir(mode=0o700,parents=False,exist_ok=False)
        for name, contents in [('source.nmrs',data),('source.json',(json.dumps(fields,indent=2)+'\n').encode()),
                               ('source.png',png(fields,pixels))]:
            fd=os.open(args.save/name,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600)
            with os.fdopen(fd,'wb') as output: output.write(contents)
        sysctl('debug.nvaccel_rotation_probe_arm',0)
        print(json.dumps(fields,indent=2))


if __name__ == '__main__':
    main()
