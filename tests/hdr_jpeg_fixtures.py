"""Tiny in-memory JPEG/MPF fixtures; no source documents or model dependencies."""
import io
import struct

from PIL import Image

XMP_NAMESPACE = b'http://ns.adobe.com/xap/1.0/\0'
ISO_NAMESPACE = b'urn:iso:std:iso:ts:21496:-1\0'
APPLE_NAMESPACE = 'http://ns.apple.com/pixeldatainfo/1.0/'
GAIN_MAP_TYPE = 'urn:com:apple:photo:2020:aux:hdrgainmap'
ADOBE_NAMESPACE = 'http://ns.adobe.com/hdr-gain-map/1.0/'
GOOGLE_ITEM_NAMESPACE = 'http://ns.google.com/photos/1.0/container/item/'
ADOBE_PRIMARY_XMP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    f'<rdf:Description xmlns:hdrgm="{ADOBE_NAMESPACE}" hdrgm:Version="1.0" '
    'xmlns:Container="http://ns.google.com/photos/1.0/container/" '
    f'xmlns:Item="{GOOGLE_ITEM_NAMESPACE}">'
    '<Container:Directory><rdf:Seq>'
    '<rdf:li rdf:parseType="Resource"><Container:Item Item:Semantic="Primary" Item:Mime="image/jpeg"/></rdf:li>'
    '<rdf:li rdf:parseType="Resource"><Container:Item Item:Semantic="GainMap" Item:Mime="image/jpeg"/></rdf:li>'
    '</rdf:Seq></Container:Directory></rdf:Description></rdf:RDF></x:xmpmeta>'
).encode('utf-8')
ADOBE_SECONDARY_XMP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    f'<rdf:Description xmlns:hdrgm="{ADOBE_NAMESPACE}" hdrgm:Version="1.0" '
    'hdrgm:BaseRenditionIsHDR="False"/></rdf:RDF></x:xmpmeta>'
).encode('utf-8')
APPLE_XMP = (
    '<x:xmpmeta xmlns:x="adobe:ns:meta/">'
    '<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    f'<rdf:Description xmlns:p="{APPLE_NAMESPACE}" '
    f'p:AuxiliaryImageType="{GAIN_MAP_TYPE}"/>'
    '</rdf:RDF></x:xmpmeta>'
).encode('utf-8')


def make_jpeg(size=(32, 24), color=(80, 120, 160), markers=(), *, mode='RGB'):
    out = io.BytesIO()
    Image.new(mode, size, color).save(out, 'JPEG', quality=90)
    data = out.getvalue()
    segments = b''.join(bytes((255, marker)) + struct.pack('>H', len(payload) + 2) + payload
                        for marker, payload in markers)
    return data[:2] + segments + data[2:]


def iso_payload(channels=1, *, use_base_color_space=True):
    """Version 0: two headroom rationals then five rationals per channel."""
    if channels not in (1, 3):
        raise ValueError('channels must be one or three')
    flags = (128 if channels == 3 else 0) | (64 if use_base_color_space else 0)
    fractions = [(1, 1), (2, 1)] + [(0, 1), (1, 1), (1, 1), (0, 1), (0, 1)] * channels
    return b'\0\0\0\0' + bytes((flags,)) + b''.join(struct.pack('>iI', n, d) for n, d in fractions)


def make_mpo(profile='apple', *, channels=1, frame_count=2,
             primary_size=(32, 24), auxiliary_size=(16, 12),
             primary_type=0x030000, secondary_type=0, primary_offset=0,
             primary_markers=None, secondary_markers=None):
    """Return original MPF bytes; custom markers replace the profile's markers.

    profile is apple, iso, adobe, or None (unidentified multi-picture document).
    The TIFF starts at byte 10; MP offsets are relative to that TIFF header.
    """
    if profile not in ('apple', 'iso', 'adobe', None) or frame_count < 1:
        raise ValueError('invalid synthetic fixture profile')
    if primary_markers is None:
        primary_markers = ([(0xE2, ISO_NAMESPACE + b'\0' * 4)] if profile == 'iso' else
                           [(0xE1, XMP_NAMESPACE + ADOBE_PRIMARY_XMP)] if profile == 'adobe' else [])
    if secondary_markers is None:
        secondary_markers = ([(0xE1, XMP_NAMESPACE + APPLE_XMP)] if profile == 'apple' else
                             [(0xE2, ISO_NAMESPACE + iso_payload(channels))] if profile == 'iso' else
                             [(0xE1, XMP_NAMESPACE + ADOBE_SECONDARY_XMP)] if profile == 'adobe' else [])
    frames = [make_jpeg(primary_size, markers=primary_markers)]
    frames += [make_jpeg(auxiliary_size, 120 if profile == 'adobe' else (120, 120, 120),
                        secondary_markers, mode='L' if profile == 'adobe' else 'RGB')
               for _ in range(frame_count - 1)]
    tiff_size = 50 + frame_count * 16
    marker_size = 4 + 4 + tiff_size
    sizes = [len(frames[0]) + marker_size] + [len(frame) for frame in frames[1:]]
    entries = b''
    offset = 0
    for index, size in enumerate(sizes):
        entries += struct.pack('<IIIHH', primary_type if index == 0 else secondary_type,
                               size, primary_offset if index == 0 else offset - 10, 0, 0)
        offset += size
    tiff = (b'II\x2a\0' + struct.pack('<I', 8) + struct.pack('<H', 3) +
            struct.pack('<HHI4s', 0xB000, 7, 4, b'0100') +
            struct.pack('<HHII', 0xB001, 4, 1, frame_count) +
            struct.pack('<HHII', 0xB002, 7, frame_count * 16, 50) +
            b'\0' * 4 + entries)
    app2 = b'\xff\xe2' + struct.pack('>H', len(tiff) + 6) + b'MPF\0' + tiff
    return frames[0][:2] + app2 + frames[0][2:] + b''.join(frames[1:])
