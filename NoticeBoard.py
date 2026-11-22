# -*- coding: utf-8 -*-
import copy
import datetime
import hashlib
import json
import os
import re
import threading
import time
import uuid as uuid_lib
from typing import Any, Dict, List, Optional, Set, Tuple

from mcdreforged.api.all import *

try:
    from mcdreforged.info_reactor.info_filter import InfoFilter as MCDRInfoFilter
except ImportError:
    MCDRInfoFilter = object

try:
    from mcdreforged.info_reactor.info import InfoActionFlag as MCDRInfoActionFlag
except ImportError:
    MCDRInfoActionFlag = None

PLUGIN_METADATA = {
    'id': 'notice_board',
    'version': '1.0.1',
    'name': 'NoticeBoard',
    'description': 'Vanilla 1.21.11 scoreboard sidebar announcement plugin with rotation, show/hide pages, targeting, colors, placeholders, and LuckPerms support',
    'author': 'MCDR',
    'dependencies': {
        'mcdreforged': '>=2.1.0',
    }
}

# ============================================================================
# Constants & Color Maps
# ============================================================================

COLOR_MAP: Dict[str, str] = {
    '0': 'black',
    '1': 'dark_blue',
    '2': 'dark_green',
    '3': 'dark_aqua',
    '4': 'dark_red',
    '5': 'dark_purple',
    '6': 'gold',
    '7': 'gray',
    '8': 'dark_gray',
    '9': 'blue',
    'a': 'green',
    'b': 'aqua',
    'c': 'red',
    'd': 'light_purple',
    'e': 'yellow',
    'f': 'white',
}

FORMAT_MAP: Dict[str, str] = {
    'k': 'obfuscated',
    'l': 'bold',
    'm': 'strikethrough',
    'n': 'underlined',
    'o': 'italic',
}

# 优先使用 white，确保仅部分玩家显示时名字颜色尽量保持正常白色
TEAM_COLORS: List[str] = [
    'white', 'aqua', 'yellow', 'green', 'gold', 'light_purple',
    'blue', 'red', 'gray', 'dark_aqua', 'dark_green', 'dark_purple',
    'dark_blue', 'dark_red', 'dark_gray', 'black',
]

MAX_SIDEBAR_LINES = 15

DEFAULT_CONFIG: Dict[str, Any] = {
    'enabled': True,
    'suppress_console_output': True,
    'rotation_mode': 'global',  # 'global' 或 'per_player'
    'refresh_interval': 1.0,
    'skip_empty_targets': True,
    'allow_player_self_toggle': True,
    'date_format': '%Y-%m-%d',
    'time_format': '%H:%M:%S',
    'duration_format': 'hms_cn',  # 'hms_cn', 'hm_cn', 'hms', 'clock'
    'weekdays': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'],
    'permission': {
        'mode': 'either',  # 'either' (MCDR或LP任一通过), 'luckperms', 'mcdr'
        'mcdr_level': 3,
        'luckperms_node': 'notice_board.admin',
        'luckperms_timeout': 1.5,
    },
    'team_prefix': '_nb_t_',
    'objective_prefix': 'nb_',
    'pages': [
        {
            'name': 'welcome',
            'enabled': True,
            'type': 'show',
            'duration': 10,
            'targets': 'all',
            'exclude': [],
            'title': '&6&l★ 服务器公告 ★',
            'lines': [
                '&7欢迎你, &b{player}',
                '&8----------------',
                '&e日期: &f{date}',
                '&e时间: &f{time}',
                '&a本次在线: &f{session_time}',
                '&a总计在线: &f{total_time}',
                '&8----------------',
                '&7在线: &e{online} &8| &7页: &f{page}/{total_pages}',
            ],
        },
        {
            'name': 'pause_1',
            'enabled': True,
            'type': 'hide',
            'duration': 5,
            'targets': 'all',
            'exclude': [],
            'title': '',
            'lines': [],
        },
        {
            'name': 'notice',
            'enabled': True,
            'type': 'show',
            'duration': 10,
            'targets': 'all',
            'exclude': [],
            'title': '&#55FFFF&l规则与提示',
            'lines': [
                '&f1. 请遵守服务器规则',
                '&f2. 爱护环境, 友好交流',
                '&63. 输入 &e!!board hide &6可隐藏',
                '&7当前时间: &b{time}',
            ],
        },
    ],
}


# ============================================================================
# Color & SNBT Helpers (Minecraft 1.21.5+ / 1.21.11)
# ============================================================================

def snbt_escape_str(s: str) -> str:
    return (
        '"'
        + s.replace('\\', '\\\\')
        .replace('"', '\\"')
        .replace('\n', '\\n')
        .replace('\r', '\\r')
        .replace('\t', '\\t')
        + '"'
    )


def parse_colored_segments(text: str) -> List[Dict[str, Any]]:
    if not text:
        return []
    segments: List[Dict[str, Any]] = []
    cur_color: Optional[str] = None
    cur_formats: Set[str] = set()
    buf: List[str] = []

    def flush() -> None:
        if buf:
            seg: Dict[str, Any] = {'text': ''.join(buf)}
            if cur_color is not None:
                seg['color'] = cur_color
            for fmt in ('bold', 'italic', 'underlined', 'strikethrough', 'obfuscated'):
                if fmt in cur_formats:
                    seg[fmt] = True
            segments.append(seg)
            buf.clear()

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch in ('&', '§') and i + 1 < n:
            nxt = text[i + 1]
            low = nxt.lower()
            if ch == '&' and nxt == '&':
                buf.append('&')
                i += 2
                continue
            if nxt == '#' and i + 7 < n:
                hex_part = text[i + 2:i + 8]
                if re.fullmatch(r'[0-9a-fA-F]{6}', hex_part):
                    flush()
                    cur_color = '#' + hex_part.upper()
                    cur_formats.clear()
                    i += 8
                    continue
            if low == 'x' and i + 13 < n:
                sub = text[i + 2:i + 14]
                if all(sub[k] in ('&', '§') and sub[k + 1] in '0123456789abcdefABCDEF' for k in range(0, 12, 2)):
                    hex_chars = ''.join(sub[k + 1] for k in range(0, 12, 2))
                    flush()
                    cur_color = '#' + hex_chars.upper()
                    cur_formats.clear()
                    i += 14
                    continue
            if low in COLOR_MAP:
                flush()
                cur_color = COLOR_MAP[low]
                cur_formats.clear()
                i += 2
                continue
            if low in FORMAT_MAP:
                flush()
                cur_formats.add(FORMAT_MAP[low])
                i += 2
                continue
            if low == 'r':
                flush()
                cur_color = None
                cur_formats.clear()
                i += 2
                continue
        buf.append(ch)
        i += 1

    flush()
    return segments


def text_to_snbt(text: str) -> str:
    segments = parse_colored_segments(text)
    if not segments:
        return '{text:""}'

    def seg_to_snbt(seg: Dict[str, Any]) -> str:
        parts = [f'text:{snbt_escape_str(seg["text"])}']
        if 'color' in seg:
            parts.append(f'color:{snbt_escape_str(seg["color"])}')
        for fmt in ('bold', 'italic', 'underlined', 'strikethrough', 'obfuscated'):
            if seg.get(fmt):
                parts.append(f'{fmt}:true')
        return '{' + ','.join(parts) + '}'

    if len(segments) == 1:
        return seg_to_snbt(segments[0])
    return '{text:"",extra:[' + ','.join(seg_to_snbt(s) for s in segments) + ']}'


def legacy_to_rtext(text: str) -> RTextBase:
    segments = parse_colored_segments(text)
    if not segments:
        return RText('')
    rcolor_rgb_cls = globals().get('RColorRGB', None)
    items: List[RTextBase] = []
    for seg in segments:
        color_obj = None
        col = seg.get('color')
        if col:
            if col.startswith('#') and rcolor_rgb_cls is not None:
                try:
                    color_obj = rcolor_rgb_cls.from_code(col)
                except Exception:
                    color_obj = None
            elif not col.startswith('#'):
                color_obj = getattr(RColor, col, None)
        styles = set()
        if seg.get('bold'):
            styles.add(RStyle.bold)
        if seg.get('italic'):
            styles.add(RStyle.italic)
        if seg.get('underlined'):
            styles.add(RStyle.underlined)
        if seg.get('strikethrough'):
            styles.add(RStyle.strikethrough)
        if seg.get('obfuscated'):
            styles.add(RStyle.obfuscated)
        items.append(RText(seg['text'], color=color_obj, styles=styles if styles else None))
    return items[0] if len(items) == 1 else RTextList(*items)


def format_duration(seconds: int, fmt: str = 'hms_cn') -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if fmt == 'clock':
        return f'{h:02d}:{m:02d}:{s:02d}'
    if fmt == 'hms':
        if h > 0:
            return f'{h}h {m}m {s}s'
        if m > 0:
            return f'{m}m {s}s'
        return f'{s}s'
    if fmt == 'hm_cn':
        if h > 0:
            return f'{h}小时{m}分'
        if m > 0:
            return f'{m}分钟'
        return '<1分钟'
    if h > 0:
        return f'{h}小时{m}分{s}秒'
    if m > 0:
        return f'{m}分{s}秒'
    return f'{s}秒'


