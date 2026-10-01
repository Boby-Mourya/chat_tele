"""Read-only browser checks against a running frontend and its API.

Run with the backend Python environment (includes Playwright). Supply
AUDIT_EMAIL/AUDIT_PASSWORD or an explicit --env-file containing seed credentials.
No business records are created or updated. Reports exclude credentials.
"""
import argparse
import json
import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--base-url', default='http://127.0.0.1:5176')
    parser.add_argument('--env-file', type=Path)
    parser.add_argument('--output', type=Path, default=Path('reports/frontend-theme'))
    parser.add_argument('--widths', default='1440,1024,390,320', help='Comma-separated viewport widths')
    args = parser.parse_args()
    settings = {}
    if args.env_file:
        settings = dict(line.split('=', 1) for line in args.env_file.read_text(encoding='utf-8-sig').splitlines()
                        if '=' in line and not line.startswith('#'))
    email = os.environ.get('AUDIT_EMAIL') or settings.get('SEED_ADMIN_EMAIL', '').strip('"')
    password = os.environ.get('AUDIT_PASSWORD') or settings.get('SEED_ADMIN_PASSWORD', '').strip('"')
    if not email or not password:
        parser.error('Supply AUDIT_EMAIL/AUDIT_PASSWORD or --env-file with seed credentials.')
    args.output.mkdir(parents=True, exist_ok=True)
    results = []
    errors = []
    interaction_checks = ['shell preserved on navigation', 'visible rail focus', 'reduced motion',
                          'mobile analytics period control']
    base = args.base_url.rstrip('/')
    routes = ['/', '/agents', '/education/courses', '/education/students', '/conversations',
              '/leads', '/analytics', '/crm-workflow', '/integrations', '/deploy', '/workspace', '/help']
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        context = browser.new_context(viewport={'width': 1440, 'height': 1000}, reduced_motion='reduce')
        page = context.new_page()
        page.on('pageerror', lambda error: errors.append(str(error)))
        page.goto(base + '/login')
        page.locator('#email').fill(email)
        page.locator('#password').fill(password)
        page.get_by_role('button', name='Sign in', exact=True).click()
        page.wait_for_url(base + '/')
        for width in [int(value) for value in args.widths.split(',')]:
            page.set_viewport_size({'width': width, 'height': 1000 if width == 1440 else 844})
            for route in routes:
                page.goto(base + route, wait_until='networkidle')
                page.locator('.page-loader').wait_for(state='hidden')
                expect(page.locator('.mm-shell')).to_be_visible()
                expect(page.locator('.route-error')).to_have_count(0)
                info = page.evaluate('''() => {
                  const theme = getComputedStyle(document.querySelector('.mm-shell'));
                  return {
                    overflow: document.documentElement.scrollWidth > innerWidth + 1,
                    primary: theme.getPropertyValue('--blue').trim(),
                    ink: theme.getPropertyValue('--ink').trim(),
                    crmBrand: theme.getPropertyValue('--brand').trim(),
                    font: theme.fontFamily,
                    colorsDefined: ['--success','--warning','--danger','--surface-subtle','--text-muted']
                      .every(name => theme.getPropertyValue(name).trim().length > 0)
                  };
                }''')
                assert not info['overflow'], (route, width, 'document overflow')
                assert info['colorsDefined'], (route, 'missing shared colors')
                assert info['crmBrand'] == info['primary'], (route, 'inconsistent brand aliases')
                assert 'Academy Sans' in info['font'], (route, 'inconsistent font')
                if route == '/analytics':
                    expect(page.get_by_label('Analytics period')).to_be_visible()
                results.append({'route': route, 'width': width, **info})
            print(f'Checked {len(routes)} routes at {width}px', flush=True)
            (args.output / 'audit.json').write_text(json.dumps({'pages': results, 'browserErrors': errors}, indent=2), encoding='utf-8')

        # Client-side navigation must preserve the shell while loading a page.
        page.set_viewport_size({'width': 1440, 'height': 1000})
        page.goto(base + '/', wait_until='networkidle')
        page.evaluate('window.auditShell = document.querySelector(".mm-shell")')
        sidebar = page.get_by_role('complementary', name='Primary navigation')
        sidebar.get_by_role('link', name='Analytics', exact=True).click()
        expect(page.get_by_label('Analytics period')).to_be_visible()
        assert page.evaluate('window.auditShell === document.querySelector(".mm-shell")')
        link = sidebar.get_by_role('link', name='Agents', exact=True)
        page.keyboard.press('Tab')  # Establish keyboard modality for :focus-visible.
        link.focus()
        assert link.evaluate('e => e.matches(":focus-visible")')
        assert link.evaluate('e => getComputedStyle(e).outlineColor') == 'rgb(255, 255, 255)'
        button = page.get_by_role('button', name='Export', exact=True)
        assert button.evaluate('e => parseFloat(getComputedStyle(e).transitionDuration)') < 0.001
        page.screenshot(path=str(args.output / 'analytics-desktop.png'), full_page=True)
        page.set_viewport_size({'width': 390, 'height': 844})
        page.screenshot(path=str(args.output / 'analytics-mobile.png'), full_page=True)
        if page.locator('script[src*="/assets/"]').count():
            # A missing deploy chunk must leave navigation usable and recover
            # when another route is opened. Use an isolated browser context.
            failure_context = browser.new_context(storage_state=context.storage_state(), viewport={'width': 1440, 'height': 1000})
            failure_page = failure_context.new_page()
            failure_page.route('**/assets/AnalyticsPage-*.js', lambda route: route.abort())
            failure_page.goto(base + '/', wait_until='networkidle')
            failure_sidebar = failure_page.get_by_role('complementary', name='Primary navigation')
            failure_sidebar.get_by_role('link', name='Analytics', exact=True).click()
            expect(failure_page.locator('.route-error')).to_be_visible()
            expect(failure_sidebar).to_be_visible()
            failure_sidebar.get_by_role('link', name='Agents', exact=True).click()
            expect(failure_page.get_by_role('heading', name='AI agents', exact=True)).to_be_visible()
            expect(failure_page.locator('.route-error')).to_have_count(0)
            failure_context.close()
            interaction_checks.append('navigation recovers after a failed production chunk')
        assert not errors, errors
        browser.close()
    (args.output / 'audit.json').write_text(json.dumps({'pages': results, 'browserErrors': errors,
        'interactionChecks': interaction_checks}, indent=2), encoding='utf-8')
    print(f'Passed {len(results)} page checks and {len(interaction_checks)} interaction checks.', flush=True)


if __name__ == '__main__':
    main()
