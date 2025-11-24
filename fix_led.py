#!/usr/bin/env python3
"""通用 DTB LED / 属性补丁脚本，使用 INI 配置文件描述多型号映射。

功能概述:
    * 扫描固件中的 DTB (magic 0xD00DFEED)。
    * 按配置文件描述的规则修改 DTB 中的属性值（目前主要用于 /leds/* gpios）。
    * 在保持 DTB 尺寸不变的前提下，重新计算被修改 DTB 的 crc32 / sha1，
        并同步更新外层 FIT 镜像中的 hash 节点。

配置方式:
    INI（单文件多型号）：`leds.ini`，例如:

        [komi-a31]
        dtb_index = 1           ; 可选，不写则自动匹配含 /leds/* 的 DTB
        green  = 8              ; /leds/green  gpios 第二个 u32: -> 8
        red    = 34             ; /leds/red    gpios 第二个 u32: -> 34

        [fur602]
        dtb_index = 1
        green  = 8
        red    = 13

    调用示例:

        # 批量处理：为 INI 中所有机型生成固件（不指定 --board）
        python3 fix_led.py firmware.bin --config leds.ini
        
        # 单机型处理：仅处理指定机型
        python3 fix_led.py firmware.bin --config leds.ini --board komi-a31
"""
from __future__ import annotations

import argparse
import binascii
import configparser
import hashlib
import os
import struct
import sys
from dataclasses import dataclass
from typing import List, Tuple, Dict, Optional, Set

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
    """收集 DTB 结构块中的所有节点路径 (包含没有属性的节点)。"""
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
    """检测外层 FIT DTB (包含 '/images' 与 '/configurations' 节点)。"""
    for off, hdr in dtbs:
        node_paths = collect_node_paths(data, off, hdr)
        if "/images" in node_paths and "/configurations" in node_paths:
            props = parse_properties(data, off, hdr)
            return off, hdr, props
    return None


def group_fit_image_hashes(props: List[PropertyRef], blob: bytes) -> Dict[str, Dict[str, PropertyRef]]:
    """按 image 节点分组 hash 属性 (/images/<name>/hash-*).

    返回: image_node -> { 'crc32': PropertyRef, 'sha1': PropertyRef }
    """
    by_path: Dict[str, List[PropertyRef]] = {}
    for p in props:
        by_path.setdefault(p.node_path, []).append(p)

    image_hashes: Dict[str, Dict[str, PropertyRef]] = {}
    for p in props:
        parts = p.node_path.strip("/").split("/")
        if len(parts) < 3:
            continue
        if parts[0] != "images":
            continue
        if parts[-1].startswith("hash-"):
            hash_node = p.node_path
            image_node = "/" + "/".join(parts[:-1])
            siblings = by_path.get(hash_node, [])
            algo_prop = next((sp for sp in siblings if sp.name == "algo"), None)
            value_prop = next((sp for sp in siblings if sp.name == "value"), None)
            if not algo_prop or not value_prop:
                continue
            algo = read_c_string_from_value(blob, algo_prop)
            if algo not in ("crc32", "sha1"):
                continue
            image_entry = image_hashes.setdefault(image_node, {})
            image_entry[algo] = value_prop
    return image_hashes


def compute_crc32(data: bytes) -> int:
    return binascii.crc32(data) & 0xFFFFFFFF


def patch_gpios_triplet_second(data: bytearray, prop: PropertyRef, expect_second: Optional[int], new_second: int) -> bool:
    """针对 u32 triplet (3 * u32) 的 gpios 属性, 仅读/改第二个 u32。
    
    参数:
        data: DTB 数据
        prop: 属性引用
        expect_second: 期望的原值。如果为 None，则跳过验证直接修改。
        new_second: 新值
    
    返回:
        True 表示成功修改，False 表示未修改（验证失败或已是目标值）
    """
    if prop.value_len != 12:
        return False
    a, b, c = struct.unpack_from(">III", data, prop.value_offset)
    # 如果指定了期望值，则验证当前值是否匹配
    if expect_second is not None and b != expect_second:
        return False
    # 如果已经是目标值，无需修改
    if b == new_second:
        return False
    struct.pack_into(">III", data, prop.value_offset, a, new_second, c)
    return True


# ------------------------- 配置结构 -------------------------------------------

@dataclass
class MappingRule:
    node: str
    property: str
    kind: str  # e.g. "u32_triplet"
    second_from: Optional[int] = None
    second_to: Optional[int] = None


@dataclass
class TargetConfig:
    dtb_index: Optional[int]
    mappings: List[MappingRule]


@dataclass
class PatchConfig:
    profile: str
    targets: List[TargetConfig]