def sanitize_prefix(prefix: str, fallback: str) -> str:
    cleaned = re.sub(r'[^a-zA-Z0-9_.+-]', '', prefix or '')
    return cleaned or fallback


# ============================================================================
# Plugin State
# ============================================================================

class PluginState:
    def __init__(self) -> None:
        self.lock = threading.RLock()
        self.stop_event = threading.Event()
        self.wake_event = threading.Event()
        self.worker_thread: Optional[threading.Thread] = None
        self.server: Optional[PluginServerInterface] = None
        self.config_path: str = ''
        self.sessions_path: str = ''
        self.config: Dict[str, Any] = copy.deepcopy(DEFAULT_CONFIG)

        # Online & playtime tracking
        self.online_players: Set[str] = set()
        self.player_sessions: Dict[str, Dict[str, float]] = {}
        self.uuid_cache: Dict[str, str] = {}
        self.self_hidden_players: Set[str] = set()

        # Rotation state
        self.global_page_index: int = 0
        self.global_page_started_at: float = time.time()
        self.per_player_rot: Dict[str, Tuple[int, float]] = {}

        # Scoreboard renderer state
        self.created_objs: Set[str] = set()
        self.created_teams: Set[str] = set()
        self.obj_cache: Dict[str, Tuple[str, Tuple[str, ...]]] = {}
        self.active_global_obj: Optional[str] = None
        self.active_team_objs: Dict[str, str] = {}
        self.player_team: Dict[str, str] = {}
        self.last_overflow_warn: float = 0.0

        # Lock-free filter state (for InfoFilter on MCDR main thread)
        self.suppress_console: bool = True
        self.obj_prefix: str = 'nb_'
        self.team_prefix: str = '_nb_t_'
        self.filter_display_until: float = 0.0
        self.filter_team_leave_until: float = 0.0

        # Async server info capture
        self.lp_lock = threading.Lock()
        self.lp_pending: Optional[Dict[str, Any]] = None
        self.list_pending_until: float = 0.0


STATE = PluginState()


# ============================================================================
# MCDR InfoFilter: Hide Plugin's Scoreboard/Team Command Feedback
# ============================================================================

_HOLDER_RE = re.compile(r'\bnb_(?:0[0-9]|1[0-4])\b')
_WINDOW_DISPLAY_RE = re.compile(
    r'^(?:Changed display slot sidebar|Nothing changed\. That display slot|已更改显示位置|没有变化)'
)
_WINDOW_TEAM_LEAVE_RE = re.compile(
    r"^(?:Removed .+ from (?:any )?team|Nothing changed\. .+?(?:isn't|is not) on any team|已将 .+ 移出队伍)"
)
_FEEDBACK_KEYWORDS = (
    'objective', 'display name', 'display slot', 'number format',
    'Set [', 'Reset [', 'team', 'Nothing changed',
    '计分', '显示', '数字格式', '队伍', '没有变化', '已将', '已创建', '已移除', '已重置', '未知', '设置',
)


def is_plugin_scoreboard_feedback(content: str, is_user: bool) -> bool:
    if is_user or not content or not STATE.suppress_console:
        return False

    obj_prefix = STATE.obj_prefix
    team_prefix = STATE.team_prefix
    if (
        _HOLDER_RE.search(content)
        or (obj_prefix and (obj_prefix + 'g_' in content or obj_prefix + 'c_' in content))
        or (team_prefix and team_prefix in content)
    ):
        if any(k in content for k in _FEEDBACK_KEYWORDS):
            return True

    now = time.time()
    if now <= STATE.filter_display_until and _WINDOW_DISPLAY_RE.match(content):
        return True
    if now <= STATE.filter_team_leave_until and _WINDOW_TEAM_LEAVE_RE.match(content):
        return True
    return False


class BoardInfoFilter(MCDRInfoFilter):
    def filter_server_info(self, info: Info) -> Optional[bool]:
        if is_plugin_scoreboard_feedback(info.content or '', info.is_user):
            if MCDRInfoActionFlag is not None and hasattr(info, 'action_flag'):
                info.action_flag &= ~MCDRInfoActionFlag.echo_to_console
                return True
            return False
        return True


# ============================================================================
# Config Normalization, Loading & Saving
# ============================================================================

def normalize_page(raw: Any, fallback_idx: int) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    name = str(raw.get('name') or f'page_{fallback_idx + 1}').strip() or f'page_{fallback_idx + 1}'
    raw_type = str(raw.get('type', 'show')).strip().lower()
    page_type = 'hide' if raw_type in ('hide', 'hidden', 'blank', 'off') else 'show'
    try:
        duration = float(raw.get('duration', 10))
    except (TypeError, ValueError):
        duration = 10.0
    duration = max(0.5, duration)

    raw_targets = raw.get('targets', 'all')
    if isinstance(raw_targets, str):
        targets: Any = 'all' if raw_targets.strip().lower() in ('all', '*', '@a', '') else [raw_targets.strip()]
    elif isinstance(raw_targets, list):
        cleaned = [str(x).strip() for x in raw_targets if str(x).strip()]
        if any(x.lower() in ('all', '*', '@a') for x in cleaned):
            targets = 'all'
        else:
            targets = cleaned
    else:
        targets = 'all'

    raw_exclude = raw.get('exclude', [])
    if isinstance(raw_exclude, list):
        exclude = [str(x).strip() for x in raw_exclude if str(x).strip()]
    else:
        exclude = []

    raw_lines = raw.get('lines', [])
    if isinstance(raw_lines, list):
        lines = [str(x) for x in raw_lines][:MAX_SIDEBAR_LINES]
    else:
        lines = []

    return {
        'name': name,
        'enabled': bool(raw.get('enabled', True)),
        'type': page_type,
        'duration': duration,
        'targets': targets,
        'exclude': exclude,
        'title': str(raw.get('title', '')),
        'lines': lines,
    }


def normalize_config(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raw = {}
    cfg = copy.deepcopy(DEFAULT_CONFIG)
    cfg['enabled'] = bool(raw.get('enabled', cfg['enabled']))
    cfg['suppress_console_output'] = bool(raw.get('suppress_console_output', cfg['suppress_console_output']))
    rot_mode = str(raw.get('rotation_mode', cfg['rotation_mode'])).strip().lower()
    cfg['rotation_mode'] = 'per_player' if rot_mode == 'per_player' else 'global'
    try:
        cfg['refresh_interval'] = max(0.2, float(raw.get('refresh_interval', cfg['refresh_interval'])))
    except (TypeError, ValueError):
        pass
    cfg['skip_empty_targets'] = bool(raw.get('skip_empty_targets', cfg['skip_empty_targets']))
    cfg['allow_player_self_toggle'] = bool(raw.get('allow_player_self_toggle', cfg['allow_player_self_toggle']))
    cfg['date_format'] = str(raw.get('date_format', cfg['date_format']))
    cfg['time_format'] = str(raw.get('time_format', cfg['time_format']))
    dur_fmt = str(raw.get('duration_format', cfg['duration_format'])).strip().lower()
    cfg['duration_format'] = dur_fmt if dur_fmt in ('hms_cn', 'hm_cn', 'hms', 'clock') else 'hms_cn'

    weekdays = raw.get('weekdays', cfg['weekdays'])
    if isinstance(weekdays, list) and len(weekdays) == 7:
        cfg['weekdays'] = [str(x) for x in weekdays]

    perm_raw = raw.get('permission', {})
    if isinstance(perm_raw, dict):
        pmode = str(perm_raw.get('mode', cfg['permission']['mode'])).strip().lower()
        cfg['permission']['mode'] = pmode if pmode in ('either', 'luckperms', 'mcdr') else 'either'
        try:
            cfg['permission']['mcdr_level'] = int(perm_raw.get('mcdr_level', cfg['permission']['mcdr_level']))
        except (TypeError, ValueError):
            pass
        cfg['permission']['luckperms_node'] = str(perm_raw.get('luckperms_node', cfg['permission']['luckperms_node'])).strip()
        try:
            cfg['permission']['luckperms_timeout'] = max(0.3, float(perm_raw.get('luckperms_timeout', cfg['permission']['luckperms_timeout'])))
        except (TypeError, ValueError):
            pass

    cfg['team_prefix'] = sanitize_prefix(str(raw.get('team_prefix', cfg['team_prefix'])), '_nb_t_')
    cfg['objective_prefix'] = sanitize_prefix(str(raw.get('objective_prefix', cfg['objective_prefix'])), 'nb_')

    if 'pages' in raw and isinstance(raw['pages'], list):
        seen_names: Set[str] = set()
        pages: List[Dict[str, Any]] = []
        for idx, p in enumerate(raw['pages']):
            np = normalize_page(p, idx)
            base_name = np['name']
            candidate = base_name
            suffix = 2
            while candidate.lower() in seen_names:
                candidate = f'{base_name}_{suffix}'
                suffix += 1
            np['name'] = candidate
            seen_names.add(candidate.lower())
            pages.append(np)
        cfg['pages'] = pages

    return cfg


def sync_filter_flags_locked() -> None:
    STATE.suppress_console = bool(STATE.config.get('suppress_console_output', True))
    STATE.obj_prefix = str(STATE.config.get('objective_prefix', 'nb_'))
    STATE.team_prefix = str(STATE.config.get('team_prefix', '_nb_t_'))


def save_config_locked() -> None:
    os.makedirs(os.path.dirname(STATE.config_path), exist_ok=True)
    tmp_path = STATE.config_path + '.tmp'
    with open(tmp_path, 'w', encoding='utf-8') as f:
        json.dump(STATE.config, f, indent=2, ensure_ascii=False)
    os.replace(tmp_path, STATE.config_path)


def load_config_from_disk(create_if_missing: bool = True) -> Tuple[bool, str]:
    with STATE.lock:
        if not os.path.exists(STATE.config_path):
            if create_if_missing:
                STATE.config = copy.deepcopy(DEFAULT_CONFIG)
                sync_filter_flags_locked()
                save_config_locked()
                return True, '已生成默认配置文件'
            return False, f'配置文件不存在: {STATE.config_path}'
        try:
            with open(STATE.config_path, 'r', encoding='utf-8') as f:
                raw = json.load(f)
        except json.JSONDecodeError as e:
            return False, f'JSON 解析错误 (第 {e.lineno} 行第 {e.colno} 列): {e.msg}'
        except OSError as e:
            return False, f'读取配置文件失败: {e}'

        STATE.config = normalize_config(raw)
        sync_filter_flags_locked()
        enabled_pages = get_enabled_pages_locked()
        if enabled_pages:
            STATE.global_page_index = STATE.global_page_index % len(enabled_pages)
        else:
            STATE.global_page_index = 0
        STATE.per_player_rot.clear()
        return True, f'已加载 {len(STATE.config["pages"])} 个页面'


def save_sessions_locked() -> None:
    if not STATE.sessions_path:
        return
    try:
        os.makedirs(os.path.dirname(STATE.sessions_path), exist_ok=True)
        payload = {
            'sessions': STATE.player_sessions,
            'uuids': STATE.uuid_cache,
            'self_hidden': sorted(STATE.self_hidden_players),
        }
        tmp = STATE.sessions_path + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)
        os.replace(tmp, STATE.sessions_path)
    except OSError:
        pass


