# subreel

**把语音音频变成可直接用于视频合成的字幕素材：绿幕 H.264、透明
WebM / ProRes，逐词卡拉OK高亮。**

[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://www.python.org/)
[![No runtime deps](https://img.shields.io/badge/runtime%20deps-none-success.svg)](#安装)

subreel 是一个轻量、零运行依赖的命令行工具，把一段配音变成一个可以直接
拖到时间线上的字幕素材。它把字幕渲染到色度抠图用的绿幕背景上（适合能抠
绿幕的剪辑软件），或渲染到透明画布上（适合直接吃 alpha 的软件），并按
说话进度逐词点亮——经典的卡拉OK效果。

时间轴有两种来源：

1. **`subreel tts` —— 最准的方式。** 用
   [edge-tts](https://github.com/rany2/edge-tts) 合成语音，同时从合成事件
   里直接抓取逐词时间戳。时间轴和音频出自同一个引擎，因此**没有任何语音
   识别的误差**。
2. **`subreel render --asr` —— 通用方式。** 对任意已有音频用
   [faster-whisper](https://github.com/SYSTRAN/faster-whisper) 做词级时间戳
   识别。

---

## 特性

- **一次命令，三种输出：**
  - **绿幕 MP4** —— H.264 / `yuv420p`，剪映、PR、达芬奇、FCP 抠绿幕即用。
  - **透明 WebM** —— 带 alpha 通道（`yuva420p`）的 VP9。
  - **透明 ProRes 4444 MOV** —— 带 alpha（`yuva444p10le`），供 PR / FCP / 达芬奇使用。
- **逐词卡拉OK高亮** —— 每个词用 ASS `\kf` 包裹，当前词与已唱词显示为高亮色。
- **edge-tts 精准时间轴** —— 直接取自 `WordBoundary` 事件，不经过语音识别。
- **Whisper ASR 兜底** —— 对非合成音频做词级识别，并带缓存。
- **零必装 Python 依赖** —— 系统只需 ffmpeg；`edge-tts`、`faster-whisper`
  都是可选 extras。
- **公开、可移植的时间轴格式** —— [`words.json`](#wordsjson-时间轴格式)。

<!-- 演示：录好后取消注释并放入文件。
<p align="center">
  <img src="docs/demo-green.gif"   alt="绿幕卡拉OK字幕" width="640">
  <img src="docs/demo-alpha.gif"   alt="透明卡拉OK字幕" width="640">
</p>
-->

---

## 安装

### 1. ffmpeg（必需）

subreel 会调用 `ffmpeg` / `ffprobe`，并在启动时探测是否可用。

| 平台            | 命令                                       |
| --------------- | ------------------------------------------ |
| Ubuntu / Debian | `sudo apt install ffmpeg`                  |
| macOS           | `brew install ffmpeg`                      |
| Windows         | `winget install Gyan.FFmpeg`               |
| Conda           | `conda install -c conda-forge ffmpeg`      |

渲染中文字幕还需安装中文字体（Debian / Ubuntu 上如 `fonts-noto-cjk`）；
默认样式使用 `Noto Sans CJK SC`。

### 2. subreel

暂未发布到 PyPI，直接从 GitHub 安装：

```bash
pip install "git+https://github.com/paxoscn/subreel.git"
```

安装可选功能：

```bash
# edge-tts 合成（subreel tts）
pip install "git+https://github.com/paxoscn/subreel.git#egg=subreel[tts]"

# faster-whisper ASR（subreel render --asr）
pip install "git+https://github.com/paxoscn/subreel.git#egg=subreel[asr]"

# 两个都要
pip install "git+https://github.com/paxoscn/subreel.git#egg=subreel[tts,asr]"
```

---

## 快速开始

### A. 合成并渲染（最准）

```bash
# 1. 生成配音，并同时得到精确的逐词时间轴
subreel tts \
  --text script.txt \
  --voice zh-CN-XiaoxiaoNeural \
  --rate +15% \
  --out voice.mp3
# -> voice.mp3  以及  voice.words.json

# 2. 渲染三种输出
subreel render voice.mp3 \
  --timings voice.words.json \
  --formats green,webm,mov \
  --out-dir out
# -> out/subs-green.mp4, out/subs-alpha.webm, out/subs-alpha.mov
```

### B. 已有音频 —— 交给 Whisper 识别

```bash
subreel render narration.m4a --asr --asr-model small --formats green,webm
```

识别结果会缓存到 `out/narration.words.json`，下次直接复用（加 `--force-asr`
可强制重跑）。

### C. 已有时间轴

任何能产出 [`words.json`](#wordsjson-时间轴格式) 格式的工具都能驱动 subreel：

```bash
subreel render voice.mp3 --timings my-alignment.json --formats mov
```

### 命令行解码透明 WebM 的注意事项

`subs-alpha.webm` 的 alpha 通道以 VP9 *BlockAdditional* 层（`alpha_mode=1`）
存放。剪辑软件和浏览器原生支持，但 ffmpeg 的**原生** `vp9` 解码器会静默丢弃
该层——直接 `ffmpeg -i subs-alpha.webm frame.png` 抽出来是全不透明的黑帧。
请用 libvpx 解码：

```bash
ffmpeg -c:v libvpx-vp9 -i subs-alpha.webm -frames:v 1 frame.png   # RGBA，alpha 完整
```

ProRes `.mov` 无此问题，任何 ffmpeg/ProRes 工具链都能直接读出 alpha。

---

## 合成指南

三种输出都是字幕**叠加层**：只包含文字（和音频），把它放到素材上层，把背景
抠掉即可。

### 剪映（CapCut / 剪映专业版）

1. 导入 `subs-green.mp4`，放到视频上方的轨道。
2. 选中片段 → **画面** → **抠像** → **色度抠图**。
3. 用吸管在绿色背景上取色——绿幕颜色是 `0x00B140`（RGB `0, 177, 64`）。
4. 提高**强度**直到绿色完全消失，再用**阴影**清理字形边缘的抗锯齿残留。

### Adobe Premiere Pro

- **绿幕 MP4**：加 **Ultra Key**，吸管取绿色，*Matte Generation* 里
  *Tolerance* 约 30–40%，*Pedestal* 约 10%。
- **透明 WebM / MOV**：直接把 `subs-alpha.webm`（带 alpha 的 VP9）或
  `subs-alpha.mov`（ProRes 4444）拖到时间线，无需抠像。

### 达芬奇 DaVinci Resolve

- **绿幕 MP4**：加 **3D Keyer** 节点，吸管取绿色，再用 *Clean Black* /
  *Clean White* 微调。
- **透明 MOV**：导入 `subs-alpha.mov` 并放到更高轨道，Resolve 直接识别
  ProRes 4444 的 alpha。

### Final Cut Pro

- **绿幕 MP4**：加 **Keyer** 滤镜并取绿色。
- **透明 MOV**：把 `subs-alpha.mov` 放到素材上方，自动使用 alpha。

### 通用

透明 WebM（VP9 `yuva420p`）和透明 MOV（ProRes 4444）在 PR、达芬奇、FCP 里
都可以直接拖到时间线，无需抠像。如果编辑器不认 VP9 的 alpha，改用 MOV 即可。

---

## `words.json` 时间轴格式

subreel 的公开交换格式。时间单位为**秒**（`float`）。

```json
{
  "language": "zh",
  "source": "edge-tts",
  "words": [
    { "text": "你", "start": 0.12, "end": 0.31 },
    { "text": "好", "start": 0.31, "end": 0.58 }
  ]
}
```

| 字段       | 类型   | 必填 | 说明                                                     |
| ---------- | ------ | ---- | -------------------------------------------------------- |
| `words`    | array  | 是   | 非空的词对象列表。                                       |
| `words[].text`  | string | 是 | 词/字的显示文本。                                    |
| `words[].start` | number | 是 | 起始时间（秒）。                                     |
| `words[].end`   | number | 是 | 结束时间（秒）；必须严格大于 `start`。                |
| `language` | string | 否   | 尽力而为的语言标签（如 `zh`、`en`）。                    |
| `source`   | string | 否   | 来源说明（`edge-tts`、`faster-whisper` …）。             |

加载时强制校验（不合法会给出清晰报错）：

- `words` 必须存在且非空；
- 每个词要有 `text`（字符串）和数值型 `start` / `end`；
- 每个词满足 `start < end`；
- `start` 单调不减（允许相等，即两词可共享边界）。

---

## 命令行参考

```
subreel [-h] [--version] [-v] [-q] {tts,render} ...
```

公共项：`--version`、`-v/--verbose`（INFO 日志）、`-q/--quiet`。

### `subreel tts`

```
subreel tts (--text FILE | --text-inline STR) [--voice VOICE]
            [--rate RATE] [--pitch PITCH] --out AUDIO [--timings JSON]
```

| 选项                | 默认值                   | 说明                             |
| ------------------- | ------------------------ | -------------------------------- |
| `--text FILE`       | —                        | 从 UTF-8 文件读取脚本。          |
| `--text-inline STR` | —                        | 直接使用给定文本。               |
| `--voice`           | `zh-CN-XiaoxiaoNeural`   | edge-tts 音色名。                |
| `--rate`            | `+0%`                    | 语速，如 `+30%`。                |
| `--pitch`           | `+0Hz`                   | 音调，如 `+8Hz`。                |
| `--out`             | *(必填)*                 | 输出音频文件。                   |
| `--timings`         | 与 `--out` 同目录        | words.json 输出路径。            |

### `subreel render`

```
subreel render AUDIO [--timings JSON] [--asr] [--asr-model M] [--language L]
               [--force-asr] [--formats F] [--out-dir DIR] [--size WxH]
               [--fps N] [--green HEX] [--no-audio] [--fontsdir DIR]
               [--font NAME] [--fontsize N] [--align POS] [--highlight HEX]
               [--color HEX] [--no-fade] [--max-chars N] [--max-lines N]
               [--hold SEC]
```

| 选项            | 默认值              | 说明                                                  |
| --------------- | ------------------- | ----------------------------------------------------- |
| `AUDIO`         | *(必填)*            | 源音频文件。                                          |
| `--timings`     | —                   | words.json 逐词时间轴（优先于 `--asr`）。             |
| `--asr`         | 关                  | 用 faster-whisper 生成时间轴。                        |
| `--asr-model`   | `base`              | faster-whisper 模型名/规格。                          |
| `--language`    | 自动                | 强制 ASR 语言（如 `zh`、`en`）。                      |
| `--force-asr`   | 关                  | 即使已有缓存也重新识别。                              |
| `--formats`     | `green`             | `green`、`webm`、`mov` 的逗号分隔子集。              |
| `--out-dir`     | `./out`             | 输出目录（不存在会自动创建）。                        |
| `--size`        | `1280x720`          | 画布尺寸。                                            |
| `--fps`         | `30`                | 帧率。                                                |
| `--green`       | `0x00B140`          | `green` 格式的抠像绿色。                              |
| `--no-audio`    | 关                  | 输出不带音轨。                                        |
| `--fontsdir`    | —                   | libass 额外的字体目录。                               |
| `--font`        | `Noto Sans CJK SC`  | 字幕字体名。                                          |
| `--fontsize`    | `64`                | 字幕字号。                                            |
| `--align`       | `bottom`            | `bottom`、`center`/`middle` 或 `top`。                |
| `--highlight`   | `#FFE500`           | 高亮色（已唱词），`#RRGGBB`。                        |
| `--color`       | `#FFFFFF`           | 基础色（未唱词）。                                    |
| `--no-fade`     | 关                  | 关闭每行淡入淡出。                                    |
| `--max-chars`   | `22`                | 每行宽度预算（按 CJK 字宽计）。                       |
| `--max-lines`   | `2`                 | 单句的最大行数（软上限）。                            |
| `--hold`        | `0.3`               | 卡拉OK停留时间（秒）。                                |

**退出码：** 成功为 `0`；所有可恢复错误均为 `2`（缺 ffmpeg、音频不存在、
没有时间轴来源、words.json 非法、ffmpeg 执行失败）。

---

## 开发

```bash
git clone https://github.com/paxoscn/subreel.git
cd subreel
pip install -e ".[dev,tts,asr]"

# 运行离线测试（不联网、不下载模型）
python3 -m pytest tests/ -q

# 字节码编译检查
python3 -m compileall src/
```

测试里 mock 了 `edge-tts`、`faster-whisper` 和 `ffmpeg`，因此到哪都能跑。

---

## 许可证

[Apache-2.0](LICENSE) © 2026 paxoscn

---

## 致谢

subreel 建立在以下项目之上：

- [**ffmpeg**](https://ffmpeg.org/) —— 探测、滤镜与编码；
- [**libass**](https://github.com/libass/libass) —— ASS 字幕渲染（经 ffmpeg
  的 `ass` 滤镜）；
- [**edge-tts**](https://github.com/rany2/edge-tts) —— 神经语音合成与逐词
  时间戳；
- [**faster-whisper**](https://github.com/SYSTRAN/faster-whisper) —— 快速
  词级语音识别。