def load_single_profile_config(cp: configparser.ConfigParser, profile: str) -> PatchConfig:
    """从 ConfigParser 对象中加载单个 profile 的配置。
    
    参数:
        cp: ConfigParser 对象
        profile: profile 名称（section 名）
    
    返回:
        PatchConfig 对象
    """
    if profile not in cp:
        raise ValueError(f"Profile '{profile}' not found in INI config")
    
    sect = cp[profile]
    
    # 解析 dtb_index
    dtb_index: Optional[int]
    if "dtb_index" in sect:
        try:
            dtb_index = int(sect.get("dtb_index", "").strip(), 0)
        except ValueError as e:
            raise ValueError(f"Invalid dtb_index in profile '{profile}': {e}")
    else:
        dtb_index = None
    
    mappings: List[MappingRule] = []
    for key, value in sect.items():
        if key == "dtb_index":
            continue
        # key 视为 LED 名，如 green/red，映射到 /leds/<key>
        led_name = key.strip()
        if not led_name:
            continue
        # value 形如 "8" 或 "0x8"（直接指定目标值）
        try:
            v_to = int(value.strip(), 0)
        except ValueError as e:
            raise ValueError(
                f"Invalid number in mapping '{value}' for led '{key}' in profile '{profile}': {e}"
            )
        node_path = f"/leds/{led_name}"
        mappings.append(
            MappingRule(
                node=node_path,
                property="gpios",
                kind="u32_triplet",
                second_from=None,
                second_to=v_to,
            )
        )
    
    if not mappings:
        raise ValueError(f"Profile '{profile}' has no LED mappings")
    
    target = TargetConfig(dtb_index=dtb_index, mappings=mappings)
    return PatchConfig(profile=profile, targets=[target])


def load_ini_config(path: str, profile: Optional[str]) -> List[PatchConfig]:
    """从 INI 文件读取配置。

    约定: 每个 section 表示一个 profile（型号），例如 [komi-a31]。
    - dtb_index: 可选，整数。
    - 其它键: 视为 LED 名，值为目标值，例如 "8" 或 "0x8"。
    
    注意: 使用 inline_comment_prefixes 以支持 INI 文件中的内联注释（如：green = 8 ; 注释 或 green = 8 # 注释）。
    
    参数:
        path: INI 配置文件路径
        profile: 指定的 profile 名称，如果为 None 则加载所有 profiles
    
    返回:
        PatchConfig 对象列表
    """
    cp = configparser.ConfigParser(inline_comment_prefixes=(';', '#'))
    with open(path, "r", encoding="utf-8") as f:
        cp.read_file(f)

    if not cp.sections():
        raise ValueError("INI config has no sections")

    if profile is None:
        # 若未指定 profile，则加载所有 profiles
        configs = []
        for section in cp.sections():
            try:
                cfg = load_single_profile_config(cp, section)
                configs.append(cfg)
            except ValueError as e:
                print(f"Warning: Skipping invalid profile '{section}': {e}. Processing will continue with other profiles.", file=sys.stderr)
        if not configs:
            raise ValueError("No valid profiles found in INI config")
        return configs
    else:
        # 若指定了 profile，则只加载该 profile
        return [load_single_profile_config(cp, profile)]


# ------------------------- 主逻辑 ---------------------------------------------