def load_sessions_from_disk() -> None:
    if not STATE.sessions_path or not os.path.exists(STATE.sessions_path):
        return
    try:
        with open(STATE.sessions_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if isinstance(data, dict):
            if isinstance(data.get('sessions'), dict):
                STATE.player_sessions.update(data['sessions'])
            if isinstance(data.get('uuids'), dict):
                STATE.uuid_cache.update(data['uuids'])
            if isinstance(data.get('self_hidden'), list):
                STATE.self_hidden_players.update(str(x).lower() for x in data['self_hidden'])
    except Exception:
        pass


# ============================================================================
# World Stats & Playtime Resolution
# ============================================================================

def get_server_working_dir(server: PluginServerInterface) -> str:
    try:
        mcdr_cfg = server.get_mcdr_config()
        return mcdr_cfg.get('working_directory', 'server')
    except Exception:
        return 'server'


def get_level_name(working_dir: str) -> str:
    props_path = os.path.join(working_dir, 'server.properties')
    if os.path.exists(props_path):
        try:
            with open(props_path, 'r', encoding='utf-8', errors='ignore') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if line.startswith('level-name='):
                        val = line.split('=', 1)[1].strip()
                        if val:
                            return val
        except OSError:
            pass
    return 'world'


def resolve_player_uuid(server: PluginServerInterface, player: str) -> Optional[str]:
    key = player.lower()
    with STATE.lock:
        if key in STATE.uuid_cache:
            return STATE.uuid_cache[key]

    working_dir = get_server_working_dir(server)
    usercache_path = os.path.join(working_dir, 'usercache.json')
    if os.path.exists(usercache_path):
        try:
            with open(usercache_path, 'r', encoding='utf-8') as f:
                entries = json.load(f)
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict) and str(entry.get('name', '')).lower() == key:
                        u = str(entry.get('uuid', '')).strip()
                        if u:
                            with STATE.lock:
                                STATE.uuid_cache[key] = u
                            return u
        except Exception:
            pass

    try:
        offline_bytes = hashlib.md5(('OfflinePlayer:' + player).encode('utf-8')).digest()
        b = bytearray(offline_bytes)
        b[6] = (b[6] & 0x0F) | 0x30
        b[8] = (b[8] & 0x3F) | 0x80
        offline_uuid = str(uuid_lib.UUID(bytes=bytes(b)))
        level_name = get_level_name(working_dir)
        stats_file = os.path.join(working_dir, level_name, 'stats', f'{offline_uuid}.json')
        if os.path.exists(stats_file):
            with STATE.lock:
                STATE.uuid_cache[key] = offline_uuid
            return offline_uuid
    except Exception:
        pass
    return None


