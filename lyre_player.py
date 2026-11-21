# -*- coding: utf-8 -*-
"""琴谱解析与按键播放"""
import ctypes
import bisect
import re
import threading
import time
import os

NOTE2KEY = {
    # 游戏内三排键位（官方说明）: 第一排 Q-U = 高音, 第二排 A-J = 中音, 第三排 Z-M = 低音
    (6, 'C'): 'Q', (6, 'D'): 'W', (6, 'E'): 'E', (6, 'F'): 'R', (6, 'G'): 'T', (6, 'A'): 'Y', (6, 'B'): 'U',
    (5, 'C'): 'A', (5, 'D'): 'S', (5, 'E'): 'D', (5, 'F'): 'F', (5, 'G'): 'G', (5, 'A'): 'H', (5, 'B'): 'J',
    (4, 'C'): 'Z', (4, 'D'): 'X', (4, 'E'): 'C', (4, 'F'): 'V', (4, 'G'): 'B', (4, 'A'): 'N', (4, 'B'): 'M',
}
KEY2NOTE = {v: k for k, v in NOTE2KEY.items()}


def set_row_order(high_first=True):
    """切换键位顺序：True=第一排(Q-U)为高音（官方说明），False=第一排为低音"""
    global NOTE2KEY, KEY2NOTE
    if high_first:
        NOTE2KEY = {
            (6, "C"): "Q", (6, "D"): "W", (6, "E"): "E", (6, "F"): "R", (6, "G"): "T", (6, "A"): "Y", (6, "B"): "U",
            (5, "C"): "A", (5, "D"): "S", (5, "E"): "D", (5, "F"): "F", (5, "G"): "G", (5, "A"): "H", (5, "B"): "J",
            (4, "C"): "Z", (4, "D"): "X", (4, "E"): "C", (4, "F"): "V", (4, "G"): "B", (4, "A"): "N", (4, "B"): "M",
        }
    else:
        NOTE2KEY = {
            (4, "C"): "Q", (4, "D"): "W", (4, "E"): "E", (4, "F"): "R", (4, "G"): "T", (4, "A"): "Y", (4, "B"): "U",
            (5, "C"): "A", (5, "D"): "S", (5, "E"): "D", (5, "F"): "F", (5, "G"): "G", (5, "A"): "H", (5, "B"): "J",
            (6, "C"): "Z", (6, "D"): "X", (6, "E"): "C", (6, "F"): "V", (6, "G"): "B", (6, "A"): "N", (6, "B"): "M",
        }
    KEY2NOTE = {v: k for k, v in NOTE2KEY.items()}

SCANCODE = {
    'Q': 0x10, 'W': 0x11, 'E': 0x12, 'R': 0x13, 'T': 0x14, 'Y': 0x15, 'U': 0x16,
    'A': 0x1E, 'S': 0x1F, 'D': 0x20, 'F': 0x21, 'G': 0x22, 'H': 0x23, 'J': 0x24,
    'Z': 0x2C, 'X': 0x2D, 'C': 0x2E, 'V': 0x2F, 'B': 0x30, 'N': 0x31, 'M': 0x32,
}

# 常用三和弦（只保留大三/小三度落在自然音阶内的，琴上可弹）
CHORD_TONES = {
    'C':  ('C', 'E', 'G'),
    'Dm': ('D', 'F', 'A'),
    'Em': ('E', 'G', 'B'),
    'F':  ('F', 'A', 'C'),
    'G':  ('G', 'B', 'D'),
    'Am': ('A', 'C', 'E'),
}

NOTE_RE = re.compile(r'^([A-Ga-g])([3-6])?$')
CHORD_RE = re.compile(r'^(C|Dm|Em|F|G|Am)$')

VK_F8 = 0x77
VK_F9 = 0x78


class ScoreError(Exception):
    pass


def is_admin():
    try:
        return ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        return True


def key_pressed(vk):
    return (ctypes.windll.user32.GetAsyncKeyState(vk) & 0x8000) != 0


GAME_PROCESS_NAMES = {"yuanshen.exe", "genshinimpact.exe"}


def get_foreground_title():
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    buf = ctypes.create_unicode_buffer(256)
    ctypes.windll.user32.GetWindowTextW(hwnd, buf, 256)
    return buf.value


