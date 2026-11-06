"""Offline smoke checks run inside the packaged executable."""

import json
import queue
import time
import traceback
from pathlib import Path


def run(destination):
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    report = {'ok': False, 'checks': []}
    try:
        from openpyxl import load_workbook
        from playwright.sync_api import sync_playwright
        from collector import APP_HOME, App, Collector, ENDPOINT, FanStore, HOVER_SCRIPT

        report['runtime_home'] = str(APP_HOME)
        assert APP_HOME.is_absolute()
        store = FanStore(destination / 'records')
        assert store.root.is_absolute()
        url = f'https://www.douyin.com{ENDPOINT}?sec_user_id=package-fixture&max_time=0'
        store.accept(url, {'status_code': 0, 'has_more': False, 'followers': [
            {'uid': '1234567890123456789', 'nickname': '=literal', 'follower_count': 10}]})
        recovered = FanStore(destination / 'records')
        recovered.open('package-fixture')
        assert recovered.counts() == {'history': 1, 'session': 0, 'new': 0, 'total': 1}
        recovered.accept(url, {'status_code': 0, 'has_more': False, 'followers': [
            {'uid': '2', 'nickname': '测试账号', 'follower_count': 20}]})
        assert recovered.counts() == {'history': 1, 'session': 1, 'new': 1, 'total': 2}
        sheet = load_workbook(recovered.export()).active
        assert sheet['C6'].value == 20 and sheet['B7'].data_type == 's'
        assert sheet['I7'].value == '1234567890123456789'
        report['checks'].append('history/session counters, disk recovery and Excel export')

        collector = Collector(queue.Queue(), queue.Queue(), destination / 'browser-records')
        responses = 0

        def route_request(route):
            nonlocal responses
            if ENDPOINT in route.request.url:
                responses += 1
                route.fulfill(json={'status_code': 0, 'has_more': responses < 2,
                                    'followers': [{'uid': str(responses), 'nickname': '测试', 'follower_count': responses}]})
            else:
                route.fulfill(content_type='text/html', body='''<!doctype html><meta charset="utf-8">
                    <div>粉丝<div id="list" style="height:200px;width:350px;overflow-y:auto">
                    <div style="height:1000px"><a href="/user/test">回关 移除</a></div></div></div>
                    <script>let n=0;list.addEventListener('scroll',()=>{
                    fetch('/aweme/v1/web/user/follower/list/?sec_user_id=package-fixture&max_time='+(n++))
                    .then(()=>list.firstElementChild.style.height=(1000+n*500)+'px');});</script>''')

        with sync_playwright() as playwright:
            context = playwright.chromium.launch_persistent_context(
                str(destination / 'test-profile'), channel='msedge', headless=True)
            context.route('**/*', route_request)
            context.add_init_script(HOVER_SCRIPT)
            context.on('request', collector.on_request)
            context.on('requestfinished', collector.on_finished)
            context.on('requestfailed', collector.on_failed)
            collector.context = context
            page = context.pages[0]
            page.goto('https://www.douyin.com/')
            collector.start()
            for _ in range(150):
                collector.scroll_tick()
                page.wait_for_timeout(20)
                if collector.store.complete:
                    break
            assert collector.store.complete and len(collector.store.users) == 2
            assert list(collector.store.directory.glob('*.xlsx'))
            context.close()
        report['checks'].append('bundled Playwright driver, Edge launch, offline scrolling, network capture and auto export')

        app = App(destination / 'gui-records')
        assert all(variable.get() == '0' for variable in app.count_values.values())
        app.events.put(('count', {'history': 3506, 'session': 20, 'new': 2, 'total': 3508}))
        app.poll()
        assert app.count_values['history'].get() == '3,506'
        assert app.count_values['session'].get() == '20'
        app.root.geometry('980x720')
        app.root.update()
        for widget in [*app.action_buttons, app.import_button, app.status_label]:
            assert widget.winfo_ismapped()
            assert widget.winfo_y() + widget.winfo_height() <= widget.master.winfo_height()
        app.root.after(200, app.close)
        app.root.mainloop()
        assert not app.worker.is_alive()
        report['checks'].append('Tk interface startup, empty initial counts and graceful shutdown')
        report['ok'] = True
    except Exception:
        report['error'] = traceback.format_exc()
    (destination / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    if not report['ok']:
        raise SystemExit(1)
