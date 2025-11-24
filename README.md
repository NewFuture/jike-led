# DTB LED Patch Scripts

本目录主要包含用于修改固件中 DTB (Device Tree Blob) 的小工具脚本，修复不同机型的 LED 映射等问题。

## extract_mt7981_leds.py

自动从 [bl-mt798x 仓库](https://github.com/hanwckf/bl-mt798x) 提取 MT7981 芯片各型号的 LED GPIO 配置并更新到 `leds.ini` 文件。

### 功能

- 自动获取 bl-mt798x 仓库中所有 mt7981 设备树文件列表
- 解析每个设备树文件，提取 LED GPIO 信息
- 生成或更新 `leds.ini` 配置文件，包含所有发现的型号

### 使用方法

```bash
# 运行脚本，自动更新 leds.ini
python3 extract_mt7981_leds.py
```

脚本会：
1. 从 GitHub 获取 mt7981 设备树文件列表
2. 逐个解析，提取 LED 配置（颜色和 GPIO 编号）
3. 生成 `leds.ini` 文件，每个型号一个 section

生成的配置格式为 `led_color = gpio_num->gpio_num`，初始设置为恒等映射。如果你需要从其他固件映射到 bl-mt798x 的 GPIO 编号，请手动修改 `->` 前的值。

## fix_led.py

通用 DTB LED / 属性补丁脚本，通过一个 INI 配置文件描述多型号的 `/leds/*:gpios` 映射，并在修改 DTB 后自动更新外层 FIT 镜像中的 hash（crc32 + sha1），确保 U-Boot 校验通过。

### 功能

- 扫描固件镜像中的所有 DTB（magic `0xD00DFEED`）。
- 按 INI 配置中给出的规则修改 `/leds/<name>:gpios` 的第二个 u32（保持 DTB 尺寸不变）。
- 自动重新计算被修改 DTB 的 crc32 / sha1，并在外层 FIT DTB 中更新对应 `hash-*` 节点的 `value` 字段。

### 配置文件：`leds.ini`

脚本默认在当前工作目录查找 `leds.ini`，你也可以用 `--config` 指定其它路径。配置文件使用 INI 格式，每个 section 表示一个机型（board）：

```ini
[komi-a31]
# 可选，指定要修改的 DTB 索引（从 0 开始）；省略时自动按节点匹配
# dtb_index = 1
# 语法：<from>-><to>，支持十进制和 0x 前缀的十六进制
# 会映射到 /leds/green:gpios 的第二个 u32
green = 4->8
# 映射到 /leds/red:gpios 的第二个 u32
red   = 5->34

[fur602]
dtb_index = 1
green = 4->8
red   = 5->13
```

规则说明：

- 每个非 `dtb_index` 的键都会被当作 LED 名，自动映射到 `/leds/<name>` 节点下的 `gpios` 属性。
- 值必须是 `from->to` 形式，例如 `4->8` 或 `0x4->0x8`，修改的是 gpios 属性三个 u32 里的“第二个值”。
- 所有修改都在原地进行，不会改变 DTB 长度，也不会移动其它数据。

### 基本用法

假设当前目录有固件文件 `firmware.bin`，并在同级目录准备好 `leds.ini`：

```bash
# 使用 INI 中默认的第一个机型
python3 fix_led.py firmware.bin

# 明确指定机型（board），等价于脚本的 --board
python3 fix_led.py firmware.bin -b komi-a31

# 或者带上长参数形式
python3 fix_led.py firmware.bin --board komi-a31
```

输出文件名默认是：

- `<board>-<原文件名>`，例如：`komi-a31-firmware.bin`

你也可以用 `-o/--output` 自定义输出路径：

```bash
python3 fix_led.py firmware.bin -b komi-a31 -o firmware-komi-a31-fixed.bin
```

### 使用自定义 INI 路径

如果你的配置文件不叫 `leds.ini`，比如放在 `scripts/led-profiles.ini`，可以这样指定：

```bash
python3 fix_led.py firmware.bin \
  --config scripts/led-profiles.ini \
  -b komi-a31 \
  -o firmware-komi-a31-fixed.bin
```

### 只查看 DTB / LED 节点

想先看看固件里有哪些 DTB、`/leds` 节点，可用 `--list`：

```bash
python3 fix_led.py firmware.bin --list
```

该模式只打印信息，不会修改文件。

### FIT hash 更新开关

正常情况下，脚本会在修改 DTB 后自动更新 FIT 中对应 fdt image 的 crc32 / sha1。如果你只想看修改效果而不想动 hash，可以关闭：

```bash
python3 fix_led.py firmware.bin -b komi-a31 --no-fit-hash -o test.bin
```

> 注意：关闭 hash 更新后，U-Boot 可能因为校验失败而拒绝从该固件启动，只适合做对比和测试用。

### 小提示

- 如果某个 board section 没有写 `dtb_index`，脚本会尝试在所有 DTB 中找到包含对应 `/leds/*` 节点的那一个；如果找不到会给出 warning。
- 映射规则里 `from` 的值和固件中原始 gpios 第二个 u32 不一致时，该 LED 不会被修改，并打印 `No change / mismatch` 提示，方便你确认原始值。
- 当前脚本专注于 LED gpios（三个 u32 的第二个值），如果以后需要支持更多类型的属性，可以再扩展 INI 语法和解析逻辑。