def process_single_profile(
    cfg: PatchConfig, 
    data: bytearray, 
    dtbs: List[Tuple[int, DtbHeader]], 
    args: argparse.Namespace
) -> Tuple[int, List[str]]:
    """处理单个 profile，返回修改次数和摘要行列表。
    
    参数:
        cfg: PatchConfig 配置对象
        data: 固件数据 (会被修改)
        dtbs: DTB 列表
        args: 命令行参数
    
    返回:
        (total_changes, summary_lines)
    """
    total_changes = 0
    # (dtb_index, old_crc_be4, new_crc_be4, old_sha1, new_sha1)
    modified_dtbs_digests: List[Tuple[int, bytes, bytes, bytes, bytes]] = []
    summary_lines: List[str] = []

    for t in cfg.targets:
        # 决定本 target 的 DTB index
        if t.dtb_index is not None:
            idx = t.dtb_index
        elif args.dtb_index is not None:
            idx = args.dtb_index
        else:
            wanted_nodes = {m.node for m in t.mappings}
            cand_idx: Optional[int] = None
            for i, (off_i, hdr_i) in enumerate(dtbs):
                props_i = parse_properties(data, off_i, hdr_i)
                node_paths_i = {p.node_path for p in props_i}
                if any(n in node_paths_i for n in wanted_nodes):
                    cand_idx = i
                    break
            if cand_idx is None:
                print(
                    f"Warning: no DTB contains any of nodes {wanted_nodes}, skip this target"
                )
                continue
            idx = cand_idx

        if idx < 0 or idx >= len(dtbs):
            print(f"Warning: target dtb_index {idx} out of range, skip", file=sys.stderr)
            continue

        off, hdr = dtbs[idx]
        props = parse_properties(data, off, hdr)
        prop_map: Dict[Tuple[str, str], PropertyRef] = {
            (p.node_path, p.name): p for p in props
        }

        print(
            f"Applying profile '{cfg.profile}' to DTB {idx} "
            f"(offset=0x{off:X}) with {len(t.mappings)} mapping(s)"
        )

        original_slice = bytes(data[off : off + hdr.totalsize])
        old_crc = compute_crc32(original_slice)
        old_sha1 = hashlib.sha1(original_slice).digest()

        local_changed = False
        for m in t.mappings:
            key = (m.node, m.property)
            ref = prop_map.get(key)
            if not ref:
                print(
                    f"Warning: property {m.property} not found in node {m.node} "
                    f"(DTB {idx})"
                )
                continue
            if m.kind == "u32_triplet":
                if m.second_to is None:
                    print(
                        f"Warning: mapping for {m.node}:{m.property} missing second_to, skip"
                    )
                    continue
                if patch_gpios_triplet_second(
                    data, ref, m.second_from, int(m.second_to)
                ):
                    if m.second_from is not None:
                        print(
                            f"Patched {m.node}:{m.property} second cell "
                            f"{m.second_from:#x}->{m.second_to:#x} (DTB {idx})"
                        )
                    else:
                        print(
                            f"Patched {m.node}:{m.property} second cell "
                            f"->{m.second_to:#x} (DTB {idx})"
                        )
                    total_changes += 1
                    local_changed = True
                else:
                    if m.second_from is not None:
                        print(
                            f"No change / mismatch for {m.node}:{m.property} "
                            f"(expected second {m.second_from:#x})"
                        )
                    else:
                        print(
                            f"No change for {m.node}:{m.property} "
                            f"(already set to {m.second_to:#x})"
                        )
            else:
                print(
                    f"Warning: unsupported mapping kind '{m.kind}' (node {m.node}), skip"
                )

        if local_changed:
            new_slice = bytes(data[off : off + hdr.totalsize])
            if new_slice != original_slice:
                new_crc = compute_crc32(new_slice)
                new_sha1 = hashlib.sha1(new_slice).digest()
                modified_dtbs_digests.append(
                    (
                        idx,
                        struct.pack(">I", old_crc),
                        struct.pack(">I", new_crc),
                        old_sha1,
                        new_sha1,
                    )
                )
                line = (
                    f"DTB {idx} digest update: crc32 {old_crc:08x}->{new_crc:08x}, "
                    f"sha1 {old_sha1.hex()}->{new_sha1.hex()}"
                )
                print(line)
                summary_lines.append(line)

    # 更新 FIT hash
    if modified_dtbs_digests and not args.no_fit_hash:
        fit = detect_fit(dtbs, data)
        if not fit:
            print(
                "Warning: FIT image DTB not detected; cannot auto-update hash values (node detection failed)"
            )
        else:
            fit_off, fit_hdr, fit_props = fit
            image_hash_map = group_fit_image_hashes(fit_props, data)
            updated_images = 0
            for dtb_idx, old_crc_be, new_crc_be, old_sha1, new_sha1 in modified_dtbs_digests:
                matched_image = None
                for image_node, algomap in image_hash_map.items():
                    crc_prop = algomap.get("crc32")
                    sha1_prop = algomap.get("sha1")
                    if not crc_prop or not sha1_prop:
                        continue
                    current_crc = read_prop_bytes(data, crc_prop)
                    current_sha1 = read_prop_bytes(data, sha1_prop)
                    if current_crc == old_crc_be and current_sha1 == old_sha1:
                        matched_image = (image_node, crc_prop, sha1_prop)
                        break
                if not matched_image:
                    print(
                        "Warning: Could not find matching FIT hash nodes for modified "
                        "DTB (old digests not present)."
                    )
                    continue
                image_node, crc_prop, sha1_prop = matched_image
                data[crc_prop.value_offset : crc_prop.value_offset + 4] = new_crc_be
                data[sha1_prop.value_offset : sha1_prop.value_offset + 20] = new_sha1
                updated_images += 1
                msg = (
                    f"Updated FIT hashes for {image_node}: crc32 -> {new_crc_be.hex()} "
                    f"sha1 -> {new_sha1.hex()}"
                )
                print(msg)
                summary_lines.append(msg)
            if updated_images == 0:
                print("Warning: No FIT hashes updated (digest match not found).")
            else:
                line = f"FIT hash update completed for {updated_images} image(s)"
                print(line)
                summary_lines.append(line)

    return total_changes, summary_lines


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Generic DTB patcher driven by INI config (LED gpios, etc.)"
    )
    ap.add_argument("firmware", help="Input firmware .bin")
    ap.add_argument(
        "-o",
        "--output",
        help="Output file (default: <profile>-<basename> from config). Cannot be used when processing multiple boards.",
    )
    ap.add_argument(
        "--dtb-index",
        type=int,
        default=None,
        help="(Legacy) force DTB index when config omits dtb_index; otherwise use config dtb_index / auto-detect",
    )
    ap.add_argument(
        "--config",
        default="leds.ini",
        help="INI config file with profiles (default: leds.ini)",
    )
    ap.add_argument(
        "-b",
        "--board",
        dest="profile",
        required=False,
        help="Board/profile name (INI section name, e.g. komi-a31). If not specified, all boards will be processed.",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="List DTBs and LED nodes then exit",
    )
    ap.add_argument(
        "--no-fit-hash",
        action="store_true",
        help="Do NOT auto-update FIT image hash values for modified fdt image",
    )
    args = ap.parse_args()

    with open(args.firmware, "rb") as f:
        original_data = bytearray(f.read())

    dtbs = scan_dtbs(original_data)
    if not dtbs:
        print("No DTB found", file=sys.stderr)
        return 1

    # 列表模式: 打印 DTB 和 /leds 节点信息
    led_presence = []  # list[(idx, has_green)]
    for i, (off, hdr) in enumerate(dtbs):
        props = parse_properties(original_data, off, hdr)
        has_green = any(p.node_path.endswith("/green") for p in props)
        led_presence.append((i, has_green))
        if args.list:
            led_nodes = sorted(
                set(p.node_path for p in props if p.node_path.startswith("/leds"))
            )
            print(
                f"[DTB {i}] offset=0x{off:X} total={hdr.totalsize} "
                f"LED nodes: {', '.join(led_nodes) if led_nodes else '-'}"
            )
    if args.list:
        return 0

    # 始终按 INI 解析；若未指定 --config，则默认使用 leds.ini
    try:
        configs = load_ini_config(args.config, getattr(args, "profile", None))
    except Exception as e:
        print(f"Failed to load config {args.config}: {e}", file=sys.stderr)
        return 1

    # 如果没有指定 board 但指定了 output，则报错
    if len(configs) > 1 and args.output:
        print(
            "Error: Cannot specify --output when processing multiple boards. "
            "Each board will generate its own output file.",
            file=sys.stderr
        )
        return 1

    # 处理所有 profiles
    all_success = True
    generated_files = []
    
    for cfg in configs:
        print(f"\n{'='*60}")
        print(f"Processing board: {cfg.profile}")
        print(f"{'='*60}")
        
        # 为每个 profile 创建独立的数据副本
        data = bytearray(original_data)
        
        total_changes, summary_lines = process_single_profile(cfg, data, dtbs, args)
        
        if total_changes == 0:
            print(f"No changes applied for {cfg.profile} (all values already set to target values or properties not found)")
            # 如果只处理一个 profile，则返回错误码
            if len(configs) == 1:
                return 2
            # 如果处理多个 profiles，继续处理下一个
            continue

        # 输出文件名
        if args.output:
            out_path = args.output
        else:
            base_name = os.path.basename(args.firmware)
            out_path = f"{cfg.profile}-{base_name}"

        if os.path.abspath(out_path) == os.path.abspath(args.firmware):
            print(f"Error: Refusing to overwrite input for {cfg.profile} (choose different -o)", file=sys.stderr)
            all_success = False
            continue

        try:
            with open(out_path, "wb") as f:
                f.write(data)
            print(f"Wrote patched firmware: {out_path} (changes: {total_changes})")
            generated_files.append(out_path)
            if summary_lines:
                print("Summary:")
                for line in summary_lines:
                    print("  " + line)
        except Exception as e:
            print(f"Error writing output for {cfg.profile}: {e}", file=sys.stderr)
            all_success = False

    # 最终总结
    if len(configs) > 1:
        print(f"\n{'='*60}")
        print(f"All boards processing completed")
        print(f"{'='*60}")
        print(f"Total boards processed: {len(configs)}")
        print(f"Firmware files generated: {len(generated_files)}")
        if generated_files:
            print("\nGenerated files:")
            for f in generated_files:
                print(f"  - {f}")

    # Return success only if all operations succeeded and at least one file was generated
    if not all_success:
        return 1
    if len(generated_files) == 0:
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("Interrupted", file=sys.stderr)
        raise SystemExit(130)

