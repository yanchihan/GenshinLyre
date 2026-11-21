# GenshinLyre

[**⬇️ 立即下载**](https://github.com/yanchihan/GenshinLyre/releases/latest/download/GenshinLyre-v1.0.zip)　｜　[**☕ 爱发电支持**](https://afdian.com/a/yanchihan)

原神风物之诗琴自动演奏工具。只模拟键盘按键，不读取也不修改游戏内存。

Genshin Impact lyre auto-player written in Python. Keyboard simulation only — no memory reading, no injection.

## 使用

1. 把 `scores` 文件夹放在程序同一目录
2. 进游戏，拿出风物之诗琴，保持游戏窗口在前台
3. 双击 `GenshinLyre.exe`（游戏以管理员身份运行时，程序也要以管理员运行）
4. 选曲 → 点开始 → 3 秒内切回游戏

切出游戏会自动暂停，切回来点「继续」，3 秒后从原位置接着弹。

进度条可以点、可以拖，用来跳到任意位置。速度 0.5x–2.0x 实时可调。

## 曲目

`scores` 里放两种文件：

- `.mid`：MIDI 文件，推荐，音高和节奏按原文件播放
- `.txt`：文字琴谱

「导入琴谱」可以直接选 `.mid`，也可以把网上的字母谱、简谱粘进去。

## 键位

第一排 `Q W E R T Y U` 高音，第二排 `A S D F G H J` 中音，第三排 `Z X C V B N M` 低音。

## 协议

MIT

## 支持

觉得好用点个 Star，或 [请我喝杯奶茶](https://afdian.com/a/yanchihan)。有问题、想加曲子，开个 Issue 就行。
