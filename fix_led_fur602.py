#!/usr/bin/env python3
"""Apply board-specific LED GPIO remapping to embedded DTB inside firmware.

目标:
 1. 扫描固件中的 DTB (magic 0xD00DFEED)。
 2. 在指定 DTB 中，将 /leds/green 与 /leds/red 的 gpios 第二个 cell 重映射 (按不同板型):
            FUR602:
                green: 0x04 -> 0x08 (GPIO 8)
                red:   0x05 -> 0x0D (GPIO 13 / blue 在 Komi-A31 上)
            Komi-A31:
                green: 0x04 -> 0x08 (GPIO 8)
                red:   0x05 -> 0x22 (GPIO 34, 真正红灯)
 3. 写出新固件文件 (默认文件名: {board}-<原文件名>，例如 fur602-firmware.bin / komi-a31-firmware.bin)。

限制:
 - 不扩大 DTB 属性长度; 仅允许替换为不更长的字符串。
 - 只处理单一 DTB (默认自动检测包含 /leds/green 的那个; 也可 --dtb-index 指定)。

用法示例:
  列出 DTB 和 LED 节点:
    python3 fix_led_fur602.py firmware.bin --list

  应用补丁 (自动找含 green 节点的 DTB):
    python3 fix_led_fur602.py firmware.bin -o firmware_fur602.bin

    明确指定 DTB 索引 + 板型:
        python3 fix_led_fur602.py firmware.bin --dtb-index 1 --board komi-a31 -o out.bin
"""
from __future__ import annotations

import argparse
import binascii
import hashlib
import os
import struct
import sys
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional, Iterable, Set

FDT_MAGIC = 0xD00DFEED

FDT_BEGIN_NODE = 0x1
FDT_END_NODE = 0x2
FDT_PROP = 0x3
FDT_NOP = 0x4
FDT_END = 0x9

U32 = struct.Struct(">I")


@dataclass
class DtbHeader:
    magic: int
    totalsize: int
    off_dt_struct: int
    off_dt_strings: int
    off_mem_rsvmap: int
    version: int
    last_comp_version: int
    boot_cpuid_phys: int
    size_dt_strings: int
    size_dt_struct: int

    @classmethod
    def parse(cls, data: bytes, off: int) -> Optional["DtbHeader"]:
        if off + 40 > len(data):
            return None
        fields = struct.unpack_from(">10I", data, off)
        if fields[0] != FDT_MAGIC:
            return None
        return cls(*fields)


@dataclass
class PropertyRef:
    node_path: str
    name: str
    value_offset: int
    value_len: int


def align4(x: int) -> int:
    return (x + 3) & ~3


def scan_dtbs(blob: bytes) -> List[Tuple[int, DtbHeader]]:
    hits: List[Tuple[int, DtbHeader]] = []
    magic_bytes = struct.pack(">I", FDT_MAGIC)
    start = 0
    while True:
        idx = blob.find(magic_bytes, start)
        if idx < 0:
            break
        hdr = DtbHeader.parse(blob, idx)
        if hdr and idx + hdr.totalsize <= len(blob):
            hits.append((idx, hdr))
        start = idx + 4
    return hits


def parse_properties(fw: bytes, base: int, hdr: DtbHeader) -> List[PropertyRef]:
    props: List[PropertyRef] = []
    struct_off = base + hdr.off_dt_struct
    strings_off = base + hdr.off_dt_strings
    strings_end = strings_off + hdr.size_dt_strings
    cursor = struct_off
    path_stack: List[str] = []

    def read_cstring(o: int) -> str:
        end = fw.find(b"\x00", o, strings_end)
        if end == -1:
            return "?"
        return fw[o:end].decode(errors="replace")

    while cursor < len(fw):
        (token,) = U32.unpack_from(fw, cursor)
        cursor += 4
        if token == FDT_BEGIN_NODE:
            end = fw.find(b"\x00", cursor)
            if end == -1:
                break
            name = fw[cursor:end].decode(errors="replace")
            cursor = align4(end + 1)
            path_stack.append(name if name else "/")
        elif token == FDT_END_NODE:
            if path_stack:
                path_stack.pop()
        elif token == FDT_PROP:
            if cursor + 8 > len(fw):
                break
            (val_len,) = U32.unpack_from(fw, cursor)
            (name_off,) = U32.unpack_from(fw, cursor + 4)
            cursor += 8
            value_off = cursor
            cursor = align4(cursor + val_len)
            name = read_cstring(strings_off + name_off)
            node_path = "/" + "/".join([p for p in path_stack if p and p != "/"])
            props.append(PropertyRef(node_path, name, value_off, val_len))
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            break
        else:
            break
    return props


