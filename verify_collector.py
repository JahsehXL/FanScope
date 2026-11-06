"""Focused offline regression checks, including a fully routed browser fixture."""

import json
import queue
import time
from pathlib import Path

from openpyxl import load_workbook
from playwright.sync_api import sync_playwright

from collector import Collector, ENDPOINT, FanStore, HOVER_SCRIPT, MIN_SCROLL_INTERVAL


def verify_store(root):
    store = FanStore(root / 'store')
    url = f'https://www.douyin.com{ENDPOINT}?sec_user_id=fixture&max_time=0'
    first = {'status_code': 0, 'has_more': True, 'min_time': 20, 'followers': [
        {'uid': '1000000000000000001', 'nickname': '=1+1', 'follower_count': 9},
        {'uid': '2', 'nickname': '并列', 'follower_count': 9},
        {'uid': '3', 'nickname': '缺失'},
        {'uid': '4', 'nickname': '零', 'follower_count': 0}]}
    store.accept(url, first)
    store.accept(url.replace('max_time=0', 'max_time=20'), {
        'status_code': 0, 'has_more': False, 'min_time': 0,
        'followers': [{'uid': '2', 'nickname': '更新', 'follower_count': 12}]})
    loaded = FanStore(root / 'store')
    loaded.open('fixture')
    assert len(loaded.users) == 4 and loaded.batches == 2 and not loaded.complete
    assert loaded.counts() == {'history': 4, 'session': 0, 'new': 0, 'total': 4}
    loaded.accept(url, {'status_code': 0, 'has_more': False,
                        'followers': [{'uid': '2', 'nickname': '更新', 'follower_count': 12}]})
    assert loaded.counts() == {'history': 4, 'session': 1, 'new': 0, 'total': 4}
    book = load_workbook(loaded.export())
    sheet = book.active
    assert sheet['B6'].value == '更新' and sheet['C6'].value == 12
    assert sheet['B7'].value == '=1+1' and sheet['B7'].data_type == 's'
    assert sheet['I7'].value == '1000000000000000001'
    assert sheet['C8'].value == 0 and sheet['C9'].value is None and sheet['A9'].value is None
    loaded.open('another-account')
    assert loaded.users == {} and loaded.batches == 0
    assert loaded.counts() == {'history': 0, 'session': 0, 'new': 0, 'total': 0}
    print('PASS durable recovery, dedup/update, sorting, missing vs zero, literal text, UID and account isolation')


def verify_browser(root):
    collector = Collector(queue.Queue(), queue.Queue(), root / 'browser')
    collector.scroll_interval = MIN_SCROLL_INTERVAL
    responses = 0

    def route_request(route):
        nonlocal responses
        if ENDPOINT in route.request.url:
            responses += 1
            route.fulfill(json={
                'status_code': 0, 'has_more': responses < 2, 'min_time': responses,
                'followers': [{'uid': str(responses), 'nickname': f'模拟账号{responses}', 'follower_count': responses * 10}]})
        else:
            route.fulfill(content_type='text/html', body='''<!doctype html><meta charset="utf-8">
                <div>粉丝<div id="list" style="height:240px;width:400px;overflow-y:auto">
                <div style="height:1500px"><a href="/user/fixture">回关 移除</a></div></div></div>
                <script>let count=0; document.querySelector('#list').addEventListener('scroll',()=>{
                count++;fetch('/aweme/v1/web/user/follower/list/?sec_user_id=fixture&max_time='+count)
                .then(()=>{ document.querySelector('#list>div').style.height=(1500+count*500)+'px'; });
                });</script>''')

    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(root / 'test-profile'), channel='msedge', headless=True)
        context.route('**/*', route_request)
        context.add_init_script(HOVER_SCRIPT)
        context.on('request', collector.on_request)
        context.on('requestfinished', collector.on_finished)
        context.on('requestfailed', collector.on_failed)
        collector.context = context
        page = context.pages[0]
        page.goto('https://www.douyin.com/')
        # Automatic discovery and scrolling must work without ever hovering.
        collector.start()
        page.evaluate("""() => { const warning = document.createElement('div');
            warning.setAttribute('role', 'alert'); warning.id = 'fixture-warning';
            warning.textContent = '访问受限'; document.body.appendChild(warning); }""")
        try:
            collector.scroll_tick()
            raise AssertionError('Access restriction must interrupt scrolling')
        except ValueError as error:
            assert '访问限制' in str(error)
        page.locator('#fixture-warning').evaluate('(el) => el.remove()')
        collector.next_interruption_check = 0
        in_flight = object()
        collector.pending.add(in_flight)
        collector.scroll_tick()
        assert page.locator('#list').evaluate('(el) => el.scrollTop') == 0
        collector.pending.remove(in_flight)
        collector.next_scroll = time.monotonic() + 1
        collector.scroll_tick()
        assert page.locator('#list').evaluate('(el) => el.scrollTop') == 0
        collector.next_scroll = 0
        for _ in range(100):
            if collector.store.complete:
                break
            collector.scroll_tick()
            page.wait_for_timeout(20)
        assert collector.store.complete and len(collector.store.users) == 2
        assert list(collector.store.directory.glob('*.xlsx'))
        context.close()
    print('PASS automatic scroller discovery without hover, bottom scrolling, scheduled XHR capture, final-page stop and export')


if __name__ == '__main__':
    from datetime import datetime
    root = Path(__file__).parent / '.verification' / datetime.now().strftime('%Y%m%d-%H%M%S')
    root.mkdir(parents=True, exist_ok=True)
    verify_store(root)
    verify_browser(root)
