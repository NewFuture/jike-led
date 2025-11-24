#!/usr/bin/env python3
"""Extract LED information from mt7981 device tree files in bl-mt798x repository.

This script:
1. Fetches all mt7981 device tree files from https://github.com/hanwckf/bl-mt798x
2. Parses them to extract LED GPIO information
3. Updates leds.ini with the extracted configurations
"""
import re
import sys
import urllib.request
import json
from typing import Dict, List, Tuple, Optional
from collections import defaultdict


def fetch_file_list() -> List[str]:
    """Fetch list of mt7981 device tree files from bl-mt798x repository."""
    api_url = "https://api.github.com/repos/hanwckf/bl-mt798x/git/trees/master?recursive=1"
    with urllib.request.urlopen(api_url) as response:
        data = json.loads(response.read().decode())
    
    mt7981_files = [
        item['path'] for item in data.get('tree', [])
        if 'uboot-mtk-20220606/arch/arm/dts/mt7981-' in item['path'] 
        and item['path'].endswith('.dts')
        and 'fpga' not in item['path']  # Skip FPGA test boards
        and 'rfb' not in item['path']   # Skip reference boards
    ]
    return sorted(mt7981_files)


def fetch_dts_content(file_path: str) -> str:
    """Fetch the content of a device tree file from GitHub."""
    raw_url = f"https://raw.githubusercontent.com/hanwckf/bl-mt798x/master/{file_path}"
    try:
        with urllib.request.urlopen(raw_url) as response:
            return response.read().decode('utf-8', errors='ignore')
    except Exception as e:
        print(f"Warning: Failed to fetch {file_path}: {e}", file=sys.stderr)
        return ""


def extract_board_name(file_path: str) -> str:
    """Extract board name from file path."""
    # From uboot-mtk-20220606/arch/arm/dts/mt7981-{boardname}.dts
    filename = file_path.split('/')[-1]
    board_name = filename.replace('mt7981-', '').replace('.dts', '')
    return board_name


def parse_led_gpios(content: str) -> Dict[str, Optional[int]]:
    """Parse LED GPIO information from device tree content.
    
    Returns a dict mapping LED color names to GPIO numbers.
    """
    leds_info: Dict[str, Optional[int]] = {}
    
    # Find the leds section using brace counting for proper nesting
    leds_start = content.find('leds {')
    if leds_start == -1:
        return leds_info
    
    # Find matching closing brace
    brace_count = 0
    i = leds_start + len('leds {')
    start_i = i
    leds_section = ""
    
    while i < len(content):
        if content[i] == '{':
            brace_count += 1
        elif content[i] == '}':
            if brace_count == 0:
                leds_section = content[start_i:i]
                break
            else:
                brace_count -= 1
        i += 1
    
    if not leds_section:
        return leds_info
    
    # Find individual LED definitions
    # Pattern: led@N { label = "color:name"; gpios = <&gpio N M>; }
    led_pattern = re.compile(
        r'(led@\d+|[\w-]+)\s*{([^}]*)}',
        re.DOTALL
    )
    
    for led_match in led_pattern.finditer(leds_section):
        led_name = led_match.group(1)
        led_block = led_match.group(2)
        
        # Extract gpios property: gpios = <&gpio N M> or <&pio N M>;
        # We want the first number (N) which is the GPIO pin number
        gpios_match = re.search(r'gpios\s*=\s*<&(gpio|pio)\s+(\d+)\s+\w+>', led_block)
        if not gpios_match:
            continue
            
        gpio_num = int(gpios_match.group(2))
        
        # Check for label to get color information
        label_match = re.search(r'label\s*=\s*"([^"]*)"', led_block)
        if label_match:
            label = label_match.group(1)
            # Extract color from label (e.g., "green:system" -> "green")
            color_match = re.match(r'(\w+):', label)
            if color_match:
                color = color_match.group(1)
                leds_info[color] = gpio_num
            else:
                # Use the label as-is if no color prefix
                leds_info[label] = gpio_num
        else:
            # No label, use led name
            leds_info[led_name] = gpio_num
    
    return leds_info


def format_ini_section(board_name: str, leds: Dict[str, Optional[int]]) -> str:
    """Format LED information as INI section."""
    if not leds:
        return ""
    
    lines = [f"[{board_name}]"]
    # Add a comment about dtb_index
    lines.append("; dtb_index = N  ; Optional: specify DTB index if needed")
    
    # Sort LEDs by name for consistency
    for led_name in sorted(leds.keys()):
        gpio_num = leds[led_name]
        if gpio_num is not None:
            # Format as "led_name = from->to" where from is a placeholder
            # Users can update the 'from' value based on their specific needs
            lines.append(f"{led_name} = {gpio_num}->{gpio_num}")
    lines.append("")
    return "\n".join(lines)


def main():
    """Main entry point."""
    print("Fetching mt7981 device tree file list...")
    file_list = fetch_file_list()
    print(f"Found {len(file_list)} device tree files")
    
    # Track boards with LED information
    boards_with_leds: Dict[str, Dict[str, Optional[int]]] = {}
    
    for file_path in file_list:
        board_name = extract_board_name(file_path)
        print(f"Processing {board_name}...", end=" ")
        
        content = fetch_dts_content(file_path)
        if not content:
            print("SKIP (fetch failed)")
            continue
        
        leds = parse_led_gpios(content)
        if leds:
            boards_with_leds[board_name] = leds
            print(f"OK ({len(leds)} LEDs: {', '.join(leds.keys())})")
        else:
            print("SKIP (no LEDs)")
    
    print(f"\nFound {len(boards_with_leds)} boards with LED configurations")
    
    # Generate INI content
    print("\nGenerating leds.ini content...")
    ini_sections = []
    
    # Add comment header
    ini_sections.append("; MT7981 LED GPIO configurations extracted from bl-mt798x repository")
    ini_sections.append("; https://github.com/hanwckf/bl-mt798x/tree/master/uboot-mtk-20220606/arch/arm/dts")
    ini_sections.append(";")
    ini_sections.append("; Format: led_color = from_gpio->to_gpio")
    ini_sections.append("; The GPIO numbers below are from the bl-mt798x device trees.")
    ini_sections.append("; Update the 'from' values based on your specific firmware requirements.")
    ini_sections.append("")
    
    # Add sections for each board
    for board_name in sorted(boards_with_leds.keys()):
        leds = boards_with_leds[board_name]
        section = format_ini_section(board_name, leds)
        if section:
            ini_sections.append(section)
    
    # Write updated leds.ini
    new_content = "\n".join(ini_sections)
    
    # Write to leds.ini directly
    output_file = "leds.ini"
    with open(output_file, "w", encoding="utf-8") as f:
        f.write(new_content)
    
    print(f"\nWrote {output_file} with {len(boards_with_leds)} board configurations")
    print("\nIMPORTANT: The GPIO values are set as identity mappings (N->N).")
    print("You need to update the 'from' values based on your original firmware")
    print("if the GPIO numbers differ between firmwares.")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
