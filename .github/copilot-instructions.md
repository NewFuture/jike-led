# GitHub Copilot Instructions for `fix_led.py`

This file contains special-purpose firmware tooling. When editing it, Copilot should follow these guidelines:

## Purpose

- `fix_led.py` is a generic DTB patcher for router firmware images.
- It:
  - Scans a firmware `.bin` file for DTB (FDT) blobs (`0xD00DFEED` magic).
  - Modifies `/leds/*:gpios` properties **in-place**, only changing the second `u32` of a 3x `u32` array.
  - Recomputes the modified DTB's CRC32 and SHA1.
  - Updates the outer FIT image DTB (`/images/*/hash-*`) hashes so U-Boot verification still passes.

## Configuration Model

- The script is **driven only by an INI file** (no JSON, no other formats).
- Default config file name: `leds.ini` (can be overridden with `--config`).
- Each INI section is a **board profile**, e.g.:

  ```ini
  [komi-a31]
  dtb_index = 1          ; optional, 0-based index of DTB to patch
  green = 8              ; maps to /leds/green:gpios second u32
  red   = 34             ; maps to /leds/red:gpios second u32
  ```

- Any key except `dtb_index` is treated as an LED name:
  - Node path: `/leds/<name>`
  - Property: `gpios`
  - Kind: `"u32_triplet"`
  - Value format: `<target_value>`; supports decimal or `0x` hex (e.g., `8` or `0x8`).

## CLI Contract

- Main entry: `python3 fix_led.py firmware.bin [options]`
- Important options:
  - `-b`, `--board`:
    - Maps to the INI section name (board/profile).
    - Internally stored as `args.profile` and passed to `load_ini_config`.
  - `--config`:
    - INI file path, default `"leds.ini"`.
  - `-o`, `--output`:
    - Output firmware path; if omitted, defaults to `<profile>-<basename>`.
  - `--dtb-index`:
    - Legacy override when config omits `dtb_index`; prefer INI `dtb_index`.
  - `--list`:
    - Print DTB & `/leds` info only, do not modify file.
  - `--no-fit-hash`:
    - Do **not** update FIT hashes (for debugging only; resulting image may not boot).

## Implementation Constraints

When Copilot suggests changes to this file, it must respect:

1. **Do not change DTB size**
   - All modifications must be in-place.
   - Do not modify `totalsize` or move DTB blobs.
   - Only touch fixed-size properties (currently `12`-byte `gpios` values).

2. **Hash logic is critical**
   - `compute_crc32()` must continue to use `binascii.crc32(data) & 0xffffffff` and pack big-endian.
   - After patching a DTB slice, recompute:
     - CRC32 (4 bytes, big-endian).
     - SHA1 (20-byte digest).
   - FIT hash update must:
     - Find `/images/*/hash-*` nodes with `algo = "crc32"` and `"sha1"`.
     - Match old CRC+SHA1 first; only then overwrite `value`.

3. **INI-only configuration**
   - Do **not** re-introduce JSON config or other formats.
   - All new mapping types should extend `load_ini_config()` and `MappingRule`/`TargetConfig`/`PatchConfig`.

4. **CLI stability**
   - Keep existing option names and semantics:
     - `-b/--board` (dest=`profile`)
     - `--config`, `--dtb-index`, `--list`, `--no-fit-hash`, `-o/--output`
   - Backwards-incompatible CLI changes should **not** be suggested by default.

5. **Safety / UX**
   - Never silently overwrite the input firmware:
     - The check `if os.path.abspath(out_path) == os.path.abspath(args.firmware)` must remain.
   - Warnings should be explicit when:
     - A node/property is missing.
     - No matching FIT hash nodes are found.

## What Copilot May Help With

- Adding support for **more property kinds** via `MappingRule.kind`:
  - e.g. other fixed-size `u32` arrays, simple strings (without size changes).
- Improving logging and summary output (without changing behavior).
- Extending `README.md` and `leds.ini` examples for new boards.

## What Copilot Should Avoid

- Changing DTB parsing logic (`scan_dtbs`, `parse_properties`, `collect_node_paths`) in a way that risks missing valid DTBs.
- Changing the hash update contract or removing digest matching.
- Introducing non-standard-library dependencies (must stay pure stdlib Python).
- Refactoring into multiple files or packages; keep it as a single self-contained script.
