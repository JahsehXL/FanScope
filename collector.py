"""Collect follower responses from a user-operated Douyin browser session."""

import argparse
import base64
import hashlib
import json
import os
import queue
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parent
APP_HOME = Path(os.environ.get('FANSCOPE_HOME', str(
    Path(os.environ.get('LOCALAPPDATA', str(Path.home() / 'AppData' / 'Local'))) / 'FanScope')))
APP_VERSION = '1.3.0'
ENDPOINT = '/aweme/v1/web/user/follower/list/'
DEFAULT_SCROLL_INTERVAL = 0.1
MIN_SCROLL_INTERVAL = 0.05
HEADERS = ['排名', '昵称', '粉丝数', '抖音号', '关注数', '作品数', '获赞数', '备注名', '用户UID', '主页链接', '个人简介']
USER_FIELDS = ('uid', 'sec_uid', 'nickname', 'unique_id', 'short_id', 'follower_count',
               'following_count', 'aweme_count', 'total_favorited', 'remark_name', 'signature')
COUNT_FIELDS = ('follower_count', 'following_count', 'aweme_count', 'total_favorited')


def normalize_user(user):
    if not isinstance(user, dict) or not user.get('uid'):
        raise ValueError('粉丝记录缺少 UID，已暂停。')
    result = {key: user.get(key) for key in USER_FIELDS}
    for key in COUNT_FIELDS:
        value = result[key]
        if value is not None and (type(value) is not int or value < 0):
            raise ValueError('粉丝记录包含无效数量，已暂停。')
    for key in set(USER_FIELDS) - set(COUNT_FIELDS):
        value = result[key]
        text = '' if value is None else str(value)
        result[key] = ''.join(char for char in text if char in '\n\r\t' or ord(char) >= 32)[:32767]
    return result

# The last element hovered in the page gives a reliable starting point for
# finding the list's scroll container, even after focus moves to the desktop UI.
HOVER_SCRIPT = """document.addEventListener('mousemove', event => {
    window.__fansHoverElement = event.target;
}, {passive: true});"""
FIND_SCROLL = """() => {
    const scrollable = element => {
        const rect = element.getBoundingClientRect();
        const style = getComputedStyle(element);
        return element !== document.body && element !== document.documentElement &&
            rect.width > 150 && rect.height > 100 && rect.top < innerHeight &&
            rect.bottom > 0 && rect.left < innerWidth && rect.right > 0 &&
            /auto|scroll/.test(style.overflowY) && element.scrollHeight > element.clientHeight + 4;
    };
    const candidates = [...document.querySelectorAll('*')].filter(scrollable).filter(el =>
        /回关|移除/.test(el.innerText) &&
        (el.querySelector('a[href*="/user/"]') || /粉丝/.test(el.parentElement.innerText)));
    if (candidates.length === 1) { window.__fansScroller = candidates[0]; return true; }
    let element = window.__fansHoverElement;
    while (element && element !== document.body) {
        if (scrollable(element)) { window.__fansScroller = element; return true; }
        element = element.parentElement;
    }
    return false;
}"""
SCROLL_ONCE = """() => {
    const el = window.__fansScroller;
    if (!el || !el.isConnected) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 || rect.height === 0) return false;
    el.scrollTo({top: el.scrollHeight, behavior: 'instant'});
    return true;
}"""
CHECK_INTERRUPTION = """() => {
    const visible = el => {
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0 && getComputedStyle(el).visibility !== 'hidden';
    };
    const captcha = [...document.querySelectorAll(
        'iframe[src*="captcha"], [id*="captcha_container"], [class*="captcha_verify"], [data-e2e="captcha"]')].some(visible);
    if (captcha) return '检测到验证页面，请在浏览器手动完成后继续。';
    const notices = [...document.querySelectorAll('[role="alert"], [role="dialog"]')]
        .filter(visible).map(el => el.innerText || '').join(' ');
    if (/操作太频繁|操作频繁，请|访问过于频繁|访问受限|请完成下方验证|请拖动滑块/.test(notices))
        return '检测到访问限制或验证提示，请检查浏览器后继续。';
    return '';
}"""


