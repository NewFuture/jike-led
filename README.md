# DTB LED for Gecoos AP

[English](#english) | [中文](#中文)

---

## 中文

修改集客 Gecoos AP 固件中 DTB (Device Tree Blob) LED 的小工具脚本，修复不同MTK 机型的 LED 映射等问题。

### ⚠️ 重要提示

> [!WARNING]
> 1. **修改后的固件缺少完整签名，只能通过 U-Boot 上传，不能直接升级写入。**
> 2. **强烈建议在修改前备份原始配置。**
> 3. **刷写错误的固件可能导致设备变砖，请确保了解恢复方法。**

> [!NOTE]
> - 如果你的机型不存在，请在 [leds.ini](leds.ini) 配置文件中添加型号配置, 支持的机型列表可在 `leds.ini` 文件中查看。
> - 本工具仅修改 LED GPIO 映射，不改变固件的其他功能。

### 快速开始

#### 方式 1: 使用自动发布的固件（推荐）

> [!TIP]
> 本仓库会自动从官方网站下载最新固件并为所有支持的机型打补丁，发布到 [GitHub Releases](https://github.com/NewFuture/jike-led/releases)。

1. **访问 [Releases 页面](https://github.com/NewFuture/jike-led/releases)**
2. **下载与你的路由器型号匹配的固件**
   - 文件名格式：`<机型名>-JIKEAP_AP250MD*.bin`
   - 例如：`konka_komi-a31-JIKEAP_AP250MDV_MT7981_K5_NAND_8.1_2025102100.bin`
3. **通过 U-Boot 刷入固件**

#### 方式 2: 手动打补丁


#### 系统要求

- Python 3.6 或更高版本（推荐 3.7+）
- 无需额外依赖，仅使用 Python 标准库

1. **克隆或下载本仓库**
   ```bash
   git clone https://github.com/NewFuture/jike-led.git
   cd jike-led
   ```

2. **准备固件文件**
   - 将需要修改的固件文件（如 `firmware.bin`）放在仓库目录中

3. **运行脚本**
   ```bash
   # 最简单的用法：为所有已配置机型批量生成固件
   python3 fix_led.py firmware.bin
   
   # 或者指定单个机型
   python3 fix_led.py firmware.bin -b komi-a31
   ```

### 基本用法

**批量处理模式（推荐）**
```bash
# 不指定机型：为 leds.ini 中所有机型生成对应固件
python3 fix_led.py firmware.bin
```
这会为每个已配置的机型生成对应的固件文件，例如：
- `komi-a31-firmware.bin`
- `fur602-firmware.bin`
- `360t7-firmware.bin`
- ... (所有 leds.ini 中配置的机型)

**单机型处理模式**
```bash
# 只处理指定的机型
python3 fix_led.py firmware.bin -b komi-a31

# 或使用完整参数名
python3 fix_led.py firmware.bin --board komi-a31
```

### 高级用法

#### 自定义输出文件名

在单机型模式下，可以使用 `-o` 或 `--output` 参数指定输出文件名：

```bash
python3 fix_led.py firmware.bin -b komi-a31 -o my-custom-firmware.bin
```

> [!NOTE]
> 批量模式下不能使用 `-o` 参数，因为需要为多个机型生成不同的文件。

#### 使用自定义配置文件

如果配置文件不在默认位置，可以使用 `--config` 参数指定：

```bash
python3 fix_led.py firmware.bin --config /path/to/custom-leds.ini -b komi-a31
```

#### 查看固件信息（不修改）

使用 `--list` 参数可以查看固件中的 DTB 和 LED 节点信息，而不进行任何修改：

```bash
python3 fix_led.py firmware.bin --list
```

输出示例：
```
Found 2 DTB(s):
DTB 0: offset=0x123400, size=12345 bytes
DTB 1: offset=0x456700, size=23456 bytes
  /leds/green: gpios = [0x00, 0x04, 0x01]
  /leds/red:   gpios = [0x00, 0x05, 0x01]
```

#### 指定 DTB 索引（高级）

如果需要强制指定要修改的 DTB 索引，可以使用 `--dtb-index` 参数：

```bash
python3 fix_led.py firmware.bin -b komi-a31 --dtb-index 1
```

> [!TIP]
> 通常不需要手动指定 DTB 索引，脚本会自动检测包含 `/leds/*` 节点的 DTB。

#### 禁用 FIT Hash 更新（调试用）

```bash
python3 fix_led.py firmware.bin -b komi-a31 --no-fit-hash
```

> [!WARNING]
> 使用 `--no-fit-hash` 生成的固件可能无法通过 U-Boot 验证而无法启动，仅用于测试和对比。

### 配置文件说明

#### 配置文件格式

脚本使用 INI 格式的配置文件（默认为 `leds.ini`），每个 section 代表一个机型（board profile）。

#### 基本配置示例

```ini
[komi-a31]
# dtb_index：可选参数，指定要修改的 DTB 索引（从 0 开始）
# 如果不指定，脚本会自动查找包含相应 LED 节点的 DTB
dtb_index = 1

# LED 配置：<LED名称> = <GPIO引脚号>
# 支持十进制（如 8）和十六进制（如 0x8）
green = 8      # 绿灯对应 GPIO 8，映射到 /leds/green:gpios 的第二个 u32
red   = 34     # 红灯对应 GPIO 34，映射到 /leds/red:gpios 的第二个 u32
```

#### 集客固件 LED 说明

集客固件通常只有**红色**和**绿色**两个可配置的 LED 灯：
- **green**：系统状态指示灯（通常为绿色，你也可以改成其它颜色）
- **red**：系统状态指示灯（通常为红色）

#### 配置规则

- **section 名称**：机型标识符（如 `[komi-a31]`），用于 `-b` 参数
- **dtb_index**：（可选）DTB 索引，省略时自动检测
- **LED 配置**：
  - 键：LED 名称（对应 `/leds/<name>` 节点）
  - 值：目标 GPIO 引脚号
  - 修改的是 `gpios` 属性中三个 u32 值的**第二个值**
- **注释**：支持 `;` 和 `#` 作为注释符号
- **数值格式**：支持十进制（`8`）和十六进制（`0x8`）
- **修改方式**：所有修改都在原地进行，不会改变 DTB 长度，也不会移动其它数据

#### 多机型配置示例

```ini
# FUR602 路由器
[fur602]
dtb_index = 1
green = 8
red   = 13

# 360T7 路由器
[360t7]
dtb_index = 1
green = 7
red   = 3
```

#### 输出文件命名

- **批量模式**（不指定 `-b`）：为每个机型生成 `<机型>-<原文件名>`
  - 例如：`komi-a31-firmware.bin`、`fur602-firmware.bin`
- **单机型模式**（指定 `-b`）：生成 `<机型>-<原文件名>`
  - 例如：`komi-a31-firmware.bin`
- **自定义输出**：使用 `-o` 参数指定（仅单机型模式）

#### 添加新机型配置

如果你的机型未在 `leds.ini` 中配置：

1. **查看固件信息**
   ```bash
   python3 fix_led.py your-firmware.bin --list
   ```

2. **确定 LED GPIO 引脚**
   - 查看输出中的 `/leds/green` 和 `/leds/red` 节点
   - 记录 `gpios` 属性中的第二个值（通常是 0x04、0x05 等）
   - 确定你需要修改成的目标 GPIO 值

3. **添加配置到 leds.ini**
   ```ini
   [your-model-name]
   dtb_index = 1    # 通常是 1，也可以不指定让脚本自动检测
   green = <你的绿灯GPIO>
   red   = <你的红灯GPIO>
   ```

4. **测试配置**
   ```bash
   python3 fix_led.py your-firmware.bin -b your-model-name --list
   python3 fix_led.py your-firmware.bin -b your-model-name
   ```

5. **提交配置**（可选）
   - 如果配置成功，欢迎提交 Pull Request 分享你的配置
   - 这样其他用户也能受益

### 支持的机型列表

当前 `leds.ini` 已配置的机型包括：

- **fur602** - FUR602 路由器
- **komi-a31_blue** - Komi A31（使用蓝灯）
- **360t7** - 360 T7 路由器
- **abt_asr3000** - ABT ASR3000
- **cetron_ct3003** - Cetron CT3003
- **cmcc-rax3000m** - 中国移动 RAX3000M
- **cmcc-rax3000m-emmc** - 中国移动 RAX3000M (eMMC版本)
- **cmcc_a10** - 中国移动 A10
- **h3c_magic-nx30-pro** - H3C Magic NX30 Pro
- **honor_fur-602** - 荣耀 FUR-602
- **imou_lc-hx3001** - 乐橙 LC-HX3001
- **konka_komi-a31** - 康佳 Komi A31
- **livinet_zr-3020** - Livinet ZR-3020
- **newland_nl-wr8103** - 新大陆 NL-WR8103
- **newland_nl-wr9103** - 新大陆 NL-WR9103
- **nokia-ea0326gmp** - Nokia EA0326GMP
- **openembed-som7981** - OpenEmbed SOM7981

> [!TIP]
> 完整列表请查看 [`leds.ini`](leds.ini) 文件。

### 工作原理

1. **扫描 DTB**
   - 在固件镜像中查找所有 DTB (Device Tree Blob) 结构
   - 使用魔数 `0xD00DFEED` 识别 DTB

2. **定位目标节点**
   - 根据配置找到对应的 `/leds/<name>` 节点
   - 定位节点的 `gpios` 属性

3. **修改 GPIO 值**
   - 修改 `gpios` 属性中三个 u32 值的第二个值
   - 保持 DTB 总大小不变（原地修改）

4. **更新校验和**
   - 重新计算修改后 DTB 的 CRC32 和 SHA1
   - 在外层 FIT 镜像中更新对应的 `hash-*` 节点值
   - 确保 U-Boot 能够验证固件完整性

### 常见问题（FAQ）

#### Q: 修改后的固件为什么不能直接升级？
A: 修改后的固件缺少完整的厂商签名，只能通过 U-Boot 上传。直接升级可能导致签名验证失败。

#### Q: 脚本会修改固件的其他功能吗？
A: 不会。脚本仅修改 LED GPIO 映射，不会改变固件的网络、WiFi、安全等其他功能。

#### Q: 如何确定我的机型需要哪些 GPIO 值？
A: 使用 `--list` 参数查看当前固件的 LED 配置，或参考同型号其他用户的配置。也可以查阅硬件原理图。

#### Q: 修改失败怎么办？
A: 
- 确保原始固件文件完好无损
- 使用 `--list` 检查固件是否包含 DTB 和 LED 节点
- 检查配置文件语法是否正确
- 查看错误信息中的提示

#### Q: 刷错固件导致设备无法启动怎么办？
A: 
- 通过 U-Boot 恢复模式重新刷入原始固件
- 具体恢复方法请参考路由器的官方文档或社区教程
- **建议修改前备份原始固件**

#### Q: 可以同时修改多个机型吗？
A: 可以。不指定 `-b` 参数时，脚本会为 `leds.ini` 中的所有机型生成对应的固件文件。

#### Q: fix_led_fur602.py 和 fix_led.py 有什么区别？
A: 
- `fix_led.py`：通用版本，支持通过 INI 配置文件管理多个机型（**推荐使用**）
- `fix_led_fur602.py`：早期版本，专门为 FUR602 和 Komi-A31 设计，功能较少

新用户建议使用 `fix_led.py`，它更灵活、功能更完善。

### 故障排除

#### 问题：找不到 DTB
```
Warning: no DTB contains any of nodes ...
```
**解决方案**：
- 确认固件文件是否正确
- 使用 `--list` 查看固件中是否存在 DTB
- 某些固件可能使用不同的结构，暂不支持

#### 问题：属性值不匹配
```
No change / mismatch for /leds/green:gpios (expected second 0x4)
```
**解决方案**：
- 使用 `--list` 查看实际的 GPIO 值
- 更新配置文件中的预期值
- 或者删除配置中的预期值检查

#### 问题：无法写入输出文件
```
Error: Cannot write to output file
```
**解决方案**：
- 检查文件权限
- 确保磁盘空间充足
- 不要覆盖输入文件（脚本会阻止此操作）

### 技术细节

#### DTB 结构

Device Tree Blob (DTB) 是一种二进制格式，用于描述硬件配置：
- **Magic Number**: `0xD00DFEED` (大端序)
- **Header**: 包含版本、大小、偏移量等信息
- **Structure Block**: 树形节点结构
- **Strings Block**: 字符串表

#### GPIO 属性格式

LED 的 `gpios` 属性通常包含三个 u32 值：
```
gpios = <phandle gpio-num flags>
```
- **phandle**: GPIO 控制器的引用（第一个值）
- **gpio-num**: GPIO 引脚号（第二个值，本工具修改的目标）
- **flags**: 标志位（第三个值，如高/低电平有效）

本工具只修改第二个值（gpio-num），保持其他值不变。

#### FIT 镜像

FIT (Flattened Image Tree) 是 U-Boot 使用的镜像格式：
- 包含内核、DTB、文件系统等多个组件
- 每个组件都有对应的哈希值用于验证
- 修改 DTB 后必须更新哈希值，否则 U-Boot 会拒绝启动

### 小提示

- **备份原始固件**：在修改前务必保存原始固件文件
- **先测试查看**：使用 `--list` 参数先查看固件信息，不做修改
- **单机型测试**：修改新机型时，先用 `-b` 参数单独测试
- **查看输出信息**：脚本会输出详细的修改信息，注意查看是否有警告
- **版本管理**：建议使用 Git 管理配置文件，方便回退
- **社区分享**：成功配置新机型后，欢迎分享配置帮助其他用户

### 贡献指南

欢迎贡献新机型配置或改进建议！

1. **Fork 本仓库**
2. **添加或修改配置**
   - 在 `leds.ini` 中添加新机型配置
   - 测试确保配置正确
3. **提交 Pull Request**
   - 说明机型名称和测试情况
   - 提供必要的硬件信息

### 许可证

本项目采用 [Apache License 2.0](LICENSE) 许可证。

### 免责声明

- 本工具仅供学习和研究使用
- 使用本工具修改固件的风险由用户自行承担
- 作者不对因使用本工具造成的设备损坏或数据丢失负责
- 请确保了解固件修改的风险和恢复方法后再使用

---

## English

A utility script to modify LED configurations in DTB (Device Tree Blob) within Jike Gecoos AP firmware, fixing LED mapping issues for different router models.

### ⚠️ Important Warnings

> [!WARNING]
> 1. **This tool has not been thoroughly tested. Use at your own risk.**
> 2. **Modified firmware lacks complete signature and can only be uploaded via U-Boot, not through direct upgrade.**
> 3. **Strongly recommend backing up original firmware before modification.**
> 4. **Flashing incorrect firmware may brick your device. Ensure you know recovery methods.**

> [!NOTE]
> - If your model is not listed, add it to the [`leds.ini`](leds.ini) configuration file.
> - See `leds.ini` for the list of supported models.
> - This tool only modifies LED GPIO mappings, not other firmware functionality.

### System Requirements

- Python 3.6 or higher (3.7+ recommended)
- No external dependencies, uses Python standard library only

### Quick Start

#### Option 1: Use Automated Releases (Recommended)

> [!TIP]
> This repository automatically downloads the latest firmware from the official website and patches it for all supported models, publishing to [GitHub Releases](https://github.com/NewFuture/jike-led/releases).

1. **Visit the [Releases page](https://github.com/NewFuture/jike-led/releases)**
2. **Download the firmware matching your router model**
   - Filename format: `<model-name>-JIKEAP_AP250MD*.bin`
   - Example: `konka_komi-a31-JIKEAP_AP250MDV_MT7981_K5_NAND_8.1_2025102100.bin`
3. **Flash via U-Boot recovery mode**

#### Option 2: Manual Patching

1. **Clone or download this repository**
   ```bash
   git clone https://github.com/NewFuture/jike-led.git
   cd jike-led
   ```

2. **Prepare firmware file**
   - Place your firmware file (e.g., `firmware.bin`) in the repository directory

3. **Run the script**
   ```bash
   # Simplest usage: batch process all configured models
   python3 fix_led.py firmware.bin
   
   # Or specify a single model
   python3 fix_led.py firmware.bin -b komi-a31
   ```

### Basic Usage

**Batch Processing Mode (Recommended)**
```bash
# Without specifying model: generate firmware for all models in leds.ini
python3 fix_led.py firmware.bin
```
This generates firmware files for each configured model:
- `komi-a31-firmware.bin`
- `fur602-firmware.bin`
- `360t7-firmware.bin`
- ... (all models configured in leds.ini)

**Single Model Mode**
```bash
# Process only the specified model
python3 fix_led.py firmware.bin -b komi-a31

# Or use full parameter name
python3 fix_led.py firmware.bin --board komi-a31
```

### Advanced Usage

#### Custom Output Filename

In single model mode, use `-o` or `--output` to specify output filename:

```bash
python3 fix_led.py firmware.bin -b komi-a31 -o my-custom-firmware.bin
```

> [!NOTE]
> Cannot use `-o` in batch mode, as it needs to generate different files for multiple models.

#### Custom Configuration File

If configuration file is not in default location, use `--config`:

```bash
python3 fix_led.py firmware.bin --config /path/to/custom-leds.ini -b komi-a31
```

#### View Firmware Information (Without Modification)

Use `--list` to view DTB and LED node information without making changes:

```bash
python3 fix_led.py firmware.bin --list
```

Example output:
```
Found 2 DTB(s):
DTB 0: offset=0x123400, size=12345 bytes
DTB 1: offset=0x456700, size=23456 bytes
  /leds/green: gpios = [0x00, 0x04, 0x01]
  /leds/red:   gpios = [0x00, 0x05, 0x01]
```

#### Specify DTB Index (Advanced)

To force a specific DTB index, use `--dtb-index`:

```bash
python3 fix_led.py firmware.bin -b komi-a31 --dtb-index 1
```

> [!TIP]
> Usually not needed to manually specify DTB index. Script auto-detects DTBs containing `/leds/*` nodes.

#### Disable FIT Hash Update (Debugging)

```bash
python3 fix_led.py firmware.bin -b komi-a31 --no-fit-hash
```

> [!WARNING]
> Firmware generated with `--no-fit-hash` may fail U-Boot verification and won't boot. For testing only.

### Configuration File

#### Configuration Format

Script uses INI format configuration file (default: `leds.ini`). Each section represents a board profile.

#### Basic Configuration Example

```ini
[komi-a31]
# dtb_index: optional, specifies DTB index to modify (0-based)
# If not specified, script auto-detects DTB containing LED nodes
dtb_index = 1

# LED configuration: <LED_name> = <GPIO_pin>
# Supports decimal (e.g., 8) and hexadecimal (e.g., 0x8)
green = 8      # Green LED on GPIO 8, maps to /leds/green:gpios second u32
red   = 34     # Red LED on GPIO 34, maps to /leds/red:gpios second u32
```

#### Jike Firmware LED Description

Jike firmware typically has two configurable LEDs:
- **green**: System status indicator (usually green)
- **red**: System status indicator (usually red, some models may use blue)

#### Configuration Rules

- **Section name**: Model identifier (e.g., `[komi-a31]`), used with `-b` parameter
- **dtb_index**: (Optional) DTB index, auto-detected if omitted
- **LED configuration**:
  - Key: LED name (corresponds to `/leds/<name>` node)
  - Value: Target GPIO pin number
  - Modifies the **second value** of three u32 values in `gpios` property
- **Comments**: Supports `;` and `#` as comment prefixes
- **Number format**: Supports decimal (`8`) and hexadecimal (`0x8`)
- **Modification method**: All changes are in-place, won't change DTB size or move data

#### Adding New Model Configuration

If your model is not configured in `leds.ini`:

1. **View firmware information**
   ```bash
   python3 fix_led.py your-firmware.bin --list
   ```

2. **Determine LED GPIO pins**
   - Check `/leds/green` and `/leds/red` nodes in output
   - Note the second value in `gpios` property
   - Determine target GPIO values you need

3. **Add configuration to leds.ini**
   ```ini
   [your-model-name]
   dtb_index = 1    # Usually 1, or omit for auto-detection
   green = <your_green_GPIO>
   red   = <your_red_GPIO>
   ```

4. **Test configuration**
   ```bash
   python3 fix_led.py your-firmware.bin -b your-model-name --list
   python3 fix_led.py your-firmware.bin -b your-model-name
   ```

5. **Submit configuration** (Optional)
   - If successful, welcome to submit Pull Request to share
   - This helps other users with the same model

### Supported Models

Currently configured models in `leds.ini`:

- **fur602** - FUR602 Router
- **komi-a31_blue** - Komi A31 (using blue LED)
- **360t7** - 360 T7 Router
- **abt_asr3000** - ABT ASR3000
- **cetron_ct3003** - Cetron CT3003
- **cmcc-rax3000m** - China Mobile RAX3000M
- **cmcc-rax3000m-emmc** - China Mobile RAX3000M (eMMC version)
- **cmcc_a10** - China Mobile A10
- **h3c_magic-nx30-pro** - H3C Magic NX30 Pro
- **honor_fur-602** - Honor FUR-602
- **imou_lc-hx3001** - IMOU LC-HX3001
- **konka_komi-a31** - Konka Komi A31
- **livinet_zr-3020** - Livinet ZR-3020
- **newland_nl-wr8103** - Newland NL-WR8103
- **newland_nl-wr9103** - Newland NL-WR9103
- **nokia-ea0326gmp** - Nokia EA0326GMP
- **openembed-som7981** - OpenEmbed SOM7981

> [!TIP]
> See [`leds.ini`](leds.ini) for complete list.

### How It Works

1. **Scan DTB**: Finds all DTB structures in firmware using magic number `0xD00DFEED`
2. **Locate Target Nodes**: Finds `/leds/<name>` nodes and their `gpios` properties
3. **Modify GPIO Values**: Changes second u32 value in `gpios` property (in-place)
4. **Update Checksums**: Recalculates CRC32 and SHA1, updates FIT image hashes

### FAQ

**Q: Why can't modified firmware be upgraded directly?**  
A: Modified firmware lacks vendor signature and can only be uploaded via U-Boot.

**Q: Does the script modify other firmware functionality?**  
A: No. Only modifies LED GPIO mappings, not network, WiFi, security, etc.

**Q: How to determine GPIO values for my model?**  
A: Use `--list` to view current LED configuration, or refer to configurations from other users with the same model.

**Q: What if modification fails?**  
A:
- Ensure original firmware file is intact
- Use `--list` to check if firmware contains DTB and LED nodes
- Verify configuration file syntax
- Check error messages for hints

**Q: What if I flash wrong firmware?**  
A: Use U-Boot recovery mode to flash original firmware. **Always backup before modifying.**

**Q: Can I modify multiple models simultaneously?**  
A: Yes. Without specifying `-b`, script generates firmware for all models in `leds.ini`.

**Q: Difference between fix_led_fur602.py and fix_led.py?**  
A: `fix_led.py` is the newer, recommended version supporting multiple models via INI config. `fix_led_fur602.py` is the older version for specific models only.

### Troubleshooting

#### Issue: DTB not found
```
Warning: no DTB contains any of nodes ...
```
**Solution**:
- Verify firmware file is correct
- Use `--list` to check if DTB exists in firmware
- Some firmware may use different structure (not supported yet)

#### Issue: Property value mismatch
```
No change / mismatch for /leds/green:gpios (expected second 0x4)
```
**Solution**:
- Use `--list` to view actual GPIO values
- Update expected values in configuration
- Or remove expected value checks from configuration

#### Issue: Cannot write output file
```
Error: Cannot write to output file
```
**Solution**:
- Check file permissions
- Ensure sufficient disk space
- Don't overwrite input file (script prevents this)

### Technical Details

#### DTB Structure

Device Tree Blob (DTB) is a binary format describing hardware configuration:
- **Magic Number**: `0xD00DFEED` (big-endian)
- **Header**: Contains version, size, offsets
- **Structure Block**: Tree node structure
- **Strings Block**: String table

#### GPIO Property Format

LED `gpios` property typically contains three u32 values:
```
gpios = <phandle gpio-num flags>
```
- **phandle**: GPIO controller reference (first value)
- **gpio-num**: GPIO pin number (second value, target of this tool)
- **flags**: Flag bits (third value, e.g., active high/low)

This tool only modifies the second value (gpio-num), keeping others unchanged.

#### FIT Image

FIT (Flattened Image Tree) is the image format used by U-Boot:
- Contains kernel, DTB, filesystem, and other components
- Each component has corresponding hash values for verification
- Must update hash values after modifying DTB, or U-Boot will reject boot

### Tips

- **Backup original firmware**: Always save original firmware before modification
- **Test first**: Use `--list` to view firmware info without modification
- **Single model test**: When modifying new model, test with `-b` first
- **Check output**: Script outputs detailed modification info, watch for warnings
- **Version control**: Use Git to manage configuration files for easy rollback
- **Community sharing**: Share successful configurations to help other users

### Contributing

Contributions welcome! To add new model configuration:

1. **Fork this repository**
2. **Add or modify configuration**
   - Add new model configuration in `leds.ini`
   - Test to ensure configuration is correct
3. **Submit Pull Request**
   - Describe model name and test results
   - Provide necessary hardware information

### License

This project is licensed under the [Apache License 2.0](LICENSE).

### Disclaimer

- This tool is for educational and research purposes only
- Users assume all risks of using this tool
- Authors are not responsible for device damage or data loss
- Ensure you understand firmware modification risks and recovery methods before use