def read_prop_bytes(blob: bytes, prop: PropertyRef) -> bytes:
    return blob[prop.value_offset: prop.value_offset + prop.value_len]


def read_c_string_from_value(blob: bytes, prop: PropertyRef) -> str:
    raw = read_prop_bytes(blob, prop)
    return raw.split(b"\x00", 1)[0].decode(errors="replace")


def collect_node_paths(fw: bytes, base: int, hdr: DtbHeader) -> Set[str]:
    """Scan structure block to collect all node paths (including nodes without properties)."""
    struct_off = base + hdr.off_dt_struct
    cursor = struct_off
    path_stack: List[str] = []
    paths: Set[str] = set()
    while cursor < len(fw):
        try:
            (token,) = U32.unpack_from(fw, cursor)
        except struct.error:
            break
        cursor += 4
        if token == FDT_BEGIN_NODE:
            end = fw.find(b"\x00", cursor)
            if end == -1:
                break
            name = fw[cursor:end].decode(errors="replace")
            cursor = align4(end + 1)
            path_stack.append(name if name else "/")
            node_path = "/" + "/".join([p for p in path_stack if p and p != "/"])
            paths.add(node_path if node_path != "" else "/")
        elif token == FDT_END_NODE:
            if path_stack:
                path_stack.pop()
        elif token == FDT_PROP:
            if cursor + 8 > len(fw):
                break
            (val_len,) = U32.unpack_from(fw, cursor)
            # skip name_off
            cursor += 8
            cursor = align4(cursor + val_len)
        elif token == FDT_NOP:
            continue
        elif token == FDT_END:
            break
        else:
            break
    return paths


def detect_fit(dtbs: List[Tuple[int, DtbHeader]], data: bytes) -> Optional[Tuple[int, DtbHeader, List[PropertyRef]]]:
    """Return (offset, header, props) for the FIT image DTB if found.

    Improved heuristic: must contain nodes '/images' AND '/configurations'.
    """
    for off, hdr in dtbs:
        node_paths = collect_node_paths(data, off, hdr)
        if '/images' in node_paths and '/configurations' in node_paths:
            props = parse_properties(data, off, hdr)
            return off, hdr, props
    return None


def group_fit_image_hashes(props: List[PropertyRef], blob: bytes) -> Dict[str, Dict[str, PropertyRef]]:
    """Group hash value properties by image node (/images/<name>). Return mapping:
        image_node -> { 'crc32': PropertyRef, 'sha1': PropertyRef }
    Only includes images having algo+value pairs.
    """
    # Build index by node_path for faster sibling lookup
    by_path: Dict[str, List[PropertyRef]] = {}
    for p in props:
        by_path.setdefault(p.node_path, []).append(p)

    image_hashes: Dict[str, Dict[str, PropertyRef]] = {}
    for p in props:
        # hash nodes look like /images/fdt-1/hash-1
        parts = p.node_path.strip('/').split('/')
        if len(parts) < 3:
            continue
        if parts[0] != 'images':
            continue
        if parts[-2].startswith('fdt') or parts[-2].startswith('kernel') or True:
            # Identify hash-* node level: expect 'hash-' prefix
            if parts[-1].startswith('hash-'):
                hash_node = p.node_path
                # Determine parent image node
                image_node = '/' + '/'.join(parts[:-1])
                siblings = by_path.get(hash_node, [])
                algo_prop = next((sp for sp in siblings if sp.name == 'algo'), None)
                value_prop = next((sp for sp in siblings if sp.name == 'value'), None)
                if not algo_prop or not value_prop:
                    continue
                algo = read_c_string_from_value(blob, algo_prop)
                if algo not in ('crc32', 'sha1'):
                    continue
                image_entry = image_hashes.setdefault(image_node, {})
                image_entry[algo] = value_prop
    return image_hashes


