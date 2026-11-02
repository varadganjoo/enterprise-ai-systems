"""Render every workspace on desktop/mobile. Install requirements-dev.txt and Chromium first."""
from pathlib import Path
import subprocess
import sys
import time
from urllib.error import URLError
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def main():
    output = ROOT/'artifacts'
    output.mkdir(exist_ok=True)
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for number in range(10):
                port = 18000 + number
                # Do not test an unrelated server or kill a process we did not start.
                import socket
                with socket.socket() as probe:
                    assert probe.connect_ex(('127.0.0.1', port)) != 0, f'Port {port} is occupied'
                with (output/f'{number:02}-server.log').open('w') as log:
                    server = subprocess.Popen([sys.executable, str(ROOT/'run.py'), str(number), '--port', str(port)],
                                              cwd=ROOT, stdout=log, stderr=log)
                    try:
                        for attempt in range(100):
                            assert server.poll() is None, f'Application {number} exited; see {log.name}'
                            try:
                                with urlopen(f'http://127.0.0.1:{port}/', timeout=1):
                                    break
                            except (URLError, TimeoutError):
                                time.sleep(.1)
                        else:
                            raise AssertionError(f'Application {number} did not start')
                        page = browser.new_page()
                        errors = []
                        page.on('pageerror', lambda error: errors.append(str(error)))
                        for width in (1440, 390):
                            page.set_viewport_size({'width': width, 'height': 1000})
                            page.goto(f'http://127.0.0.1:{port}/')
                            page.wait_for_load_state('networkidle')
                            assert page.locator('h1').count() == 1
                            assert page.locator('nav select').count() == 1
                            assert page.locator('nav select option').count() == 10
                            assert page.locator('nav select').input_value() == str(number)
                            assert page.request.get(f'http://127.0.0.1:{port}/suite/workspace.css').ok
                            page.screenshot(path=str(output/f'{number:02}-{width}.png'), full_page=True)
                            overflow = page.evaluate("Array.from(document.querySelectorAll('body *')).filter(el => el.getBoundingClientRect().right > innerWidth + 1).slice(0,8).map(el => el.tagName + '.' + el.className)")
                            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), f'Overflow: {number}/{width}: {overflow}'
                            page.keyboard.press('Tab')
                            assert page.locator(':focus').count() == 1
                        assert not errors, errors
                        if number:
                            endpoints = ['', 'ask', 'extract', 'run', 'query', 'route', 'chat', 'audit', 'cases', 'brief']
                            buttons = ['', '#submit', '#extractBtn', '#runBtn', '#submit-btn', '#route-btn', '#send-btn', '#submit', '#openBtn', '#submit']
                            marker = 'Simulated service failure <img src=x onerror=alert(1)>'
                            dialogs = []
                            page.on('dialog', lambda dialog: (dialogs.append(dialog.message), dialog.dismiss()))
                            page.route(f'**/{endpoints[number]}', lambda route: route.fulfill(status=503, json={'detail': marker}))
                            page.locator(buttons[number]).click()
                            expect(page.locator(buttons[number])).to_be_enabled()
                            if number == 3:
                                assert dialogs and marker in dialogs[0]
                            else:
                                expect(page.get_by_text(marker, exact=False).first).to_be_visible()
                            assert page.locator('img[src="x"]').count() == 0
                            assert not errors, errors
                        page.close()
                        print(f'PASS workspace {number}: desktop, mobile, assets, keyboard, JavaScript, service failure', flush=True)
                    finally:
                        server.terminate()
                        server.wait(timeout=10)
        finally:
            browser.close()


if __name__ == '__main__':
    main()