def atomic_json(path, data):
    temporary = path.with_suffix(path.suffix + '.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(data, stream, ensure_ascii=False, indent=2)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temporary, path)


def identify_request(url):
    parsed = urlsplit(url)
    if parsed.path != ENDPOINT:
        return None
    query = parse_qs(parsed.query)
    owner = (query.get('sec_user_id') or query.get('user_id') or [''])[0]
    # A missing owner must not combine unrelated accounts in one data set.
    if not owner:
        raise ValueError('粉丝请求缺少账号标识，已暂停保存，请检查接口是否变化。')
    return owner, {key: query[key][0] for key in ('max_time', 'min_time', 'source_type', 'count', 'offset') if key in query}


class FanStore:
    def __init__(self, root):
        self.root = Path(root)
        self.directory = None
        self.owner = None
        self.users = {}
        self.batches = 0
        self.complete = False
        self.last_cursor = None
        self.started_at_first_page = False
        self.history_count = 0
        self.session_uids = set()

    def open(self, owner):
        if owner == self.owner:
            return
        key = hashlib.sha256(owner.encode()).hexdigest()[:16]
        directory = self.root / key
        directory.mkdir(parents=True, exist_ok=True)
        recovered = FanStore(self.root)
        for path in sorted(directory.glob('batch-*.json')):
            try:
                record = json.loads(path.read_text(encoding='utf-8'))
                recovered.apply(record)
            except (ValueError, KeyError, TypeError) as error:
                raise ValueError(f'保存的批次 {path.name} 无法读取，请检查本机数据目录。') from error
        self.owner = owner
        self.directory = directory
        self.users = recovered.users
        self.batches = recovered.batches
        self.last_cursor = recovered.last_cursor
        self.history_count = 0
        self.session_uids = set()
        self.history_count = len(self.users)
        # A previous session's last page does not complete this session.
        self.complete = False
        self.started_at_first_page = False

    def counts(self):
        return {'history': self.history_count, 'session': len(self.session_uids),
                'new': len(self.users) - self.history_count, 'total': len(self.users)}

    def apply(self, record):
        body = record['response']
        if not isinstance(body.get('followers'), (list, type(None))):
            raise ValueError('保存的粉丝列表格式无效。')
        self.batches += 1
        for user in body['followers'] or []:
            normalized = normalize_user(user)
            self.users[normalized['uid']] = normalized
        if record['request'].get('max_time') == '0':
            self.started_at_first_page = True
        self.last_cursor = body.get('min_time')
        if record['request'].get('max_time') == '0':
            self.complete = False
        self.complete = self.complete or body.get('has_more') is False

    def accept(self, url, body):
        identity = identify_request(url)
        if identity is None:
            return False
        if not isinstance(body, dict) or body.get('status_code') != 0:
            raise ValueError('粉丝接口返回异常状态，请在浏览器检查登录或验证。')
        if 'followers' not in body or not isinstance(body['followers'], (list, type(None))):
            raise ValueError('响应缺少 followers 列表，已暂停，请检查接口是否变化。')
        followers = [normalize_user(user) for user in body['followers'] or []]
        if type(body.get('has_more')) is not bool:
            raise ValueError('响应缺少有效分页标记，已暂停。')
        owner, query = identity
        self.open(owner)
        response = {key: body.get(key) for key in ('status_code', 'has_more', 'min_time', 'max_time')}
        response['followers'] = followers
        record = {'schema_version': 1, 'captured_at': datetime.now().astimezone().isoformat(),
                  'request': query, 'response': response}
        atomic_json(self.directory / f'batch-{self.batches + 1:06d}.json', record)
        self.apply(record)
        self.session_uids.update(str(user['uid']) for user in body['followers'] or [])
        return True

    def export(self, scope='history'):
        from openpyxl import Workbook
        from openpyxl.styles import Alignment, Font, PatternFill
        from openpyxl.worksheet.table import Table, TableStyleInfo

        if scope not in ('history', 'session'):
            raise ValueError('未知导出范围。')
        selected = self.users if scope == 'history' else {uid: self.users[uid] for uid in self.session_uids}
        if not selected:
            raise ValueError('还没有采集到账号，请先打开粉丝列表。')
        users = sorted(selected.values(), key=lambda user: (
            user.get('follower_count') is None, -(user.get('follower_count') or 0)))
        workbook = Workbook()
        sheet = workbook.active
        sheet.title = '粉丝量排名'
        scope_label = '本次采集' if scope == 'session' else '历史合并'
        sheet.append([f'FanScope · {scope_label} · 按粉丝数降序'])
        sheet.append([f'共 {len(users)} 人；同粉丝数并列排名；导出时间 {datetime.now():%Y-%m-%d %H:%M:%S}'])
        sheet.append([f'范围 {scope_label}；本次读取 {len(self.session_uids)} 人；历史 {self.history_count} 人；历史合并可能保留已取关账号。'])
        sheet.append([f'来源为 follower/list 响应；本次记录首批 {self.started_at_first_page}、末页 {self.complete}；实际返回数量可能少于页面总数。'])
        sheet.append(HEADERS)
        rank = None
        for index, user in enumerate(users):
            count = user.get('follower_count')
            if index == 0 or count != users[index - 1].get('follower_count'):
                rank = index + 1 if count is not None else None
            row = [rank, user.get('nickname', ''), count,
                   str(user.get('unique_id') or user.get('short_id') or ''),
                   user.get('following_count'), user.get('aweme_count'), user.get('total_favorited'),
                   user.get('remark_name') or '', str(user['uid']),
                   f"https://www.douyin.com/user/{user['sec_uid']}" if user.get('sec_uid') else '',
                   user.get('signature') or '']
            sheet.append(row)
            row_number = index + 6
            for column in range(1, len(HEADERS) + 1):
                cell = sheet.cell(row_number, column)
                # Account names and signatures are untrusted literal text.
                if isinstance(cell.value, str):
                    cell.data_type = 's'
                cell.alignment = Alignment(vertical='center')
            for column in (1, 3, 5, 6, 7):
                sheet.cell(row_number, column).number_format = '#,##0'
            if row[9]:
                sheet.cell(row_number, 10).hyperlink = row[9]
                sheet.cell(row_number, 10).style = 'Hyperlink'
        for cell in sheet[5]:
            cell.font = Font(name='Microsoft YaHei', bold=True, color='FFFFFF')
            cell.fill = PatternFill('solid', fgColor='263B59')
            cell.alignment = Alignment(horizontal='center')
        widths = {'A': 10, 'B': 32, 'C': 14, 'D': 25, 'E': 13, 'F': 13, 'G': 16, 'H': 25, 'I': 25, 'J': 50, 'K': 65}
        for column, width in widths.items():
            sheet.column_dimensions[column].width = width
        sheet.freeze_panes = 'C6'
        sheet.sheet_view.showGridLines = False
        table = Table(displayName='FansRanking', ref=f'A5:K{sheet.max_row}')
        table.tableStyleInfo = TableStyleInfo(name='TableStyleMedium2', showRowStripes=True)
        sheet.add_table(table)
        target = self.directory / f'FanScope-{scope_label}-{datetime.now():%Y%m%d-%H%M%S-%f}.xlsx'
        temporary = target.with_suffix('.tmp.xlsx')
        workbook.save(temporary)
        os.replace(temporary, target)
        return target


def import_har(path, store, scope='history'):
    previous_owner = None
    imported = 0
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    for entry in data['log']['entries']:
        request = entry.get('request', {})
        if request.get('method') != 'GET' or urlsplit(request.get('url', '')).path != ENDPOINT:
            continue
        owner, _ = identify_request(request['url'])
        if previous_owner is not None and previous_owner != owner:
            raise ValueError('HAR 包含多个目标账号，请按账号分开导入。已读取的批次已保存。')
        previous_owner = owner
        content = entry.get('response', {}).get('content', {})
        if not content.get('text'):
            raise ValueError('HAR 中有粉丝响应缺失，请重新导出包含响应内容的文件。')
        text = content['text']
        if content.get('encoding') == 'base64':
            text = base64.b64decode(text).decode('utf-8')
        store.accept(request['url'], json.loads(text))
        imported += 1
    if not imported:
        raise ValueError('HAR 中未找到粉丝列表请求。')
    return store.export(scope)


class Collector:
    def __init__(self, commands, events, data_root=APP_HOME / 'data'):
        self.commands = commands
        self.events = events
        self.store = FanStore(data_root)
        self.context = None
        self.page = None
        self.running = False
        self.last_response = time.monotonic()
        self.next_scroll = 0
        self.scroll_interval = DEFAULT_SCROLL_INTERVAL
        self.pending = set()
        self.export_scope = 'session'
        self.next_interruption_check = 0

    def report(self, text):
        self.events.put(('log', text))

    def on_request(self, request):
        parsed = urlsplit(request.url)
        if (parsed.path != ENDPOINT or request.method != 'GET' or
                not (parsed.hostname == 'douyin.com' or (parsed.hostname or '').endswith('.douyin.com'))):
            return
        self.pending.add(request)

    def on_finished(self, request):
        if request not in self.pending:
            return
        self.pending.remove(request)
        try:
            response = request.response()
            if response.status != 200:
                raise ValueError(f'粉丝请求 HTTP {response.status}，请检查浏览器。')
            self.store.accept(response.url, response.json())
            self.last_response = time.monotonic()
            # Give the page a short turn to append the received batch before
            # scrolling to the new bottom. Preserve the user's minimum interval.
            self.next_scroll = max(self.next_scroll, self.last_response + 0.03)
            self.events.put(('count', self.store.counts()))
            self.report(f'已保存 {self.store.batches} 批，本次读取 {len(self.store.session_uids)} 人，合计 {len(self.store.users)} 人')
            if self.store.complete and not self.pending:
                self.running = False
                target = self.store.export(self.export_scope)
                self.report(f'接口已返回末页，已导出 {target}')
                self.events.put(('exported', str(target)))
        except Exception as error:
            self.running = False
            self.report(f'已暂停：{error}')

    def on_failed(self, request):
        if request in self.pending:
            self.pending.remove(request)
            self.running = False
            self.report('粉丝请求失败，已暂停。请检查网络后继续。')

    def open_browser(self, playwright):
        if self.context:
            self.report('浏览器已经打开，请在该窗口中操作。')
            return
        self.context = playwright.chromium.launch_persistent_context(
            str(APP_HOME / 'browser-profile'), channel='msedge', headless=False,
            no_viewport=True, args=['--start-maximized'])
        self.context.add_init_script(HOVER_SCRIPT)
        self.context.on('request', self.on_request)
        self.context.on('requestfinished', self.on_finished)
        self.context.on('requestfailed', self.on_failed)
        self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
        self.page.goto('https://www.douyin.com/', wait_until='domcontentloaded', timeout=60000)
        self.report('请登录，进入目标主页并打开粉丝列表，然后点击“开始／继续”。定位失败时，把鼠标移到列表内一次再试。')

    def start(self):
        if not self.context:
            raise ValueError('请先打开采集浏览器。')
        candidates = [page for page in self.context.pages if urlsplit(page.url).hostname in ('www.douyin.com', 'douyin.com')]
        candidates = [page for page in candidates if page.evaluate(FIND_SCROLL)]
        if len(candidates) != 1:
            raise ValueError('请在一个抖音页面打开粉丝列表，将鼠标移到列表内部后再开始。')
        self.page = candidates[0]
        self.running = True
        self.last_response = time.monotonic()
        self.next_scroll = time.monotonic()
        self.report(f'已开始滚动至列表底部，最短间隔 {self.scroll_interval:g} 秒。鼠标可以移开。')

    def scroll_tick(self):
        if not self.running:
            return
        now = time.monotonic()
        if now >= self.next_interruption_check:
            self.next_interruption_check = now + 1
            interruption = self.page.evaluate(CHECK_INTERRUPTION)
            if interruption:
                raise ValueError(interruption)
        if now - self.last_response > 60:
            raise ValueError('60 秒没有新响应，已暂停。请检查网络、登录或验证，再点击继续。')
        if self.pending or now < self.next_scroll:
            return
        if not self.page.evaluate(SCROLL_ONCE):
            raise ValueError('粉丝列表已关闭或页面变化，请重新打开列表后继续。')
        self.next_scroll = time.monotonic() + self.scroll_interval

    def run(self):
        from playwright.sync_api import sync_playwright
        try:
            with sync_playwright() as playwright:
                while True:
                    try:
                        command, value = self.commands.get_nowait()
                    except queue.Empty:
                        command, value = None, None
                    try:
                        if command == 'quit':
                            break
                        if command == 'open':
                            self.open_browser(playwright)
                        elif command == 'start':
                            self.start()
                        elif command == 'pause':
                            self.running = False
                            self.report('已暂停自动滚动，已保存的数据保留。')
                        elif command == 'interval':
                            if not isinstance(value, (int, float)) or not MIN_SCROLL_INTERVAL <= value <= 10:
                                raise ValueError(f'滚动间隔需要在 {MIN_SCROLL_INTERVAL:g} 到 10 秒之间。')
                            self.scroll_interval = value
                            self.report(f'滚动间隔已设置为 {value:g} 秒，请求加载时会自动等待。')
                        elif command == 'export':
                            target = self.store.export(self.export_scope)
                            self.events.put(('exported', str(target)))
                            self.report(f'已导出 {target}')
                        elif command == 'import':
                            self.running = False
                            target = import_har(value, self.store, self.export_scope)
                            self.events.put(('count', self.store.counts()))
                            self.events.put(('exported', str(target)))
                            self.report(f'HAR 已导入并导出 {target}')
                        elif command == 'scope':
                            if value not in ('history', 'session'):
                                raise ValueError('未知导出范围。')
                            self.export_scope = value
                        self.scroll_tick()
                        if self.context and self.context.pages:
                            self.context.pages[0].wait_for_timeout(20 if self.running else 100)
                        elif self.context:
                            self.running = False
                            closed_context = self.context
                            self.context = None
                            self.page = None
                            self.pending.clear()
                            try:
                                closed_context.close()
                            except Exception as error:
                                self.report(f'浏览器关闭时返回：{error}')
                            self.report('浏览器已关闭，可以重新打开后继续，已有数据会按 UID 合并。')
                        else:
                            time.sleep(0.1)
                    except Exception as error:
                        self.running = False
                        self.report(f'操作未完成：{error}')
                if self.context:
                    self.context.close()
        except Exception as error:
            self.report(f'采集线程停止：{error}')
            self.events.put(('fatal', str(error)))


class App:
    def __init__(self, data_root=APP_HOME / 'data'):
        # Tk scales point fonts automatically. Scale pixel dimensions by the same DPI.
        if sys.platform == 'win32':
            import ctypes
            try:
                ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-2))
            except AttributeError:
                ctypes.windll.user32.SetProcessDPIAware()
        self.root = tk.Tk()
        self.root.title(f'FanScope · 粉丝观测台 {APP_VERSION}')
        self.ui_scale = self.root.winfo_fpixels('1i') / 96
        p = self.px
        screen_width, screen_height = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        left, top, right, bottom = 0, 0, screen_width, screen_height
        if sys.platform == 'win32':
            from ctypes import wintypes
            work_area = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(48, 0, ctypes.byref(work_area), 0):
                left, top, right, bottom = work_area.left, work_area.top, work_area.right, work_area.bottom
        width = min(p(1160), right - left - p(40))
        height = min(p(800), bottom - top - p(64))
        self.root.geometry(f'{width}x{height}+{left + (right-left-width)//2}+{top + (bottom-top-height)//2}')
        self.root.minsize(min(p(520), width), min(p(460), height))
        background, panel = '#F5F6F8', '#FFFFFF'
        ink, muted, border = '#202534', '#6D7483', '#E4E7ED'
        accent, dark = '#E54668', '#202738'
        self.root.configure(background=background)
        icon_file = ROOT / 'assets' / 'icon-48.png'
        if icon_file.exists():
            self.app_icon = tk.PhotoImage(file=str(icon_file))
            self.root.iconphoto(True, self.app_icon)
        self.data_root = Path(data_root)
        style = ttk.Style(self.root)
        style.theme_use('clam')
        style.configure('.', font=('Microsoft YaHei UI', 10))
        style.configure('TButton', padding=(p(12), p(8)), background=panel, foreground=ink,
                        bordercolor=border, lightcolor=panel, darkcolor=panel,
                        relief='flat', focusthickness=1, focuscolor=accent)
        style.map('TButton', background=[('disabled', '#EEF0F4'), ('active', '#F0F2F6')],
                  foreground=[('disabled', '#A3A9B5')], bordercolor=[('focus', accent)])
        for name, color, hover in [('Accent', accent, '#D23557'), ('Dark', '#333D52', '#414E68')]:
            style.configure(f'{name}.TButton', background=color, foreground='white',
                            bordercolor=color, lightcolor=color, darkcolor=color,
                            font=('Microsoft YaHei UI', 10, 'bold'))
            style.map(f'{name}.TButton', background=[('disabled', '#535B6C'), ('active', hover)],
                      foreground=[('disabled', '#BCC2CC')], bordercolor=[('focus', '#FFC0CF')])
        style.configure('Small.TButton', padding=(p(10), p(6)), font=('Microsoft YaHei UI', 9))
        style.configure('TSpinbox', fieldbackground='#F7F8FA', background=panel,
                        foreground=ink, bordercolor=border, arrowsize=p(13), padding=p(6))
        style.configure('TCombobox', fieldbackground=panel, background='#F0F2F6',
                        foreground=ink, bordercolor=border, arrowsize=p(12), padding=p(6))
        style.map('TCombobox', fieldbackground=[('readonly', panel)],
                  selectbackground=[('readonly', panel)], selectforeground=[('readonly', ink)])
        style.configure('Vertical.TScrollbar', background='#CFD5DF', troughcolor=background,
                        bordercolor=background, arrowsize=p(10), relief='flat')
        self.commands = queue.Queue()
        self.events = queue.Queue()
        self.exported = None
        self.closing = False
        self.worker = threading.Thread(target=Collector(self.commands, self.events, self.data_root).run, daemon=True)
        self.worker.start()

        header = tk.Frame(self.root, background=panel, padx=p(24), pady=p(12))
        header.pack(fill='x')
        if hasattr(self, 'app_icon'):
            tk.Label(header, image=self.app_icon, background=panel).pack(side='left', padx=(0, p(12)))
        brand = tk.Frame(header, background=panel)
        brand.pack(side='left')
        tk.Label(brand, text='FanScope', background=panel, foreground=ink,
                 font=('Segoe UI', 16, 'bold')).pack(anchor='w')
        tk.Label(brand, text='粉丝观测台', background=panel, foreground=muted,
                 font=('Microsoft YaHei UI', 8)).pack(anchor='w')
        tk.Label(header, text=f'v{APP_VERSION}', background=panel, foreground=muted,
                 font=('Segoe UI', 9)).pack(side='right', padx=(p(14), 0))
        self.import_button = ttk.Button(header, text='导入 HAR', style='Small.TButton', command=self.choose_har)
        self.import_button.pack(side='right')
        ttk.Button(header, text='数据目录', style='Small.TButton', command=self.open_data).pack(side='right', padx=p(8))
        tk.Frame(self.root, height=1, background=border).pack(fill='x')

        self.status = tk.StringVar(value='准备就绪 · 请先打开采集浏览器')
        footer = tk.Frame(self.root, background=panel, padx=p(24), pady=p(9))
        footer.pack(side='bottom', fill='x')
        tk.Label(footer, text='●', background=panel, foreground='#29967E',
                 font=('Segoe UI', 10)).pack(side='left', padx=(0, p(9)))
        self.status_label = tk.Label(footer, textvariable=self.status, background=panel,
                                     foreground=muted, font=('Microsoft YaHei UI', 9), anchor='w', justify='left')
        self.status_label.pack(side='left', fill='x', expand=True)
        footer.bind('<Configure>', lambda event: self.status_label.configure(wraplength=max(p(120), event.width-p(80))))

        # A page scrollbar keeps controls reachable on short laptop screens.
        viewport = tk.Frame(self.root, background=background)
        viewport.pack(fill='both', expand=True)
        self.page = tk.Canvas(viewport, background=background, highlightthickness=0, yscrollincrement=p(24))
        self.page.pack(side='left', fill='both', expand=True)
        self.page_scroll = ttk.Scrollbar(viewport, orient='vertical', command=self.page.yview)
        self.page.configure(yscrollcommand=self.page_scroll.set)
        self.content = tk.Frame(self.page, background=background, padx=p(24), pady=p(18))
        self.content_window = self.page.create_window(0, 0, window=self.content, anchor='nw')
        self.content.columnconfigure(0, weight=1)
        self.content.rowconfigure(3, weight=1)

        title = tk.Frame(self.content, background=background)
        title.grid(row=0, column=0, sticky='ew', pady=(0, p(18)))
        tk.Label(title, text='粉丝数据工作台', background=background, foreground=ink,
                 font=('Microsoft YaHei UI', 20, 'bold')).pack(anchor='w')
        self.page_subtitle = tk.Label(title, text='采集、整理与排名，一处完成。', background=background,
                                      foreground=muted, font=('Microsoft YaHei UI', 10))
        self.page_subtitle.pack(anchor='w', pady=(p(5), 0))

        steps = tk.Frame(self.content, background='#ECEFF4', padx=p(16), pady=p(10))
        self.steps = steps
        steps.grid(row=1, column=0, sticky='ew', pady=(0, p(18)))
        for column, text in enumerate(['打开浏览器', '登录并打开粉丝列表', '开始采集与导出']):
            steps.columnconfigure(column, weight=1, uniform='steps')
            tk.Label(steps, text=f'{column+1:02}   {text}', background='#ECEFF4', foreground='#596277',
                     font=('Microsoft YaHei UI', 9), anchor='w').grid(row=0, column=column, sticky='ew')

        self.metrics = tk.Frame(self.content, background=background)
        self.metrics.grid(row=2, column=0, sticky='ew', pady=(0, p(18)))
        self.metric_cards = []
        self.metric_numbers = []
        self.count_values = {}
        for key, title, caption, color in [
                ('history', '历史已保存', '来自本机历史记录', ink),
                ('session', '本次读取', '本次收到的去重账号', ink),
                ('new', '本次新增', '此前未保存的账号', '#23846B'),
                ('total', '历史合计', '历史与本次合并去重', accent)]:
            surface = '#FFF3F6' if key == 'total' else panel
            card = tk.Frame(self.metrics, background=surface, padx=p(18), pady=p(12),
                            highlightbackground='#F5D7E0' if key == 'total' else border, highlightthickness=1)
            tk.Label(card, text=title, background=surface, foreground=muted,
                     font=('Microsoft YaHei UI', 9)).pack(anchor='w')
            self.count_values[key] = tk.StringVar(value='0')
            number = tk.Label(card, textvariable=self.count_values[key], background=surface,
                              foreground=color, font=('Segoe UI', 28, 'bold'))
            number.pack(anchor='w', pady=(p(3), 0))
            self.metric_numbers.append(number)
            tk.Label(card, text=caption, background=surface, foreground=muted,
                     font=('Microsoft YaHei UI', 8)).pack(anchor='w')
            self.metric_cards.append(card)

        self.workspace = tk.Frame(self.content, background=background)
        self.workspace.grid(row=3, column=0, sticky='nsew')
        self.workspace.columnconfigure(1, weight=1)
        self.workspace.rowconfigure(0, weight=1)
        self.controls = tk.Frame(self.workspace, background=dark, padx=p(18), pady=p(16))
        self.controls.grid(row=0, column=0, sticky='nsew', padx=(0, p(18)))
        tk.Label(self.controls, text='采集控制', background=dark, foreground='white',
                 font=('Microsoft YaHei UI', 13, 'bold')).pack(anchor='w')
        tk.Label(self.controls, text='打开粉丝列表后开始运行', background=dark, foreground='#B1BACC',
                 font=('Microsoft YaHei UI', 9)).pack(anchor='w', pady=(p(5), p(12)))
        self.action_buttons = []
        for label, action, button_style in [
                ('打开采集浏览器', lambda: self.commands.put(('open', None)), 'Dark.TButton'),
                ('开始 / 继续采集', self.start_capture, 'Accent.TButton')]:
            button = ttk.Button(self.controls, text=label, style=button_style, command=action)
            button.pack(fill='x', pady=(0, p(10)))
            self.action_buttons.append(button)
        secondary = tk.Frame(self.controls, background=dark)
        secondary.pack(fill='x', pady=(0, p(14)))
        for column, (label, command) in enumerate([('暂停采集', 'pause'), ('导出 Excel', 'export')]):
            secondary.columnconfigure(column, weight=1)
            button = ttk.Button(secondary, text=label, style='Dark.TButton',
                                command=lambda name=command: self.commands.put((name, None)))
            button.grid(row=0, column=column, sticky='ew', padx=(0, p(4)) if column == 0 else (p(4), 0))
            self.action_buttons.append(button)
        tk.Frame(self.controls, height=1, background='#3B4355').pack(fill='x', pady=(0, p(12)))
        tk.Label(self.controls, text='滚动间隔', background=dark, foreground='#DAE0EB',
                 font=('Microsoft YaHei UI', 9, 'bold')).pack(anchor='w', pady=(0, p(8)))
        speed = tk.Frame(self.controls, background=dark)
        speed.pack(fill='x')
        self.interval = tk.StringVar(value=f'{DEFAULT_SCROLL_INTERVAL:g}')
        self.speed_control = ttk.Spinbox(speed, from_=MIN_SCROLL_INTERVAL, to=10, increment=0.05, width=6,
                                          textvariable=self.interval)
        self.speed_control.pack(side='left')
        tk.Label(speed, text='秒', background=dark, foreground='#B1BACC').pack(side='left', padx=p(8))
        ttk.Button(speed, text='应用', style='Small.TButton', command=self.apply_speed).pack(side='right')
        tk.Label(self.controls, text='加载时等待 · 鼠标可移开', background=dark, foreground='#B1BACC',
                 justify='left', font=('Microsoft YaHei UI', 8)).pack(anchor='w', pady=(p(12), 0))

        self.activity = tk.Frame(self.workspace, background=panel, padx=p(20), pady=p(18),
                                 highlightbackground=border, highlightthickness=1)
        self.activity.grid(row=0, column=1, sticky='nsew')
        activity_header = tk.Frame(self.activity, background=panel)
        activity_header.pack(fill='x', pady=(0, p(14)))
        tk.Label(activity_header, text='运行记录', background=panel, foreground=ink,
                 font=('Microsoft YaHei UI', 13, 'bold')).pack(side='left')
        self.view_export_button = ttk.Button(activity_header, text='查看导出 ↗', style='Small.TButton', command=self.open_export)
        self.view_export_button.pack(side='right')
        export_options = tk.Frame(self.activity, background=panel)
        export_options.pack(fill='x', pady=(0, p(14)))
        tk.Label(export_options, text='导出范围', background=panel, foreground=muted,
                 font=('Microsoft YaHei UI', 9)).pack(side='left', padx=(0, p(10)))
        self.export_scope = tk.StringVar(value='本次采集')
        self.scope_control = ttk.Combobox(export_options, textvariable=self.export_scope,
                                          values=['本次采集', '历史合并'], state='readonly', width=10)
        self.scope_control.pack(side='left')
        self.scope_control.bind('<<ComboboxSelected>>', lambda event: self.commands.put((
            'scope', 'session' if self.export_scope.get() == '本次采集' else 'history')))
        log_frame = tk.Frame(self.activity, background='#F7F8FA', highlightbackground=border, highlightthickness=1)
        log_frame.pack(fill='both', expand=True)
        self.log = tk.Text(log_frame, wrap='word', height=6, width=24, background='#F7F8FA',
                           foreground='#444E62', relief='flat', borderwidth=0, padx=p(14), pady=p(12),
                           insertbackground=ink, selectbackground='#FBDDE5', spacing1=p(3), spacing3=p(6),
                           font=('Microsoft YaHei UI', 9))
        scrollbar = ttk.Scrollbar(log_frame, orient='vertical', command=self.log.yview)
        scrollbar.pack(side='right', fill='y')
        self.log.configure(yscrollcommand=scrollbar.set)
        self.log.pack(fill='both', expand=True)
        self.log.tag_configure('time', foreground='#8B94A5', font=('Consolas', 9))
        self.log.tag_configure('error', foreground='#CE3658')
        self.log.insert('end', 'READY  /  等待开始\n\n', 'time')
        self.log.insert('end', '01  打开采集浏览器，手动登录抖音。\n02  进入目标主页，打开粉丝列表。\n03  点击开始，每批数据将自动保存。\n')
        self.log.configure(state='disabled')
        self.layout_columns = None
        self.layout_job = None
        self.page.bind('<Configure>', self.resize_page)
        self.content.bind('<Configure>', self.resize_page)
        self.root.bind('<MouseWheel>', self.scroll_page)
        self.root.bind('<FocusIn>', self.reveal_control, add='+')
        self.root.protocol('WM_DELETE_WINDOW', self.close)
        self.root.after(150, self.poll)

    def px(self, value):
        return round(value * self.ui_scale)

    def resize_page(self, event=None):
        if self.layout_job is None:
            self.layout_job = self.root.after_idle(self.fit_page)

    def fit_page(self):
        # Keep the pending marker while Tk settles requested sizes after reflow.
        width, height = self.page.winfo_width(), self.page.winfo_height()
        if height < self.px(620):
            self.steps.grid_remove()
            self.page_subtitle.pack_forget()
        else:
            self.steps.grid()
            self.page_subtitle.pack(anchor='w', pady=(self.px(5), 0))
        columns = 2 if width < self.px(960) else 4
        stacked = width < self.px(700)
        self.workspace.columnconfigure(0, weight=1 if stacked else 0)
        self.workspace.columnconfigure(1, weight=0 if stacked else 1)
        self.workspace.rowconfigure(0, weight=0 if stacked else 1)
        self.workspace.rowconfigure(1, weight=1 if stacked else 0)
        self.controls.grid_configure(row=0, column=0, columnspan=2 if stacked else 1,
                                     padx=(0, 0 if stacked else self.px(18)),
                                     pady=(0, self.px(18) if stacked else 0))
        self.activity.grid_configure(row=1 if stacked else 0, column=0 if stacked else 1,
                                     columnspan=2 if stacked else 1)
        number_width = (width - self.px(48 + (columns-1)*12)) // columns - self.px(48)
        for label, variable in zip(self.metric_numbers, self.count_values.values()):
            size = 28
            while size > 14 and self.root.tk.call('font', 'measure', ('Segoe UI', size, 'bold'), variable.get()) > number_width:
                size -= 1
            label.configure(font=('Segoe UI', size, 'bold'))
        if columns != self.layout_columns:
            self.layout_columns = columns
            for column in range(4):
                self.metrics.columnconfigure(column, weight=1 if column < columns else 0,
                                              uniform='cards' if column < columns else '')
            for index, card in enumerate(self.metric_cards):
                card.grid(row=index // columns, column=index % columns, sticky='nsew',
                          padx=(0 if index % columns == 0 else self.px(6),
                                0 if index % columns == columns-1 else self.px(6)),
                          pady=(0, self.px(10) if columns == 2 and index < 2 else 0))
        self.page.itemconfigure(self.content_window, width=width)
        self.content.update_idletasks()
        required_height = self.content.winfo_reqheight()
        scroll_needed = required_height > height + 1
        if scroll_needed and not self.page_scroll.winfo_manager():
            self.page_scroll.pack(side='right', fill='y')
        elif not scroll_needed and self.page_scroll.winfo_manager():
            self.page_scroll.pack_forget()
        self.page.itemconfigure(self.content_window, width=width, height=max(height, required_height))
        self.page.configure(scrollregion=(0, 0, width, max(height, required_height)))
        if not scroll_needed:
            self.page.yview_moveto(0)
        self.layout_job = None
        if (width, height) != (self.page.winfo_width(), self.page.winfo_height()):
            self.resize_page()

    def scroll_page(self, event):
        if isinstance(event.widget, (tk.Text, ttk.Spinbox, ttk.Combobox)):
            return
        self.page.yview_scroll(-int(event.delta / 120), 'units')

    def reveal_control(self, event):
        widget = event.widget
        if not str(widget).startswith(str(self.content) + '.'):
            return
        y = widget.winfo_rooty() - self.content.winfo_rooty()
        top = self.page.canvasy(0)
        bottom = top + self.page.winfo_height()
        if y < top or y + widget.winfo_height() > bottom:
            self.page.yview_moveto(max(0, y - self.px(16)) / max(1, self.content.winfo_height()))

    def apply_speed(self):
        try:
            interval = float(self.interval.get())
            if not MIN_SCROLL_INTERVAL <= interval <= 10:
                raise ValueError
        except ValueError:
            messagebox.showinfo('滚动间隔', f'请输入 {MIN_SCROLL_INTERVAL:g} 到 10 之间的秒数。')
            return False
        self.commands.put(('interval', interval))
        return True

    def start_capture(self):
        if self.apply_speed():
            self.commands.put(('start', None))

    def choose_har(self):
        path = filedialog.askopenfilename(filetypes=[('HAR 文件', '*.har *.devtools'), ('所有文件', '*.*')])
        if path:
            self.commands.put(('import', path))

    def open_data(self):
        self.data_root.mkdir(parents=True, exist_ok=True)
        os.startfile(self.data_root)

    def open_export(self):
        if self.exported:
            os.startfile(self.exported)
        else:
            messagebox.showinfo('导出', '请先采集或导入数据，然后导出 Excel。')

    def poll(self):
        while not self.events.empty():
            kind, value = self.events.get_nowait()
            if kind == 'count':
                for key, variable in self.count_values.items():
                    variable.set(f'{value[key]:,}')
                self.resize_page()
                self.status.set('数据已更新 · 导出范围可选本次采集或历史合并')
            elif kind == 'exported':
                self.exported = value
                self.status.set('Excel 已导出 · 点击“查看导出”打开排名表')
            else:
                self.log.configure(state='normal')
                self.log.insert('end', f'{datetime.now():%H:%M:%S}  ', 'time')
                self.log.insert('end', f'{value}\n', 'error' if kind == 'fatal' else '')
                self.log.see('end')
                self.log.configure(state='disabled')
                if kind == 'fatal':
                    for button in self.action_buttons:
                        button.configure(state='disabled')
        if self.closing and not self.worker.is_alive():
            self.root.destroy()
            return
        self.root.after(150, self.poll)

    def close(self):
        if not self.closing:
            self.closing = True
            self.commands.put(('quit', None))
            self.status.set('正在保存并关闭采集浏览器…')


if __name__ == '__main__':
    import msvcrt

    parser = argparse.ArgumentParser()
    parser.add_argument('--import-har', type=Path)
    parser.add_argument('--data-dir', type=Path, default=APP_HOME / 'data')
    parser.add_argument('--diagnose', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.diagnose:
        from packaging_smoke import run
        run(args.diagnose)
        raise SystemExit(0)
    APP_HOME.mkdir(parents=True, exist_ok=True)
    instance_lock = (APP_HOME / '.instance.lock').open('a+b')
    instance_lock.seek(0)
    try:
        msvcrt.locking(instance_lock.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        messagebox.showinfo('抖音粉丝采集', '工具已经在运行，请切换到已打开的窗口。')
        raise SystemExit(0)
    if args.import_har:
        target = import_har(args.import_har, FanStore(args.data_dir))
        if sys.stdout is not None:
            print(target)
    else:
        App(args.data_dir).root.mainloop()