def compute_crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


def patch_gpios(data: bytearray, prop: PropertyRef, expect_second: int, new_second: int) -> bool:
    if prop.value_len != 12:
        return False
    a, b, c = struct.unpack_from(">III", data, prop.value_offset)
    if b != expect_second:
        return False
    if b == new_second:
        return False
    struct.pack_into(">III", data, prop.value_offset, a, new_second, c)
    return True


def main() -> int:
    ap = argparse.ArgumentParser(description="Apply FUR602 LED gpio mapping to firmware DTB (no label changes)")
    ap.add_argument("firmware", help="Input firmware .bin")
    ap.add_argument("-o", "--output", help="Output file (default: {board}-<basename>)")
    ap.add_argument("--dtb-index", type=int, default=None, help="Operate only on given DTB index (default: auto choose containing /leds/green)")
    ap.add_argument("--list", action="store_true", help="List DTBs and LED nodes then exit")
    ap.add_argument("--no-fit-hash", action="store_true", help="Do NOT attempt to auto-update FIT (outer image) hash values for modified fdt image")
    ap.add_argument("--board", choices=["fur602", "komi-a31"], default="fur602", help="Board mapping profile (default: fur602)")
    args = ap.parse_args()

    with open(args.firmware, 'rb') as f:
        data = bytearray(f.read())

    dtbs = scan_dtbs(data)
    if not dtbs:
        print("No DTB found", file=sys.stderr)
        return 1

    # Collect LED info for listing and auto index selection
    led_presence = []  # list[(idx, has_green)]
    for i, (off, hdr) in enumerate(dtbs):
        props = parse_properties(data, off, hdr)
        has_green = any(p.node_path.endswith('/green') for p in props)
        led_presence.append((i, has_green))
        if args.list:
            led_nodes = sorted(set(p.node_path for p in props if p.node_path.startswith('/leds')))
            print(f"[DTB {i}] offset=0x{off:X} total={hdr.totalsize} LED nodes: {', '.join(led_nodes) if led_nodes else '-'}")
    if args.list:
        return 0

    target_indices: List[int]
    if args.dtb_index is not None:
        if args.dtb_index < 0 or args.dtb_index >= len(dtbs):
            print("Invalid --dtb-index", file=sys.stderr)
            return 1
        target_indices = [args.dtb_index]
    else:
        # Pick first with green
        cand = [i for i, g in led_presence if g]
        target_indices = [cand[0]] if cand else [0]

    total_changes = 0
    # Keep record of (old_crc32, old_sha1, new_crc32, new_sha1) for each modified DTB so we can update FIT
    modified_dtbs_digests: List[Tuple[bytes, bytes, bytes, bytes]] = []  # (old_crc_be4, old_sha1_20, new_crc_be4, new_sha1_20)
    # For summary
    summary_lines: List[str] = []

    for idx in target_indices:
        off, hdr = dtbs[idx]
        props = parse_properties(data, off, hdr)
        prop_map: Dict[Tuple[str, str], PropertyRef] = {(p.node_path, p.name): p for p in props}

        # Board-specific GPIOS mapping definitions
        if args.board == 'komi-a31':
            mapping = [
                ("/leds/green", 0x04, 0x08),  # 4 -> 8
                ("/leds/red",   0x05, 0x22),  # 5 -> 34 (true red LED)
            ]
        else:  # fur602 default
            mapping = [
                ("/leds/green", 0x04, 0x08),  # 4 -> 8
                ("/leds/red",   0x05, 0x0D),  # 5 -> 13
            ]
        print(f"Using board profile: {args.board} (mapping count={len(mapping)})")

        # Capture original dtb slice bytes (exact) to compute hashes before & after
        original_slice = bytes(data[off: off + hdr.totalsize])
        old_crc = compute_crc32(original_slice)
        old_sha1 = hashlib.sha1(original_slice).digest()
        for node, old_val, new_val in mapping:
            ref = prop_map.get((node, "gpios"))
            if not ref:
                print(f"Warning: {node}:gpios not found (DTB {idx})")
                continue
            if patch_gpios(data, ref, old_val, new_val):
                print(f"Patched {node}:gpios second cell {old_val:#x}->{new_val:#x} (DTB {idx})")
                total_changes += 1
            else:
                print(f"No change / mismatch for {node}:gpios (expected second {old_val:#x})")

        # Label updates intentionally disabled per user request.

        if total_changes:  # At least one change maybe across dtbs; verify if this dtb changed
            # Recompute if any gpio patch succeeded within this dtb by comparing slice
            new_slice = bytes(data[off: off + hdr.totalsize])
            if new_slice != original_slice:
                new_crc = compute_crc32(new_slice)
                new_sha1 = hashlib.sha1(new_slice).digest()
                modified_dtbs_digests.append((struct.pack('>I', old_crc), old_sha1, struct.pack('>I', new_crc), new_sha1))
                line = f"DTB {idx} digest update: crc32 {old_crc:08x}->{new_crc:08x}, sha1 {old_sha1.hex()}->{new_sha1.hex()}"
                print(line)
                summary_lines.append(line)

    if total_changes == 0:
        print("No changes applied (nothing matched expected original values)")
        return 2

    # Attempt FIT hash auto-update unless disabled
    if modified_dtbs_digests and not args.no_fit_hash:
        fit = detect_fit(dtbs, data)
        if not fit:
            print("Warning: FIT image DTB not detected; cannot auto-update hash values (node detection failed)")
        else:
            fit_off, fit_hdr, fit_props = fit
            image_hash_map = group_fit_image_hashes(fit_props, data)
            # For each modified dtb, try locate matching image by old digests
            updated_images = 0
            for old_crc_be, old_sha1, new_crc_be, new_sha1 in modified_dtbs_digests:
                matched_image = None
                for image_node, algomap in image_hash_map.items():
                    crc_prop = algomap.get('crc32')
                    sha1_prop = algomap.get('sha1')
                    if not crc_prop or not sha1_prop:
                        continue
                    current_crc = read_prop_bytes(data, crc_prop)
                    current_sha1 = read_prop_bytes(data, sha1_prop)
                    if current_crc == old_crc_be and current_sha1 == old_sha1:
                        matched_image = (image_node, crc_prop, sha1_prop)
                        break
                if not matched_image:
                    print("Warning: Could not find matching FIT hash nodes for modified DTB (old digests not present).")
                    continue
                image_node, crc_prop, sha1_prop = matched_image
                # Write new values
                data[crc_prop.value_offset: crc_prop.value_offset + 4] = new_crc_be
                data[sha1_prop.value_offset: sha1_prop.value_offset + 20] = new_sha1
                updated_images += 1
                msg = f"Updated FIT hashes for {image_node}: crc32 -> {new_crc_be.hex()} sha1 -> {new_sha1.hex()}"
                print(msg)
                summary_lines.append(msg)
            if updated_images == 0:
                print("Warning: No FIT hashes updated (digest match not found).")
            else:
                print(f"FIT hash update completed for {updated_images} image(s)")
                summary_lines.append(f"FIT hash update completed for {updated_images} image(s)")

    if args.output:
        out_path = args.output
    else:
        base_name = os.path.basename(args.firmware)
        out_path = f"{args.board}-{base_name}"
    if os.path.abspath(out_path) == os.path.abspath(args.firmware):
        print("Refusing to overwrite input (choose different -o)", file=sys.stderr)
        return 1
    with open(out_path, 'wb') as f:
        f.write(data)
    print(f"Wrote patched firmware: {out_path} (changes: {total_changes})")
    if summary_lines:
        print("Summary:")
        for l in summary_lines:
            print("  " + l)
    return 0


if __name__ == '__main__':  # pragma: no cover
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)