def get_foreground_process_name():
    import ctypes.wintypes as wt
    hwnd = ctypes.windll.user32.GetForegroundWindow()
    pid = wt.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)  # QUERY_LIMITED_INFORMATION
    if not h:
        return ""
    try:
        size = wt.DWORD(1024)
        buf = ctypes.create_unicode_buffer(1024)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value).lower()
        return ""
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def is_game_foreground():
    """当前前台窗口是不是原神（进程名优先，其次窗口标题）"""
    name = get_foreground_process_name()
    if name:
        return name in GAME_PROCESS_NAMES
    title = get_foreground_title().lower()
    return ("原神" in title) or ("genshin" in title)


ULONG_PTR = ctypes.c_size_t
LONG = ctypes.c_long
DWORD = ctypes.c_uint32
WORD = ctypes.c_uint16


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", LONG), ("dy", LONG), ("mouseData", DWORD),
                ("dwFlags", DWORD), ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", WORD), ("wScan", WORD), ("dwFlags", DWORD),
                ("time", DWORD), ("dwExtraInfo", ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", DWORD), ("wParamL", WORD), ("wParamH", WORD)]


class INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", DWORD), ("u", INPUTUNION)]


def send_key(key, down):
    """向当前前台窗口发送扫描码按键。key 必须是 SCANCODE 中的大写字母。"""
    if key not in SCANCODE:
        return
    inp = INPUT()
    inp.type = 1  # INPUT_KEYBOARD
    inp.u.ki.wScan = SCANCODE[key]
    inp.u.ki.dwFlags = 0x0008  # KEYEVENTF_SCANCODE
    if not down:
        inp.u.ki.dwFlags |= 0x0002  # KEYEVENTF_KEYUP
    ctypes.windll.user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def _parse_chords(tokens):
    chords = []
    if len(tokens) % 2 != 0:
        raise ScoreError("和弦行必须成对出现(和弦 拍数): " + " ".join(tokens))
    for i in range(0, len(tokens), 2):
        name = tokens[i]
        if not CHORD_RE.match(name):
            raise ScoreError("不支持的和弦: " + name + " (支持 C Dm Em F G Am)")
        chords.append((name, float(tokens[i + 1])))
    return chords


KEY_LETTERS = "QWERTYUASDFGHJZXCVBNM"


def _scan_group(inner, lineno):
    """解析括号内的和弦，如 "Q/ Z/" -> [('Q',1),('Z',1)]"""
    out = []
    i = 0
    while i < len(inner):
        c = inner[i]
        if c.upper() in KEY_LETTERS:
            key = c.upper()
            j = i + 1
            sl = 0
            while j < len(inner) and inner[j] == '/':
                sl += 1
                j += 1
            out.append((key, sl if sl else 1))
            i = j
        else:
            i += 1
    return out


def _parse_key_steps(line, lineno):
    """解析键谱行，返回 [(keys列表或None, 拍数)]。
    兼容三种写法:
      Q 1 W 1           本文档格式（键 + 拍数）
      Q/ W/ (E/ G/) 停/  社区格式（斜杠数=拍数，括号=和弦快速琶音，停=休止）
      TTE(WF)EH         社区紧凑格式（连写字母各占 1 拍）
    """
    toks = line.split()
    if toks and len(toks) % 2 == 0 and all(re.fullmatch(r'[A-Za-z]|\d+(?:\.\d+)?', t) for t in toks) \
            and any(t[0].isdigit() for t in toks[1::2]):
        steps = []
        for i in range(0, len(toks), 2):
            key = toks[i].upper()
            if key not in SCANCODE:
                raise ScoreError("第%d行无效按键: %s" % (lineno, toks[i]))
            try:
                beats = float(toks[i + 1])
            except ValueError:
                raise ScoreError("第%d行拍数不是数字: %s" % (lineno, toks[i + 1]))
            steps.append(([key], beats))
        return steps

    steps = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == '(':
            j = line.find(')', i)
            if j < 0:
                raise ScoreError("第%d行括号未闭合" % lineno)
            group = _scan_group(line[i + 1:j], lineno)
            if group:
                dur = max(g[1] for g in group)
                steps.append(([g[0] for g in group], dur))
            i = j + 1
        elif c == '停':
            j = i + 1
            sl = 0
            while j < n and line[j] == '/':
                sl += 1
                j += 1
            steps.append((None, sl if sl else 1))
            i = j
        elif c.upper() in KEY_LETTERS:
            key = c.upper()
            j = i + 1
            sl = 0
            while j < n and line[j] == '/':
                sl += 1
                j += 1
            steps.append(([key], sl if sl else 1))
            i = j
        else:
            i += 1
    return steps


NOTE_ORDER = {'C': 0, 'D': 1, 'E': 2, 'F': 3, 'G': 4, 'A': 5, 'B': 6}
DEGREE_NOTE = {'1': 'C', '2': 'D', '3': 'E', '4': 'F', '5': 'G', '6': 'A', '7': 'B'}
JIANPU_BASE_OCTAVE = 5


def _scan_jianpu_items(inner):
    """解析一段简谱（可能含 +/- 八度记号与斜杠），返回 [(符号, 数字, 拍数)]"""
    items = []
    k = 0
    n = len(inner)
    while k < n:
        c = inner[k]
        if c in '+-' and k + 1 < n and inner[k + 1].isdigit():
            sign, d = c, inner[k + 1]
            k += 2
            sl = 0
            while k < n and inner[k] == '/':
                sl += 1
                k += 1
            items.append((sign, d, sl if sl else 1))
        elif c.isdigit():
            d = c
            k += 1
            sl = 0
            while k < n and inner[k] == '/':
                sl += 1
                k += 1
            items.append(('', d, sl if sl else 1))
        else:
            k += 1
    return items


def _parse_jianpu_steps(line, lineno):
    """解析简谱行，返回 [(keys或None, 拍数)]，keys 元素为 (八度, 音名)。"""
    steps = []
    i, n = 0, len(line)
    while i < n:
        c = line[i]
        if c == '(':
            j = line.find(')', i)
            if j < 0:
                raise ScoreError("第%d行括号未闭合" % lineno)
            items = _scan_jianpu_items(line[i + 1:j])
            if items:
                dur = max(it[2] for it in items)
                keys = []
                for sign, d, _ in items:
                    if d == '0':
                        continue
                    octave = JIANPU_BASE_OCTAVE + (1 if sign == '+' else -1 if sign == '-' else 0)
                    keys.append((octave, DEGREE_NOTE[d]))
                if keys:
                    steps.append((keys, dur))
                else:
                    steps.append((None, dur))
            i = j + 1
        elif c in '+-' and i + 1 < n and line[i + 1].isdigit():
            sign, d = c, line[i + 1]
            i += 2
            sl = 0
            while i < n and line[i] == '/':
                sl += 1
                i += 1
            beats = sl if sl else 1
            octave = JIANPU_BASE_OCTAVE + (1 if sign == '+' else -1)
            steps.append(([(octave, DEGREE_NOTE[d])], beats))
        elif c.isdigit():
            d = c
            i += 1
            sl = 0
            while i < n and line[i] == '/':
                sl += 1
                i += 1
            beats = sl if sl else 1
            if d == '0':
                steps.append((None, beats))
            else:
                steps.append(([(JIANPU_BASE_OCTAVE, DEGREE_NOTE[d])], beats))
        else:
            i += 1
    return steps


def parse_score(text, melody_only=False):
    """解析琴谱文本。
    返回 (meta, melody, chords)
    melody: [(拍时间, kind, 数据, 时值拍)]  kind='note' 数据=(八度,音名)  kind='key' 数据=键字母
    """
    meta = {"title": "未命名", "bpm": 100.0, "unit": 1.0}
    melody = []
    chords = []
    mode = "notes"
    t = 0.0
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", ";", "//")):
            continue
        if line.startswith("@"):
            parts = line[1:].split()
            tag = parts[0].lower()
            try:
                if tag == "title":
                    meta["title"] = " ".join(parts[1:])
                elif tag == "bpm" and len(parts) > 1:
                    meta["bpm"] = float(parts[1])
                elif tag == "unit" and len(parts) > 1:
                    meta["unit"] = float(parts[1])
                elif tag == "notes":
                    mode = "notes"
                elif tag == "keys":
                    mode = "keys"
                elif tag == "jianpu":
                    mode = "jianpu"
                elif tag == "chord":
                    chords.extend(_parse_chords(parts[1:]))
                else:
                    raise ScoreError("未知指令: @" + tag)
            except ValueError:
                raise ScoreError("第%d行指令格式错误: %s" % (lineno, line))
            continue
        if mode == "notes":
            toks = line.split()
            if len(toks) % 2 != 0:
                raise ScoreError("第%d行必须成对出现(音名 + 拍数): %s" % (lineno, line))
            for i in range(0, len(toks), 2):
                item = toks[i]
                try:
                    beats = float(toks[i + 1])
                except ValueError:
                    raise ScoreError("第%d行拍数不是数字: %s" % (lineno, toks[i + 1]))
                m = NOTE_RE.match(item)
                if not m:
                    raise ScoreError("第%d行无效音符: %s (例: C, G4, A5)" % (lineno, item))
                octave = int(m.group(2)) if m.group(2) else 4
                melody.append((t, "note", (octave, m.group(1).upper()), beats))
                t += beats
        elif mode == "jianpu":
            unit = meta.get("unit", 1.0)
            for keys, beats in _parse_jianpu_steps(line, lineno):
                if keys and melody_only and len(keys) > 1:
                    keys = [max(keys, key=lambda k: (k[0], NOTE_ORDER.get(k[1], 0)))]
                if keys:
                    for idx, (octave, name) in enumerate(keys):
                        off = 0.04 * idx if len(keys) > 1 else 0.0
                        melody.append((t + off, "note", (octave, name), beats * unit))
                t += beats * unit
        else:
            unit = meta.get("unit", 1.0)
            for keys, beats in _parse_key_steps(line, lineno):
                if keys and melody_only and len(keys) > 1:
                    keys = keys[:1]
                if keys:
                    for idx, k in enumerate(keys):
                        off = 0.04 * idx if len(keys) > 1 else 0.0
                        melody.append((t + off, "key", k, beats * unit))
                t += beats * unit
    return meta, melody, chords


def transpose_notes(melody):
    """自动移调：让音符尽量落在 C4-B6 内，返回移调后的旋律和移调半音数(按八度)。"""
    octaves = [d[0] for _, kind, d, _ in melody if kind == "note"]
    if not octaves:
        return melody, 0
    lo, hi = min(octaves), max(octaves)
    shift = 0
    if lo < 4 and hi + 1 <= 6:
        shift = 1
    elif hi > 6 and lo - 1 >= 4:
        shift = -1
    while shift != 0:
        # 验证移位后仍在范围内
        if lo + shift < 4 or hi + shift > 6:
            break
        out = []
        for t, kind, d, dur in melody:
            if kind == "note":
                d = (d[0] + shift, d[1])
            out.append((t, kind, d, dur))
        return out, shift
    return melody, 0


def build_events(melody, chords, bpm, accompany=False, dry_run=False):
    """生成按键事件序列 [(秒, 键, 下/上, 显示名)]，并统计丢弃的音符。"""
    bt = 60.0 / bpm
    events = []
    dropped = 0
    total_beats = melody[-1][0] + melody[-1][3] if melody else 0.0

    def add(t_beat, key, dur_beat, display):
        events.append([t_beat * bt, key, dur_beat * bt, "down", display])
        hold = min(dur_beat * 0.85, 0.45)
        events.append([t_beat * bt + hold * bt, key, 0.0, "up", display])

    for t_beat, kind, data, dur in melody:
        if kind == "key":
            add(t_beat, data, dur, data)
        else:
            key = NOTE2KEY.get(data)
            if key is None:
                dropped += 1
                continue
            display = "%s%d" % (data[1], data[0])
            add(t_beat, key, dur, display)

    if accompany and chords:
        melody_down_times = [e[0] for e in events if e[3] == "down"]
        ctime = 0.0
        ci = 0
        while ctime < total_beats - 0.001 and melody:
            name, cbeats = chords[ci % len(chords)]
            tones = CHORD_TONES.get(name)
            if tones:
                root, fifth = tones[0], tones[1]
                root_key = NOTE2KEY.get((4, root))
                fifth_key = NOTE2KEY.get((4, fifth))
                # 根音在强拍，五音在半小节
                for pos, key in ((ctime, root_key), (ctime + cbeats / 2.0, fifth_key)):
                    if key is None:
                        continue
                    tt = pos * bt
                    # 与旋律音撞车就跳过
                    idx = bisect.bisect_left(melody_down_times, tt)
                    clash = False
                    for mtime in (melody_down_times[idx - 1] if idx > 0 else None,
                                  melody_down_times[idx] if idx < len(melody_down_times) else None):
                        if mtime is not None and abs(mtime - tt) < 0.09:
                            clash = True
                    if clash:
                        continue
                    events.append([tt, key, 0.35, "down", name])
                    events.append([tt + 0.3, key, 0.0, "up", name])
            ctime += cbeats
            ci += 1

    # 按时间排序，并保证相邻事件至少 20ms 间隔
    events.sort(key=lambda e: (e[0], 0 if e[3] == "down" else 1))
    out = []
    for e in events:
        if out and e[0] < out[-1][0] + 0.02:
            e[0] = out[-1][0] + 0.02
        out.append(e)
    return out, dropped


# ---- MIDI 支持 ----
MIDI_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NATURAL_SEMI = [0, 2, 4, 5, 7, 9, 11]


def _read_varlen(data, pos):
    val = 0
    while True:
        b = data[pos]
        pos += 1
        val = (val << 7) | (b & 0x7F)
        if not (b & 0x80):
            return val, pos


def parse_midi(path):
    """解析标准 MIDI，返回 [(起始秒, 时值秒, midi音高)]"""
    data = open(path, "rb").read()
    if data[:4] != b"MThd":
        raise ScoreError("不是 MIDI 文件")
    hlen = int.from_bytes(data[4:8], "big")
    division = int.from_bytes(data[12:14], "big")
    pos = 8 + hlen
    tracks = []
    while pos + 8 <= len(data) and data[pos:pos + 4] == b"MTrk":
        tlen = int.from_bytes(data[pos + 4:pos + 8], "big")
        tracks.append(data[pos + 8:pos + 8 + tlen])
        pos += 8 + tlen

    tempo = 500000
    events = []  # (tick, order, kind, a, b)
    for ti, tr in enumerate(tracks):
        p = 0
        tick = 0
        running = None
        while p < len(tr):
            delta, p = _read_varlen(tr, p)
            tick += delta
            if p >= len(tr):
                break
            status = tr[p]
            if status & 0x80:
                p += 1
                if status < 0xF0:
                    running = status
            else:
                status = running
                if status is None:
                    break
            if status == 0xFF:
                mtype = tr[p]; p += 1
                mlen, p = _read_varlen(tr, p)
                payload = tr[p:p + mlen]; p += mlen
                if mtype == 0x51 and mlen == 3:
                    events.append((tick, ti, "tempo", int.from_bytes(payload, "big"), 0))
                elif mtype == 0x2F:
                    break
            elif status in (0xF0, 0xF7):
                mlen, p = _read_varlen(tr, p); p += mlen
            else:
                hi = status & 0xF0
                if hi in (0xC0, 0xD0):
                    p += 1
                else:
                    a = tr[p]; b = tr[p + 1]; p += 2
                    if hi == 0x90 and b > 0:
                        events.append((tick, ti, "on", a, b))
                    elif hi == 0x80 or (hi == 0x90 and b == 0):
                        events.append((tick, ti, "off", a, 0))

    # 时间轴（秒）
    events.sort(key=lambda e: (e[0], 0 if e[2] == "tempo" else 1))
    secs_per_tick = (tempo / 1e6) / division
    last_tick = 0
    cur_sec = 0.0
    for ev in events:
        if ev[2] == "tempo":
            pass
    # 逐事件推进（tempo 变更按段累加）
    sec_at_tick = []
    cur_sec = 0.0
    last_tick = 0
    tempos = [e for e in events if e[2] == "tempo"]
    ti = 0
    tmap = []
    for ev in events:
        while ti < len(tempos) and tempos[ti][0] <= ev[0]:
            tmap.append((tempos[ti][0], tempos[ti][3]))
            ti += 1
    tmap.sort()

    def tick_to_sec(t):
        sec = 0.0
        prev_t = 0
        cur_tempo = 500000
        for tt, tp in tmap:
            if tt >= t:
                break
            sec += (tt - prev_t) * (cur_tempo / 1e6) / division
            prev_t = tt
            cur_tempo = tp
        sec += (t - prev_t) * (cur_tempo / 1e6) / division
        return sec

    active = {}
    notes = []
    for ev in events:
        tick, track, kind, a, b = ev
        if kind == "on":
            active.setdefault((track, a), []).append(tick)
        elif kind == "off":
            st = active.get((track, a))
            if st:
                start = st.pop(0)
                notes.append((tick_to_sec(start), max(0.03, tick_to_sec(tick) - tick_to_sec(start)), a))
    return notes


def midi_to_events(notes, melody_only=False):
    """MIDI 音符 -> 按键事件。自动选取最佳移调，尽量多保留自然音；melody_only 时只留最高声部"""
    if not notes:
        return [], 0
    best = None
    for shift in range(-24, 25):
        kept = 0
        for start, dur, pitch in notes:
            p = pitch + shift
            if p < 48 or p > 95:
                continue
            if p % 12 in NATURAL_SEMI:
                kept += 2
            elif any(48 <= p + d <= 95 and (p + d) % 12 in NATURAL_SEMI for d in (1, -1)):
                kept += 1
        if best is None or kept > best[0]:
            best = (kept, shift)
    shift = best[1]

    conv = []
    dropped = 0
    for start, dur, pitch in notes:
        q = pitch + shift
        if q < 48 or q > 95:
            dropped += 1
            continue
        if q % 12 not in NATURAL_SEMI:
            snapped = None
            for d in (1, -1, 2, -2):
                if 48 <= q + d <= 95 and (q + d) % 12 in NATURAL_SEMI:
                    snapped = q + d
                    break
            if snapped is None:
                dropped += 1
                continue
            q = snapped
        conv.append([start, dur, q])

    if melody_only and conv:
        conv.sort(key=lambda x: (round(x[0], 3), -x[2]))
        picked = []
        for item in conv:
            if picked and abs(item[0] - picked[-1][0]) < 0.04:
                if item[2] > picked[-1][2]:
                    picked[-1] = item
                continue
            picked.append(item)
        conv = picked

    out = []
    for start, dur, q in conv:
        octave = q // 12 - 1
        name = MIDI_NAMES[q % 12]
        key = NOTE2KEY.get((octave, name))
        if key is None:
            dropped += 1
            continue
        out.append((start, key, dur))
    out.sort()
    return out, dropped


def _strip_accompaniment(melody):
    octs = [d[0] for _, kind, d, _ in melody if kind == 'note']
    if not octs:
        return melody
    keep_from = max(octs) - 1
    return [it for it in melody if it[1] != 'note' or it[2][0] >= keep_from]


class Player:
    def __init__(self, dry_run=False):
        self.lock = threading.Lock()
        self.dry_run = dry_run
        self.melody_only = False
        self.octave_shift = 0
        self.foreground_guard = False
        self.meta = {}
        self.stats = {}
        self.events = []
        self.playing = False
        self.paused = False
        self.running = False
        self.speed = 1.0
        self.current = ""
        self.progress = 0.0
        self._thread = None
        self._pending_seek = None

    # ---- 加载 ----
    def load(self, path):
        if path.lower().endswith((".mid", ".midi")):
            return self._load_midi(path)
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            return "无法读取琴谱: %s" % e
        try:
            meta, melody, chords = parse_score(text, self.melody_only)
            if not melody:
                return "琴谱里没有音符"
            if self.melody_only:
                melody = _strip_accompaniment(melody)
            melody, shift = transpose_notes(melody)
            if self.octave_shift:
                melody = [(tt, kind, (d[0] + self.octave_shift, d[1]) if kind == "note" else d, dur)
                          for tt, kind, d, dur in melody]
            events, dropped = build_events(melody, chords, meta["bpm"], self.accompany(), self.dry_run)
        except ScoreError as e:
            return "琴谱错误: %s" % e
        with self.lock:
            self.meta = meta
            self.events = events
            self.stats = {
                "notes": sum(1 for e in events if e[3] == "down"),
                "dropped": dropped,
                "shift": shift,
                "total_s": events[-1][0] if events else 0,
            }
            self.current = ""
            self.progress = 0.0
        return None


    def _load_midi(self, path):
        try:
            notes = parse_midi(path)
            keyed, dropped = midi_to_events(notes, self.melody_only)
        except ScoreError as e:
            return str(e)
        except Exception as e:
            return "MIDI 解析失败: %s" % e
        if not keyed:
            return "MIDI 里没有可用音符"
        evs = []
        for start, key, dur in keyed:
            evs.append([start, key, dur, "down", key])
            evs.append([start + min(dur * 0.9, 0.5), key, 0.0, "up", key])
        evs.sort(key=lambda e: (e[0], 0 if e[3] == "down" else 1))
        out = []
        for e in evs:
            if out and e[0] < out[-1][0] + 0.02:
                e[0] = out[-1][0] + 0.02
            out.append(e)
        with self.lock:
            self.meta = {"title": os.path.splitext(os.path.basename(path))[0], "bpm": "-"}
            self.events = out
            self.stats = {"notes": sum(1 for e in out if e[3] == "down"),
                          "dropped": dropped, "shift": 0,
                          "total_s": out[-1][0] if out else 0}
            self.current = ""
            self.progress = 0.0
        return None

    def accompany(self):
        return False  # 由 GUI/外部覆写

    # ---- 控制 ----
    def play(self):
        with self.lock:
            if not self.events or self.playing:
                return
            self.playing = True
            self.paused = False
            self.running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def pause(self):
        with self.lock:
            if self.playing and not self.paused:
                self.paused = True

    def resume(self):
        with self.lock:
            self.paused = False

    def stop(self):
        with self.lock:
            self.running = False
            self.playing = False
            self.paused = False
            self.current = ""
            self.progress = 0.0

    def seek(self, ratio):
        with self.lock:
            if not self.events:
                return
            total = self.events[-1][0] or 1.0
            target = max(0.0, min(total - 0.001, float(ratio) * total))
            times = [e[0] for e in self.events]
            self._pending_seek = (bisect.bisect_left(times, target), target)
            self.progress = target / total

    def set_speed(self, v):
        with self.lock:
            self.speed = max(0.2, min(4.0, float(v)))

    def _send(self, e):
        if self.dry_run:
            return
        if self.foreground_guard and not is_game_foreground():
            return
        send_key(e[1], e[3] == "down")

    def _run(self):
        events = self.events
        i = 0
        base = 0.0
        last = time.monotonic()
        total = events[-1][0] if events else 1.0
        while i < len(events):
            with self.lock:
                if not self.running:
                    break
                paused = self.paused
                speed = self.speed
            now = time.monotonic()
            base += (now - last) * speed if not paused else 0.0
            last = now
            if paused:
                time.sleep(0.02)
                continue
            if self._pending_seek is not None:
                i, base = self._pending_seek
                self._pending_seek = None
                if i >= len(events):
                    break
            e = events[i]
            wait = (e[0] - base) / speed
            if wait > 0.02:
                time.sleep(min(wait, 0.1))
                continue
            if wait > -0.06:
                self._send(e)
                if e[3] == "down":
                    with self.lock:
                        self.current = e[4]
                        self.progress = e[0] / total
            i += 1
        with self.lock:
            self.running = False
            self.playing = False
            self.current = ""
            self.progress = 1.0


if __name__ == "__main__":
    # 测试模式: python lyre_player.py [琴谱文件]
    import sys
    if len(sys.argv) < 2:
        print("用法: python lyre_player.py <琴谱文件>")
        sys.exit(1)
    p = Player(dry_run=True)
    err = p.load(sys.argv[1])
    if err:
        print("错误:", err)
        sys.exit(1)
    print("标题:", p.meta["title"], " BPM:", p.meta["bpm"])
    print("事件数:", len(p.events), " 按键次数:", p.stats["notes"],
          " 丢弃音符:", p.stats["dropped"], " 移调八度:", p.stats["shift"])
    print("总时长: %.1f 秒" % p.stats["total_s"])
    for e in p.events[:12]:
        print("  %.2fs  %s  %s(%s)" % (e[0], e[1], e[3], e[4]))