def read_vanilla_playtime_seconds(server: PluginServerInterface, player: str) -> float:
    player_uuid = resolve_player_uuid(server, player)
    if not player_uuid:
        return 0.0
    working_dir = get_server_working_dir(server)
    level_name = get_level_name(working_dir)
    stats_path = os.path.join(working_dir, level_name, 'stats', f'{player_uuid}.json')
    if not os.path.exists(stats_path):
        return 0.0
    try:
        with open(stats_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        custom = data.get('stats', {}).get('minecraft:custom', {})
        ticks = custom.get('minecraft:play_time')
        if ticks is None:
            ticks = custom.get('minecraft:play_one_minute', 0)
        return max(0.0, float(ticks) / 20.0)
    except Exception:
        return 0.0


def ensure_player_session(server: PluginServerInterface, player: str, reset_join: bool = False) -> None:
    now = time.time()
    with STATE.lock:
        if not reset_join and player in STATE.player_sessions:
            return
    base_total = read_vanilla_playtime_seconds(server, player)
    with STATE.lock:
        if reset_join or player not in STATE.player_sessions:
            STATE.player_sessions[player] = {
                'join_time': now,
                'base_total': base_total,
            }
            save_sessions_locked()


def get_player_times(server: PluginServerInterface, player: str, now: float) -> Tuple[int, int]:
    with STATE.lock:
        sess = STATE.player_sessions.get(player)
    if sess is None:
        ensure_player_session(server, player, reset_join=False)
        with STATE.lock:
            sess = STATE.player_sessions.get(player, {'join_time': now, 'base_total': 0.0})
    elapsed = max(0.0, now - float(sess.get('join_time', now)))
    base_total = float(sess.get('base_total', 0.0))
    return int(elapsed), int(base_total + elapsed)


# ============================================================================
# Target Matching, Rotation & Placeholders
# ============================================================================

def get_enabled_pages_locked() -> List[Dict[str, Any]]:
    return [p for p in STATE.config['pages'] if p.get('enabled', True)]


def player_matches_page(player: str, page: Dict[str, Any]) -> bool:
    pl = player.lower()
    excludes = {x.lower() for x in page.get('exclude', [])}
    if pl in excludes:
        return False
    targets = page.get('targets', 'all')
    if targets == 'all':
        return True
    if isinstance(targets, list):
        return pl in {x.lower() for x in targets}
    return False


def page_has_any_online_target(page: Dict[str, Any], online_players: Set[str]) -> bool:
    if page.get('type') == 'hide' and page.get('targets', 'all') == 'all':
        return True
    return any(player_matches_page(p, page) for p in online_players)


def advance_global_rotation_locked(now: float) -> Tuple[Optional[Dict[str, Any]], int, int]:
    enabled = get_enabled_pages_locked()
    if not enabled:
        STATE.global_page_index = 0
        return None, 0, 0

    if STATE.global_page_index >= len(enabled):
        STATE.global_page_index = 0
        STATE.global_page_started_at = now

    cur = enabled[STATE.global_page_index]
    dur = float(cur.get('duration', 10))
    if now - STATE.global_page_started_at >= dur:
        STATE.global_page_index = (STATE.global_page_index + 1) % len(enabled)
        STATE.global_page_started_at = now

    if STATE.config.get('skip_empty_targets', True) and STATE.online_players:
        for _ in range(len(enabled)):
            cand = enabled[STATE.global_page_index]
            if page_has_any_online_target(cand, STATE.online_players):
                break
            STATE.global_page_index = (STATE.global_page_index + 1) % len(enabled)
            STATE.global_page_started_at = now
        else:
            return None, 0, len(enabled)

    active = enabled[STATE.global_page_index]
    return active, STATE.global_page_index + 1, len(enabled)


def advance_player_rotation_locked(player: str, now: float) -> Tuple[Optional[Dict[str, Any]], int, int]:
    matching = [p for p in get_enabled_pages_locked() if player_matches_page(player, p)]
    if not matching:
        return None, 0, 0
    key = player.lower()
    idx, started_at = STATE.per_player_rot.get(key, (0, now))
    if idx >= len(matching):
        idx = 0
        started_at = now
    cur = matching[idx]
    if now - started_at >= float(cur.get('duration', 10)):
        idx = (idx + 1) % len(matching)
        started_at = now
    STATE.per_player_rot[key] = (idx, started_at)
    return matching[idx], idx + 1, len(matching)


def build_placeholder_context(
    server: PluginServerInterface,
    player: str,
    now: float,
    page_num: int,
    total_pages: int,
    page: Dict[str, Any],
) -> Dict[str, str]:
    dt = datetime.datetime.fromtimestamp(now)
    cfg = STATE.config
    dur_fmt = cfg.get('duration_format', 'hms_cn')
    sess_sec, total_sec = get_player_times(server, player, now)

    weekdays = cfg.get('weekdays', DEFAULT_CONFIG['weekdays'])
    weekday_str = weekdays[dt.weekday()] if len(weekdays) == 7 else dt.strftime('%a')

    show_pages = [p for p in get_enabled_pages_locked() if p.get('type') != 'hide']
    show_total = len(show_pages)
    show_idx = 0
    for i, sp in enumerate(show_pages):
        if sp.get('name') == page.get('name'):
            show_idx = i + 1
            break

    return {
        'player': player,
        'player_name': player,
        'date': dt.strftime(cfg.get('date_format', '%Y-%m-%d')),
        'time': dt.strftime(cfg.get('time_format', '%H:%M:%S')),
        'datetime': dt.strftime(f"{cfg.get('date_format', '%Y-%m-%d')} {cfg.get('time_format', '%H:%M:%S')}"),
        'year': dt.strftime('%Y'),
        'month': dt.strftime('%m'),
        'day': dt.strftime('%d'),
        'weekday': weekday_str,
        'session_time': format_duration(sess_sec, dur_fmt),
        'session_seconds': str(sess_sec),
        'session_minutes': str(sess_sec // 60),
        'session_hours': str(sess_sec // 3600),
        'total_time': format_duration(total_sec, dur_fmt),
        'total_seconds': str(total_sec),
        'total_minutes': str(total_sec // 60),
        'total_hours': str(total_sec // 3600),
        'online': str(len(STATE.online_players)),
        'online_count': str(len(STATE.online_players)),
        'page': str(page_num),
        'page_index': str(page_num),
        'total_pages': str(total_pages),
        'show_page': str(show_idx),
        'show_total_pages': str(show_total),
        'page_name': str(page.get('name', '')),
    }


def apply_placeholders(template: str, ctx: Dict[str, str]) -> str:
    if '{' not in template and '%' not in template:
        return template
    out = template
    for k, v in ctx.items():
        if '{' in out:
            out = out.replace('{' + k + '}', v)
        if '%' in out:
            out = out.replace('%' + k + '%', v)
    return out


# ============================================================================
# Vanilla 1.21.11 Scoreboard Renderer (Zero-Flicker + Team Slot Allocation)
# ============================================================================

def exec_mc(server: PluginServerInterface, cmd: str) -> None:
    if cmd.startswith('scoreboard objectives setdisplay'):
        STATE.filter_display_until = time.time() + 1.5
    elif cmd.startswith('team leave '):
        STATE.filter_team_leave_until = time.time() + 1.5
    server.execute(cmd)


def ensure_and_update_objective(server: PluginServerInterface, obj_name: str, title_snbt: str, lines_snbt: Tuple[str, ...]) -> None:
    if obj_name not in STATE.created_objs:
        exec_mc(server, f'scoreboard objectives remove {obj_name}')
        exec_mc(server, f'scoreboard objectives add {obj_name} dummy {title_snbt}')
        exec_mc(server, f'scoreboard objectives modify {obj_name} numberformat blank')
        STATE.created_objs.add(obj_name)
        old_lines: Tuple[str, ...] = ()
    else:
        old_title, old_lines = STATE.obj_cache.get(obj_name, ('', ()))
        if old_title != title_snbt:
            exec_mc(server, f'scoreboard objectives modify {obj_name} displayname {title_snbt}')

    new_lines = lines_snbt[:MAX_SIDEBAR_LINES]
    for i, line_snbt in enumerate(new_lines):
        holder = f'nb_{i:02d}'
        if i >= len(old_lines):
            exec_mc(server, f'scoreboard players set {holder} {obj_name} {MAX_SIDEBAR_LINES - i}')
            exec_mc(server, f'scoreboard players display name {holder} {obj_name} {line_snbt}')
        elif old_lines[i] != line_snbt:
            exec_mc(server, f'scoreboard players display name {holder} {obj_name} {line_snbt}')

    for j in range(len(new_lines), len(old_lines)):
        exec_mc(server, f'scoreboard players reset nb_{j:02d} {obj_name}')

    STATE.obj_cache[obj_name] = (title_snbt, new_lines)


def update_slot_buffer(
    server: PluginServerInterface,
    slot_id: str,
    display_slot: str,
    cur_obj: Optional[str],
    title_snbt: str,
    lines_snbt: Tuple[str, ...],
) -> str:
    prefix = STATE.config.get('objective_prefix', 'nb_')
    obj0 = f'{prefix}{slot_id}_0'
    obj1 = f'{prefix}{slot_id}_1'

    if cur_obj in (obj0, obj1):
        cached_title, cached_lines = STATE.obj_cache.get(cur_obj, ('', ()))
        if cached_title == title_snbt and len(cached_lines) == len(lines_snbt):
            ensure_and_update_objective(server, cur_obj, title_snbt, lines_snbt)
            return cur_obj
        alt_obj = obj1 if cur_obj == obj0 else obj0
        ensure_and_update_objective(server, alt_obj, title_snbt, lines_snbt)
        exec_mc(server, f'scoreboard objectives setdisplay {display_slot} {alt_obj}')
        return alt_obj

    ensure_and_update_objective(server, obj0, title_snbt, lines_snbt)
    exec_mc(server, f'scoreboard objectives setdisplay {display_slot} {obj0}')
    return obj0


def ensure_team(server: PluginServerInterface, color: str) -> str:
    team_name = f"{STATE.config.get('team_prefix', '_nb_t_')}{color}"
    if team_name not in STATE.created_teams:
        exec_mc(server, f'team remove {team_name}')
        exec_mc(server, f'team add {team_name}')
        exec_mc(server, f'team modify {team_name} color {color}')
        STATE.created_teams.add(team_name)
    return team_name


def clear_all_display(server: PluginServerInterface) -> None:
    if STATE.active_global_obj is not None:
        exec_mc(server, 'scoreboard objectives setdisplay sidebar')
        STATE.active_global_obj = None
    for color, obj in list(STATE.active_team_objs.items()):
        if obj is not None:
            exec_mc(server, f'scoreboard objectives setdisplay sidebar.team.{color}')
    STATE.active_team_objs.clear()
    for player in list(STATE.player_team.keys()):
        if player in STATE.online_players:
            exec_mc(server, f'team leave {player}')
    STATE.player_team.clear()


def cleanup_minecraft_scoreboard(server: PluginServerInterface) -> None:
    if not server.is_server_startup():
        return
    clear_all_display(server)
    for team_name in list(STATE.created_teams):
        exec_mc(server, f'team remove {team_name}')
    STATE.created_teams.clear()
    for obj_name in list(STATE.created_objs):
        exec_mc(server, f'scoreboard objectives remove {obj_name}')
    STATE.created_objs.clear()
    STATE.obj_cache.clear()


def sync_board(server: PluginServerInterface) -> None:
    with STATE.lock:
        if not server.is_server_startup():
            return
        if not STATE.online_players:
            return
        if not STATE.config.get('enabled', True):
            clear_all_display(server)
            return

        now = time.time()
        rot_mode = STATE.config.get('rotation_mode', 'global')
        desired: Dict[str, Tuple[Dict[str, Any], int, int]] = {}

        if rot_mode == 'per_player':
            for player in sorted(STATE.online_players):
                if player.lower() in STATE.self_hidden_players:
                    continue
                page, p_num, total_p = advance_player_rotation_locked(player, now)
                if page is not None and page.get('type') != 'hide':
                    desired[player] = (page, p_num, total_p)
        else:
            page, p_num, total_p = advance_global_rotation_locked(now)
            if page is not None and page.get('type') != 'hide':
                for player in sorted(STATE.online_players):
                    if player.lower() in STATE.self_hidden_players:
                        continue
                    if player_matches_page(player, page):
                        desired[player] = (page, p_num, total_p)

        if not desired:
            clear_all_display(server)
            return

        groups: Dict[Tuple[str, Tuple[str, ...]], List[str]] = {}
        for player, (page, p_num, total_p) in desired.items():
            ctx = build_placeholder_context(server, player, now, p_num, total_p, page)
            title_snbt = text_to_snbt(apply_placeholders(page.get('title', ''), ctx))
            lines_snbt = tuple(
                text_to_snbt(apply_placeholders(line, ctx))
                for line in page.get('lines', [])[:MAX_SIDEBAR_LINES]
            )
            key = (title_snbt, lines_snbt)
            groups.setdefault(key, []).append(player)

        hidden_count = len(STATE.online_players) - len(desired)

        # Case 1: 全部在线玩家显示完全相同的内容 -> 直接使用全局 sidebar
        if len(groups) == 1 and hidden_count == 0:
            (title_snbt, lines_snbt) = next(iter(groups.keys()))
            for color, obj in list(STATE.active_team_objs.items()):
                if obj is not None:
                    exec_mc(server, f'scoreboard objectives setdisplay sidebar.team.{color}')
            STATE.active_team_objs.clear()
            for p in list(STATE.player_team.keys()):
                if p in STATE.online_players:
                    exec_mc(server, f'team leave {p}')
            STATE.player_team.clear()

            STATE.active_global_obj = update_slot_buffer(
                server, 'g', 'sidebar', STATE.active_global_obj, title_snbt, lines_snbt
            )
            return

        # Case 2: 部分玩家可见 或 含有按玩家区分的占位符 -> 使用 sidebar.team.<color>
        if STATE.active_global_obj is not None:
            exec_mc(server, 'scoreboard objectives setdisplay sidebar')
            STATE.active_global_obj = None

        group_items = list(groups.items())
        if len(group_items) > len(TEAM_COLORS):
            if now - STATE.last_overflow_warn > 60.0:
                STATE.last_overflow_warn = now
                server.logger.warning(
                    f'[NoticeBoard] 当前同时需要 {len(group_items)} 个独立计分栏，超过原版 16 种队伍颜色上限，部分玩家将暂不显示。'
                )
            group_items = group_items[:len(TEAM_COLORS)]

        used_colors: Set[str] = set()
        assigned: List[Tuple[str, Tuple[str, Tuple[str, ...]], List[str]]] = []
        unassigned: List[Tuple[Tuple[str, Tuple[str, ...]], List[str]]] = []

        for key, players_in_grp in group_items:
            preferred = None
            if len(players_in_grp) == 1:
                c = STATE.player_team.get(players_in_grp[0])
                if c in TEAM_COLORS and c not in used_colors:
                    preferred = c
            if preferred:
                used_colors.add(preferred)
                assigned.append((preferred, key, players_in_grp))
            else:
                unassigned.append((key, players_in_grp))

        avail_colors = [c for c in TEAM_COLORS if c not in used_colors]
        for (key, players_in_grp), color in zip(unassigned, avail_colors):
            used_colors.add(color)
            assigned.append((color, key, players_in_grp))

        visible_assigned_players: Set[str] = set()
        for _, _, players_in_grp in assigned:
            visible_assigned_players.update(players_in_grp)

        for p in list(STATE.player_team.keys()):
            if p not in visible_assigned_players:
                if p in STATE.online_players:
                    exec_mc(server, f'team leave {p}')
                STATE.player_team.pop(p, None)

        for color in list(STATE.active_team_objs.keys()):
            if color not in used_colors:
                exec_mc(server, f'scoreboard objectives setdisplay sidebar.team.{color}')
                STATE.active_team_objs.pop(color, None)

        for color, (title_snbt, lines_snbt), players_in_grp in assigned:
            team_name = ensure_team(server, color)
            for p in players_in_grp:
                if STATE.player_team.get(p) != color:
                    exec_mc(server, f'team join {team_name} {p}')
                    STATE.player_team[p] = color

            cur_obj = STATE.active_team_objs.get(color)
            new_obj = update_slot_buffer(
                server, f'c_{color}', f'sidebar.team.{color}', cur_obj, title_snbt, lines_snbt
            )
            STATE.active_team_objs[color] = new_obj


def ticker_loop(server: PluginServerInterface) -> None:
    while not STATE.stop_event.is_set():
        try:
            sync_board(server)
        except Exception as e:
            server.logger.error(f'[NoticeBoard] 刷新循环异常: {e}')
        with STATE.lock:
            interval = float(STATE.config.get('refresh_interval', 1.0))
        STATE.wake_event.wait(timeout=max(0.2, interval))
        STATE.wake_event.clear()


# ============================================================================
# Permission Checking (MCDR Permission + LuckPerms Support)
# ============================================================================

def parse_lp_check_output(text: str) -> Optional[bool]:
    for line in reversed(text.splitlines()):
        m = re.search(r'(?:result|结果)\s*:\s*(true|false|undefined)\b', line, re.I)
        if m:
            return m.group(1).lower() == 'true'
        m2 = re.search(r':\s*(true|false|undefined)\s*$', line.strip(), re.I)
        if m2:
            return m2.group(1).lower() == 'true'
    return None


def check_luckperms_permission(server: PluginServerInterface, player: str, node: str, timeout: float) -> bool:
    if not node or not re.fullmatch(r'[a-zA-Z0-9_.*-]+', node):
        return False
    if not re.fullmatch(r'[a-zA-Z0-9_.-]+', player):
        return False

    try:
        if server.is_rcon_running():
            out = server.rcon_query(f'lp user {player} permission check {node}')
            if out is not None:
                parsed = parse_lp_check_output(out)
                if parsed is not None:
                    return parsed
    except Exception:
        pass

    with STATE.lp_lock:
        evt = threading.Event()
        pending = {
            'player': player.lower(),
            'node': node.lower(),
            'saw_header': False,
            'result': None,
            'event': evt,
        }
        STATE.lp_pending = pending
        try:
            server.execute(f'lp user {player} permission check {node}')
            evt.wait(timeout=timeout)
            return bool(pending['result'])
        finally:
            if STATE.lp_pending is pending:
                STATE.lp_pending = None


def check_admin_permission(source: CommandSource) -> bool:
    if source.is_console:
        return True
    with STATE.lock:
        perm_cfg = copy.deepcopy(STATE.config.get('permission', DEFAULT_CONFIG['permission']))

    mode = perm_cfg.get('mode', 'either')
    mcdr_level = int(perm_cfg.get('mcdr_level', 3))
    lp_node = str(perm_cfg.get('luckperms_node', 'notice_board.admin'))
    lp_timeout = float(perm_cfg.get('luckperms_timeout', 1.5))

    if mode in ('either', 'mcdr') and source.has_permission(mcdr_level):
        return True
    if mode == 'mcdr':
        return False
    if source.is_player:
        server = source.get_server()
        if server.is_server_startup():
            return check_luckperms_permission(server, source.player, lp_node, lp_timeout)
    return False


def reply_no_perm(source: CommandSource) -> None:
    with STATE.lock:
        perm_cfg = STATE.config.get('permission', DEFAULT_CONFIG['permission'])
        node = perm_cfg.get('luckperms_node', 'notice_board.admin')
        lvl = perm_cfg.get('mcdr_level', 3)
    source.reply(
        RTextList(
            RText('权限不足！', RColor.red),
            RText(' 需要 LuckPerms 节点 ', RColor.gray),
            RText(node, RColor.yellow),
            RText(f' 或 MCDR 权限等级 >= {lvl}', RColor.gray),
        )
    )


def admin_action(fn):
    @new_thread('NoticeBoard-Cmd')
    def wrapper(source: CommandSource, context: CommandContext):
        if not check_admin_permission(source):
            reply_no_perm(source)
            return
        fn(source, context)
    return wrapper


# ============================================================================
# Page Lookup & Command Handlers
# ============================================================================

def find_page_locked(name: str) -> Tuple[Optional[int], Optional[Dict[str, Any]]]:
    nl = name.lower()
    for idx, p in enumerate(STATE.config['pages']):
        if p['name'].lower() == nl:
            return idx, p
    return None, None


def format_targets_summary(page: Dict[str, Any]) -> str:
    t = page.get('targets', 'all')
    t_str = '全部玩家' if t == 'all' else (', '.join(t) if t else '无')
    ex = page.get('exclude', [])
    if ex:
        t_str += f' (排除: {", ".join(ex)})'
    return t_str


def parse_line_text_arg(raw: Optional[str]) -> str:
    if raw is None:
        return ''
    s = raw.strip()
    if s in ('""', "''", '<blank>', '<empty>'):
        return ''
    return raw


def cmd_help(source: CommandSource, context: CommandContext) -> None:
    lines = [
        RText('=== NoticeBoard 公告栏帮助 ===', RColor.gold, styles=RStyle.bold),
        RText('!!board list', RColor.aqua).c(RAction.suggest_command, '!!board list') + RText(' - 查看所有页面', RColor.gray),
        RText('!!board info <名称>', RColor.aqua).c(RAction.suggest_command, '!!board info ') + RText(' - 查看页面详情', RColor.gray),
        RText('!!board reload', RColor.aqua).c(RAction.suggest_command, '!!board reload') + RText(' - 重载配置文件', RColor.gray),
        RText('!!board enable / disable', RColor.aqua).c(RAction.suggest_command, '!!board enable') + RText(' - 全局开关公告栏', RColor.gray),
        RText('!!board next / prev / goto <名称>', RColor.aqua).c(RAction.suggest_command, '!!board next') + RText(' - 手动切换页面', RColor.gray),
        RText('!!board add <名称> <秒> <标题>', RColor.aqua).c(RAction.suggest_command, '!!board add ') + RText(' - 添加显示页', RColor.gray),
        RText('!!board addhide <名称> <秒>', RColor.aqua).c(RAction.suggest_command, '!!board addhide ') + RText(' - 添加隐藏页(留空间隔)', RColor.gray),
        RText('!!board remove <名称>', RColor.aqua).c(RAction.suggest_command, '!!board remove ') + RText(' - 删除页面', RColor.gray),
        RText('!!board settitle <名称> [标题]', RColor.aqua).c(RAction.suggest_command, '!!board settitle ') + RText(' - 修改标题', RColor.gray),
        RText('!!board setduration <名称> <秒>', RColor.aqua).c(RAction.suggest_command, '!!board setduration ') + RText(' - 修改持续时间', RColor.gray),
        RText('!!board settype <名称> <show|hide>', RColor.aqua).c(RAction.suggest_command, '!!board settype ') + RText(' - 修改页面类型', RColor.gray),
        RText('!!board toggle <名称>', RColor.aqua).c(RAction.suggest_command, '!!board toggle ') + RText(' - 启用/禁用该页', RColor.gray),
        RText('!!board move <名称> <序号>', RColor.aqua).c(RAction.suggest_command, '!!board move ') + RText(' - 调整顺序(从1开始)', RColor.gray),
        RText('!!board addline <名称> [文本]', RColor.aqua).c(RAction.suggest_command, '!!board addline ') + RText(' - 追加一行(留空为空行)', RColor.gray),
        RText('!!board setline <名称> <行号> [文本]', RColor.aqua).c(RAction.suggest_command, '!!board setline ') + RText(' - 修改指定行', RColor.gray),
        RText('!!board insertline <名称> <行号> [文本]', RColor.aqua).c(RAction.suggest_command, '!!board insertline ') + RText(' - 插入行', RColor.gray),
        RText('!!board delline <名称> <行号>', RColor.aqua).c(RAction.suggest_command, '!!board delline ') + RText(' - 删除指定行', RColor.gray),
        RText('!!board target <名称> all | set <玩家...> | add <玩家> | remove <玩家>', RColor.aqua).c(RAction.suggest_command, '!!board target ') + RText(' - 设置可见目标', RColor.gray),
        RText('!!board exclude <名称> clear | add <玩家> | remove <玩家>', RColor.aqua).c(RAction.suggest_command, '!!board exclude ') + RText(' - 设置排除玩家', RColor.gray),
        RText('!!board mode <global|per_player>', RColor.aqua).c(RAction.suggest_command, '!!board mode ') + RText(' - 切换全局/独立轮播模式', RColor.gray),
        RText('!!board hide / show', RColor.green).c(RAction.suggest_command, '!!board hide') + RText(' - 玩家个人隐藏/显示公告栏', RColor.gray),
        RText('占位符: {player} {date} {time} {session_time} {total_time} {online} {page}/{total_pages}', RColor.yellow),
        RText('颜色: &0-&f, &l/o/n/m/k/r, &#RRGGBB', RColor.yellow),
    ]
    for line in lines:
        source.reply(line)


@admin_action
def cmd_list(source: CommandSource, context: CommandContext) -> None:
    with STATE.lock:
        enabled_global = STATE.config.get('enabled', True)
        rot_mode = STATE.config.get('rotation_mode', 'global')
        pages = copy.deepcopy(STATE.config['pages'])
        cur_idx = STATE.global_page_index

    status_txt = RText('开启', RColor.green) if enabled_global else RText('关闭', RColor.red)
    source.reply(RTextList(
        RText('公告栏状态: ', RColor.gold), status_txt,
        RText(f' | 模式: {rot_mode} | 共 {len(pages)} 页', RColor.gray),
    ))
    if not pages:
        source.reply(RText('当前没有任何页面，使用 !!board add 添加。', RColor.yellow))
        return

    enabled_only = [p['name'] for p in pages if p.get('enabled', True)]
    active_name = enabled_only[cur_idx % len(enabled_only)] if enabled_only and rot_mode == 'global' else None

    for i, p in enumerate(pages, start=1):
        en_mark = RText('[✓] ', RColor.green) if p['enabled'] else RText('[✗] ', RColor.red)
        type_mark = RText('[隐藏] ', RColor.dark_gray) if p['type'] == 'hide' else RText('[显示] ', RColor.aqua)
        cur_mark = RText('▶ ', RColor.yellow) if p['name'] == active_name else RText('  ')
        title_preview = legacy_to_rtext(p['title']) if p['type'] == 'show' else RText('(隐藏间隔)', RColor.gray)
        source.reply(RTextList(
            cur_mark,
            RText(f'#{i} ', RColor.gray),
            en_mark,
            type_mark,
            RText(p['name'], RColor.gold).c(RAction.run_command, f'!!board info {p["name"]}').h('点击查看详情'),
            RText(f' ({p["duration"]}s, {format_targets_summary(p)}) ', RColor.gray),
            title_preview,
        ))


@admin_action
def cmd_info(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    with STATE.lock:
        idx, page = find_page_locked(name)
        page = copy.deepcopy(page) if page is not None else None
    if page is None:
        source.reply(RText(f'未找到页面: {name}', RColor.red))
        return

    source.reply(RText(f'=== 页面 #{idx + 1}: {page["name"]} ===', RColor.gold, styles=RStyle.bold))
    source.reply(RText(f'状态: {"启用" if page["enabled"] else "禁用"} | 类型: {page["type"]} | 时长: {page["duration"]}s', RColor.gray))
    source.reply(RText(f'目标: {format_targets_summary(page)}', RColor.gray))
    source.reply(RTextList(RText('标题: ', RColor.gray), legacy_to_rtext(page['title']), RText(f'  (原文: {page["title"]})', RColor.dark_gray)))
    lines = page.get('lines', [])
    if not lines:
        source.reply(RText('内容行: (空)', RColor.gray))
    else:
        source.reply(RText(f'内容行 ({len(lines)}):', RColor.gray))
        for li, ltxt in enumerate(lines, start=1):
            source.reply(RTextList(
                RText(f'  {li}. ', RColor.yellow).c(RAction.suggest_command, f'!!board setline {page["name"]} {li} {ltxt}').h('点击修改此行'),
                legacy_to_rtext(ltxt) if ltxt else RText('<空行>', RColor.dark_gray),
                RText(f'  ({ltxt})', RColor.dark_gray),
            ))


@admin_action
def cmd_reload(source: CommandSource, context: CommandContext) -> None:
    ok, msg = load_config_from_disk(create_if_missing=True)
    if ok:
        STATE.wake_event.set()
        source.reply(RText(f'[NoticeBoard] 重载成功: {msg}', RColor.green))
    else:
        source.reply(RText(f'[NoticeBoard] 重载失败，保留原配置: {msg}', RColor.red))


def cmd_set_enabled(enabled: bool):
    @admin_action
    def inner(source: CommandSource, context: CommandContext) -> None:
        with STATE.lock:
            STATE.config['enabled'] = enabled
            save_config_locked()
        STATE.wake_event.set()
        source.reply(RText(f'公告栏已{"开启" if enabled else "关闭"}', RColor.green if enabled else RColor.yellow))
    return inner


def cmd_nav(direction: int):
    @admin_action
    def inner(source: CommandSource, context: CommandContext) -> None:
        with STATE.lock:
            enabled_pages = get_enabled_pages_locked()
            if not enabled_pages:
                source.reply(RText('没有已启用的页面。', RColor.red))
                return
            STATE.global_page_index = (STATE.global_page_index + direction) % len(enabled_pages)
            STATE.global_page_started_at = time.time()
            target_name = enabled_pages[STATE.global_page_index]['name']
        STATE.wake_event.set()
        source.reply(RText(f'已切换到页面: {target_name}', RColor.green))
    return inner


@admin_action
def cmd_goto(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    with STATE.lock:
        enabled_pages = get_enabled_pages_locked()
        for i, p in enumerate(enabled_pages):
            if p['name'].lower() == name.lower():
                STATE.global_page_index = i
                STATE.global_page_started_at = time.time()
                STATE.wake_event.set()
                source.reply(RText(f'已切换到页面: {p["name"]}', RColor.green))
                return
    source.reply(RText(f'未找到已启用的页面: {name}', RColor.red))


def cmd_add(page_type: str):
    @admin_action
    def inner(source: CommandSource, context: CommandContext) -> None:
        name = context['name'].strip()
        duration = float(context['duration'])
        title = context.get('title', '')
        if duration <= 0:
            source.reply(RText('持续时间必须大于 0 秒。', RColor.red))
            return
        with STATE.lock:
            _, existing = find_page_locked(name)
            if existing is not None:
                source.reply(RText(f'页面 "{name}" 已存在！', RColor.red))
                return
            new_page = normalize_page({
                'name': name,
                'enabled': True,
                'type': page_type,
                'duration': duration,
                'targets': 'all',
                'exclude': [],
                'title': title if page_type == 'show' else '',
                'lines': [] if page_type == 'hide' else ['&7欢迎来到服务器, &b{player}'],
            }, len(STATE.config['pages']))
            STATE.config['pages'].append(new_page)
            save_config_locked()
        STATE.wake_event.set()
        source.reply(RText(f'已添加{"隐藏" if page_type == "hide" else "显示"}页面 "{name}" ({duration}s)', RColor.green))
    return inner


@admin_action
def cmd_remove(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    with STATE.lock:
        idx, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        removed_name = page['name']
        STATE.config['pages'].pop(idx)
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RText(f'已删除页面: {removed_name}', RColor.green))


@admin_action
def cmd_settitle(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    title = parse_line_text_arg(context.get('title', ''))
    with STATE.lock:
        _, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        page['title'] = title
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RTextList(RText(f'已更新 {page["name"]} 标题为: ', RColor.green), legacy_to_rtext(title)))


@admin_action
def cmd_setduration(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    duration = float(context['duration'])
    if duration <= 0:
        source.reply(RText('持续时间必须大于 0 秒。', RColor.red))
        return
    with STATE.lock:
        _, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        page['duration'] = max(0.5, duration)
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RText(f'已更新 {page["name"]} 持续时间为 {page["duration"]}s', RColor.green))


@admin_action
def cmd_settype(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    ptype = context['ptype'].strip().lower()
    if ptype not in ('show', 'hide'):
        source.reply(RText('页面类型必须为 show 或 hide。', RColor.red))
        return
    with STATE.lock:
        _, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        page['type'] = ptype
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RText(f'已将页面 {page["name"]} 类型设为 {ptype}', RColor.green))


@admin_action
def cmd_toggle_page(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    with STATE.lock:
        _, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        page['enabled'] = not page['enabled']
        new_state = page['enabled']
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RText(f'页面 {page["name"]} 已{"启用" if new_state else "禁用"}', RColor.green if new_state else RColor.yellow))


@admin_action
def cmd_move_page(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    target_pos = int(context['index'])
    with STATE.lock:
        idx, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        pages = STATE.config['pages']
        if target_pos < 1 or target_pos > len(pages):
            source.reply(RText(f'序号超出范围 (1 ~ {len(pages)})。', RColor.red))
            return
        item = pages.pop(idx)
        pages.insert(target_pos - 1, item)
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RText(f'已将页面 {item["name"]} 移动到第 {target_pos} 位', RColor.green))


@admin_action
def cmd_addline(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    text = parse_line_text_arg(context.get('text', ''))
    with STATE.lock:
        _, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        if len(page['lines']) >= MAX_SIDEBAR_LINES:
            source.reply(RText(f'原版计分栏最多显示 {MAX_SIDEBAR_LINES} 行！', RColor.red))
            return
        page['lines'].append(text)
        line_no = len(page['lines'])
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RTextList(RText(f'已向 {page["name"]} 添加第 {line_no} 行: ', RColor.green), legacy_to_rtext(text)))


@admin_action
def cmd_setline(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    line_num = int(context['line_num'])
    text = parse_line_text_arg(context.get('text', ''))
    with STATE.lock:
        _, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        lines = page['lines']
        if line_num < 1 or line_num > MAX_SIDEBAR_LINES or line_num > len(lines) + 1:
            source.reply(RText(f'行号无效 (当前共 {len(lines)} 行，可填 1 ~ {min(MAX_SIDEBAR_LINES, len(lines) + 1)})。', RColor.red))
            return
        if line_num == len(lines) + 1:
            lines.append(text)
        else:
            lines[line_num - 1] = text
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RTextList(RText(f'已设置 {page["name"]} 第 {line_num} 行: ', RColor.green), legacy_to_rtext(text)))


@admin_action
def cmd_insertline(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    line_num = int(context['line_num'])
    text = parse_line_text_arg(context.get('text', ''))
    with STATE.lock:
        _, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        lines = page['lines']
        if len(lines) >= MAX_SIDEBAR_LINES:
            source.reply(RText(f'原版计分栏最多显示 {MAX_SIDEBAR_LINES} 行！', RColor.red))
            return
        if line_num < 1 or line_num > len(lines) + 1:
            source.reply(RText(f'行号无效 (可填 1 ~ {len(lines) + 1})。', RColor.red))
            return
        lines.insert(line_num - 1, text)
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RTextList(RText(f'已在 {page["name"]} 第 {line_num} 行插入: ', RColor.green), legacy_to_rtext(text)))


@admin_action
def cmd_delline(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    line_num = int(context['line_num'])
    with STATE.lock:
        _, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        lines = page['lines']
        if line_num < 1 or line_num > len(lines):
            source.reply(RText(f'行号无效 (当前共 {len(lines)} 行)。', RColor.red))
            return
        lines.pop(line_num - 1)
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RText(f'已删除 {page["name"]} 第 {line_num} 行', RColor.green))


@admin_action
def cmd_target_all(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    with STATE.lock:
        _, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        page['targets'] = 'all'
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RText(f'已将 {page["name"]} 目标设为: 全部玩家', RColor.green))


@admin_action
def cmd_target_set(source: CommandSource, context: CommandContext) -> None:
    name = context['name']
    raw_players = context['players']
    players = [p.strip() for p in re.split(r'[\s,，]+', raw_players) if p.strip()]
    if not players:
        source.reply(RText('请提供至少一个玩家名。', RColor.red))
        return
    with STATE.lock:
        _, page = find_page_locked(name)
        if page is None:
            source.reply(RText(f'未找到页面: {name}', RColor.red))
            return
        page['targets'] = players
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RText(f'已将 {page["name"]} 目标设为: {", ".join(players)}', RColor.green))


def cmd_target_mod(op: str):
    @admin_action
    def inner(source: CommandSource, context: CommandContext) -> None:
        name = context['name']
        player = context['player'].strip()
        with STATE.lock:
            _, page = find_page_locked(name)
            if page is None:
                source.reply(RText(f'未找到页面: {name}', RColor.red))
                return
            t = page.get('targets', 'all')
            if op == 'add':
                if t == 'all':
                    page['targets'] = [player]
                elif isinstance(t, list):
                    if player.lower() not in {x.lower() for x in t}:
                        t.append(player)
            else:
                if t == 'all':
                    source.reply(RText('当前目标为 all，如需排除特定玩家请使用 !!board exclude add <玩家>。', RColor.yellow))
                    return
                if isinstance(t, list):
                    page['targets'] = [x for x in t if x.lower() != player.lower()]
            save_config_locked()
            summary = format_targets_summary(page)
        STATE.wake_event.set()
        source.reply(RText(f'已更新 {page["name"]} 目标: {summary}', RColor.green))
    return inner


def cmd_exclude(op: str):
    @admin_action
    def inner(source: CommandSource, context: CommandContext) -> None:
        name = context['name']
        player = context.get('player', '').strip()
        with STATE.lock:
            _, page = find_page_locked(name)
            if page is None:
                source.reply(RText(f'未找到页面: {name}', RColor.red))
                return
            ex = page.setdefault('exclude', [])
            if op == 'clear':
                page['exclude'] = []
            elif op == 'add':
                if player and player.lower() not in {x.lower() for x in ex}:
                    ex.append(player)
            elif op == 'remove':
                page['exclude'] = [x for x in ex if x.lower() != player.lower()]
            save_config_locked()
            summary = format_targets_summary(page)
        STATE.wake_event.set()
        source.reply(RText(f'已更新 {page["name"]} 排除名单: {summary}', RColor.green))
    return inner


@admin_action
def cmd_mode(source: CommandSource, context: CommandContext) -> None:
    mode = context['mode'].strip().lower()
    if mode not in ('global', 'per_player'):
        source.reply(RText('轮播模式必须为 global 或 per_player。', RColor.red))
        return
    with STATE.lock:
        STATE.config['rotation_mode'] = mode
        STATE.per_player_rot.clear()
        save_config_locked()
    STATE.wake_event.set()
    source.reply(RText(f'已切换轮播模式为: {mode}', RColor.green))


def cmd_self_visibility(hide: bool):
    def inner(source: CommandSource, context: CommandContext) -> None:
        if not source.is_player:
            source.reply(RText('此命令仅限游戏内玩家使用。', RColor.red))
            return
        with STATE.lock:
            if not STATE.config.get('allow_player_self_toggle', True):
                source.reply(RText('服务器已禁用个人隐藏公告栏功能。', RColor.red))
                return
            pl = source.player.lower()
            if hide:
                STATE.self_hidden_players.add(pl)
            else:
                STATE.self_hidden_players.discard(pl)
            save_sessions_locked()
        STATE.wake_event.set()
        source.reply(RText('已为你隐藏公告栏，输入 !!board show 可恢复显示。' if hide else '已恢复显示公告栏。', RColor.green))
    return inner


# ============================================================================
# Command Registration
# ============================================================================

def build_command_tree(root_literal: str) -> Literal:
    return (
        Literal(root_literal)
        .runs(cmd_help)
        .then(Literal('help').runs(cmd_help))
        .then(Literal('list').runs(cmd_list))
        .then(Literal('info').then(Text('name').runs(cmd_info)))
        .then(Literal('reload').runs(cmd_reload))
        .then(Literal('enable').runs(cmd_set_enabled(True)))
        .then(Literal('disable').runs(cmd_set_enabled(False)))
        .then(Literal('next').runs(cmd_nav(1)))
        .then(Literal('prev').runs(cmd_nav(-1)))
        .then(Literal('goto').then(Text('name').runs(cmd_goto)))
        .then(
            Literal('add').then(
                Text('name').then(
                    Float('duration').then(
                        GreedyText('title').runs(cmd_add('show'))
                    )
                )
            )
        )
        .then(
            Literal('addhide').then(
                Text('name').then(
                    Float('duration').runs(cmd_add('hide'))
                )
            )
        )
        .then(Literal('remove').then(Text('name').runs(cmd_remove)))
        .then(
            Literal('settitle').then(
                Text('name').runs(cmd_settitle).then(GreedyText('title').runs(cmd_settitle))
            )
        )
        .then(
            Literal('setduration').then(
                Text('name').then(Float('duration').runs(cmd_setduration))
            )
        )
        .then(
            Literal('settype').then(
                Text('name').then(Text('ptype').runs(cmd_settype))
            )
        )
        .then(Literal('toggle').then(Text('name').runs(cmd_toggle_page)))
        .then(
            Literal('move').then(
                Text('name').then(Integer('index').runs(cmd_move_page))
            )
        )
        .then(
            Literal('addline').then(
                Text('name').runs(cmd_addline).then(GreedyText('text').runs(cmd_addline))
            )
        )
        .then(
            Literal('setline').then(
                Text('name').then(
                    Integer('line_num').runs(cmd_setline).then(GreedyText('text').runs(cmd_setline))
                )
            )
        )
        .then(
            Literal('insertline').then(
                Text('name').then(
                    Integer('line_num').runs(cmd_insertline).then(GreedyText('text').runs(cmd_insertline))
                )
            )
        )
        .then(
            Literal('delline').then(
                Text('name').then(Integer('line_num').runs(cmd_delline))
            )
        )
        .then(
            Literal('target').then(
                Text('name')
                .then(Literal('all').runs(cmd_target_all))
                .then(Literal('set').then(GreedyText('players').runs(cmd_target_set)))
                .then(Literal('add').then(Text('player').runs(cmd_target_mod('add'))))
                .then(Literal('remove').then(Text('player').runs(cmd_target_mod('remove'))))
            )
        )
        .then(
            Literal('exclude').then(
                Text('name')
                .then(Literal('clear').runs(cmd_exclude('clear')))
                .then(Literal('add').then(Text('player').runs(cmd_exclude('add'))))
                .then(Literal('remove').then(Text('player').runs(cmd_exclude('remove'))))
            )
        )
        .then(Literal('mode').then(Text('mode').runs(cmd_mode)))
        .then(Literal('hide').runs(cmd_self_visibility(True)))
        .then(Literal('show').runs(cmd_self_visibility(False)))
    )


# ============================================================================
# Online Player Discovery Helper (for hot-load while players are online)
# ============================================================================

def parse_list_output(server: PluginServerInterface, content: str) -> bool:
    m = re.search(r'There are \d+ of a max of \d+ players online:\s*(.*)', content)
    if not m:
        return False
    names_raw = m.group(1).strip()
    names = [n.strip() for n in names_raw.split(',') if n.strip()] if names_raw else []
    with STATE.lock:
        for p in names:
            STATE.online_players.add(p)
    for p in names:
        ensure_player_session(server, p, reset_join=False)
    STATE.wake_event.set()
    return True


def query_online_players(server: PluginServerInterface) -> None:
    if not server.is_server_startup():
        return
    try:
        if server.is_rcon_running():
            out = server.rcon_query('list')
            if out and parse_list_output(server, out):
                return
    except Exception:
        pass
    with STATE.lock:
        STATE.list_pending_until = time.time() + 3.0
    server.execute('list')


# ============================================================================
# MCDR Lifecycle & Events
# ============================================================================

def on_load(server: PluginServerInterface, prev_module: Any) -> None:
    STATE.server = server
    data_folder = server.get_data_folder()
    os.makedirs(data_folder, exist_ok=True)
    STATE.config_path = os.path.join(data_folder, 'config.json')
    STATE.sessions_path = os.path.join(data_folder, 'sessions_cache.json')

    if prev_module is not None and hasattr(prev_module, 'STATE'):
        old = prev_module.STATE
        with old.lock:
            STATE.online_players = set(old.online_players)
            STATE.player_sessions = copy.deepcopy(old.player_sessions)
            STATE.uuid_cache = dict(old.uuid_cache)
            STATE.self_hidden_players = set(old.self_hidden_players)
            STATE.global_page_index = old.global_page_index
            STATE.global_page_started_at = old.global_page_started_at
    else:
        load_sessions_from_disk()

    ok, msg = load_config_from_disk(create_if_missing=True)
    if not ok:
        server.logger.error(f'[NoticeBoard] {msg}')
    else:
        server.logger.info(f'[NoticeBoard] {msg} ({STATE.config_path})')

    if hasattr(server, 'register_info_filter') and MCDRInfoFilter is not object:
        server.register_info_filter(BoardInfoFilter())
    else:
        server.logger.warning('[NoticeBoard] 当前 MCDR 版本过低（< 2.13.0），无法自动隐藏控制台回显，建议升级 MCDR 或调大 refresh_interval。')

    server.register_help_message('!!board', '管理 NoticeBoard 计分栏公告栏 (别名: !!ann)')
    server.register_command(build_command_tree('!!board'))
    server.register_command(build_command_tree('!!ann'))

    STATE.stop_event.clear()
    STATE.wake_event.clear()
    STATE.worker_thread = threading.Thread(
        target=ticker_loop,
        args=(server,),
        name='NoticeBoard-Ticker',
        daemon=True,
    )
    STATE.worker_thread.start()

    if server.is_server_startup() and not STATE.online_players:
        query_online_players(server)


def on_unload(server: PluginServerInterface) -> None:
    STATE.stop_event.set()
    STATE.wake_event.set()
    if STATE.worker_thread is not None and STATE.worker_thread.is_alive():
        STATE.worker_thread.join(timeout=2.5)
    with STATE.lock:
        save_sessions_locked()
        cleanup_minecraft_scoreboard(server)


def on_server_startup(server: PluginServerInterface) -> None:
    with STATE.lock:
        STATE.online_players.clear()
        STATE.player_sessions.clear()
        STATE.created_objs.clear()
        STATE.created_teams.clear()
        STATE.obj_cache.clear()
        STATE.active_global_obj = None
        STATE.active_team_objs.clear()
        STATE.player_team.clear()
        STATE.global_page_index = 0
        STATE.global_page_started_at = time.time()
        STATE.per_player_rot.clear()
        save_sessions_locked()
    STATE.wake_event.set()


def on_server_stop(server: PluginServerInterface, server_return_code: int) -> None:
    with STATE.lock:
        STATE.online_players.clear()
        STATE.player_sessions.clear()
        STATE.created_objs.clear()
        STATE.created_teams.clear()
        STATE.obj_cache.clear()
        STATE.active_global_obj = None
        STATE.active_team_objs.clear()
        STATE.player_team.clear()
        save_sessions_locked()


def on_player_joined(server: PluginServerInterface, player: str, info: Info) -> None:
    with STATE.lock:
        STATE.online_players.add(player)
    ensure_player_session(server, player, reset_join=True)
    STATE.wake_event.set()


def on_player_left(server: PluginServerInterface, player: str) -> None:
    with STATE.lock:
        STATE.online_players.discard(player)
        STATE.player_sessions.pop(player, None)
        STATE.player_team.pop(player, None)
        STATE.per_player_rot.pop(player.lower(), None)
        save_sessions_locked()
    STATE.wake_event.set()


def on_info(server: PluginServerInterface, info: Info) -> None:
    if info.is_user:
        return
    content = info.content or ''

    m_uuid = re.search(r'UUID of player (\S+) is ([0-9a-fA-F-]+)', content)
    if m_uuid:
        pname, puuid = m_uuid.group(1), m_uuid.group(2)
        with STATE.lock:
            STATE.uuid_cache[pname.lower()] = puuid

    if time.time() <= STATE.list_pending_until and 'players online:' in content:
        if parse_list_output(server, content):
            STATE.list_pending_until = 0.0

    pending = STATE.lp_pending
    if pending is not None and not pending['event'].is_set():
        low = content.lower()
        if not pending['saw_header']:
            if pending['player'] in low and pending['node'] in low and 'permission' in low:
                pending['saw_header'] = True
                m_inline = re.search(r':\s*(true|false|undefined)\s*$', low)
                if m_inline:
                    pending['result'] = (m_inline.group(1) == 'true')
                    pending['event'].set()
        else:
            m_res = re.search(r'(?:result|结果)\s*:\s*(true|false|undefined)\b', low)
            if not m_res:
                m_res = re.search(r':\s*(true|false|undefined)\s*$', low)
            if m_res:
                pending['result'] = (m_res.group(1) == 'true')
                pending['event'].set()
            elif 'unknown command' in low or '未知的命令' in low:
                pending['result'] = False
                pending['event'].set()