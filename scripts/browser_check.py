"""Exercise the actual browser against a disposable database, never personal data."""
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / 'test-results'
ARTIFACTS.mkdir(exist_ok=True)
DATABASE = ARTIFACTS / f'browser-{uuid4().hex}.db'
URL = 'http://127.0.0.1:8001'
env = {**os.environ, 'DATABASE_URL':f'sqlite:///{DATABASE.as_posix()}', 'DEMO_DATA':'true', 'GEMINI_API_KEY':''}
log = (ARTIFACTS / 'browser-server.log').open('w')
server = subprocess.Popen([sys.executable,'-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8001'], cwd=ROOT, env=env, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)

try:
    for attempt in range(100):
        if server.poll() is not None:
            raise RuntimeError('Browser test server failed. See test-results/browser-server.log.')
        try:
            with urllib.request.urlopen(URL+'/api/config',timeout=1) as response:
                config=json.load(response)
            break
        except OSError:
            time.sleep(.15)
    else:
        raise RuntimeError('Server did not become ready.')

    with sync_playwright() as p:
        browser=p.chromium.launch(channel='msedge',headless=True)
        page=browser.new_page(viewport={'width':1440,'height':1100},device_scale_factor=1)
        errors=[]
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(URL)
        expect(page.locator('.stats-grid')).to_be_visible()
        page.wait_for_function('window.Chart && Chart.getChart("spending-chart") !== undefined')
        page.wait_for_timeout(800)
        page.screenshot(path=str(ARTIFACTS/'desktop.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')

        # Create an expense and verify persistence after reloading the browser.
        page.locator('#add-transaction').click()
        page.locator('#field-merchant').fill('Browser test coffee')
        page.locator('.item-name').fill('Iced latte')
        page.locator('.item-price').fill('0.10')
        page.get_by_role('button',name='Add item',exact=True).click()
        page.locator('.item-name').nth(1).fill('Banana bread')
        page.locator('.item-price').nth(1).fill('0.20')
        expect(page.locator('#field-amount')).to_have_value('0.30')
        page.locator('.item-price').nth(0).fill('4.50')
        page.locator('.item-price').nth(1).fill('2.75')
        expect(page.locator('#field-amount')).to_have_value('7.25')
        page.get_by_role('button',name='Add item',exact=True).click()
        page.locator('.remove-item').nth(2).click()
        expect(page.locator('.item-row')).to_have_count(2)
        page.locator('#field-category').select_option('Food & drinks')
        page.locator('#editor-dialog').screenshot(path=str(ARTIFACTS/'transaction-items-desktop.png'))
        page.locator('#save-dialog').click()
        expect(page.locator('#editor-dialog')).not_to_be_visible()
        page.goto(URL+'/#transactions')
        page.locator('#transaction-search').fill('Browser test coffee')
        expect(page.locator('.merchant-name')).to_have_text('Browser test coffee')
        page.reload()
        page.locator('#transaction-search').fill('Browser test coffee')
        expect(page.locator('.merchant-name')).to_have_text('Browser test coffee')
        page.get_by_role('button',name='Edit Browser test coffee',exact=True).click()
        expect(page.locator('.item-name').nth(0)).to_have_value('Iced latte')
        expect(page.locator('.item-price').nth(1)).to_have_value('2.75')
        page.locator('#field-amount').fill('8.75')
        page.locator('#save-dialog').click()
        expect(page.locator('#editor-dialog')).not_to_be_visible()
        expect(page.locator('.transaction-focused .amount-cell')).to_contain_text('8.75')

        # Review/correct a CSV, including a rejected row, and confirm only once.
        page.goto(URL+'/#import')
        csv=f'date,description,amount,currency\n{config["today"]},Browser import test,9.90,USD\n{config["today"]},Correct me,wrong,USD\n'
        page.locator('#upload-file').set_input_files({'name':'browser.csv','mimeType':'text/csv','buffer':csv.encode()})
        expect(page.locator('#review-form')).to_be_visible()
        rows=page.locator('#review-form tbody tr')
        expect(rows).to_have_count(2)
        rows.nth(0).locator('[name=amount]').fill('10.25')
        rows.nth(1).locator('[name=keep]').check()
        rows.nth(1).locator('[name=amount]').fill('3.50')
        page.locator('#confirm-import').click()
        expect(page.locator('#review-form')).not_to_be_visible()
        expect(page.locator('#toast')).to_contain_text('2 transactions saved')
        page.locator('#upload-file').set_input_files({'name':'browser.csv','mimeType':'text/csv','buffer':csv.replace('9.90','10.25').replace('wrong','3.50').encode()})
        expect(page.locator('#review-form')).to_be_visible()
        expect(page.locator('#review-form [name=keep]').nth(0)).not_to_be_checked()
        expect(page.locator('#review-form [name=keep]').nth(1)).not_to_be_checked()
        page.get_by_role('button',name='Discard',exact=True).click()

        # Create/update/delete a budget.
        page.goto(URL+'/#budgets')
        page.get_by_role('button',name='Create budget',exact=True).click()
        page.locator('#field-category').select_option('Education')
        page.locator('#field-amount').fill('60')
        page.locator('#save-dialog').click()
        expect(page.locator('#editor-dialog')).not_to_be_visible()
        expect(page.locator('.detail-card h3',has_text='Education')).to_be_visible()
        page.get_by_role('button',name='Edit Education budget',exact=True).click()
        page.locator('#field-amount').fill('80')
        page.locator('#save-dialog').click()
        expect(page.locator('#editor-dialog')).not_to_be_visible()
        page.get_by_role('button',name='Delete Education budget',exact=True).click()
        page.locator('#save-dialog').click()
        expect(page.locator('#editor-dialog')).not_to_be_visible()
        expect(page.locator('.detail-card h3',has_text='Education')).to_have_count(0)

        # Savings progress remains independent of the transaction ledger.
        page.goto(URL+'/#goals')
        page.get_by_role('button',name='Create goal',exact=True).click()
        page.locator('#field-name').fill('Browser savings goal')
        page.locator('#field-target').fill('500')
        page.locator('#field-saved').fill('50')
        page.locator('#save-dialog').click()
        expect(page.locator('#editor-dialog')).not_to_be_visible()
        page.get_by_role('button',name='Edit Browser savings goal',exact=True).click()
        page.locator('#field-saved').fill('100')
        page.locator('#save-dialog').click()
        expect(page.locator('#editor-dialog')).not_to_be_visible()
        goal=page.locator('.detail-card',has=page.get_by_role('heading',name='Browser savings goal',exact=True))
        expect(goal).to_contain_text('20%')

        page.goto(URL+'/#receipts')
        expect(page.locator('#choose-file')).to_be_disabled()
        expect(page.locator('.notice.warning')).to_contain_text('Gemini API key')
        page.goto(URL+'/#settings')
        expect(page.get_by_role('heading',name='Your workspace',exact=True)).to_be_visible()

        # Currency and month controls actually change dashboard queries.
        page.goto(URL+'/#dashboard')
        page.locator('[data-currency=KHR]').click()
        expect(page.locator('.stats-grid')).to_contain_text('៛')
        assert '$' not in page.locator('.stats-grid').inner_text()
        page.locator('#month-picker').fill('2020-01')
        expect(page.locator('.stats-grid')).to_be_visible()
        expect(page.locator('.stat-value').nth(1)).to_contain_text('0')
        page.locator('#month-picker').fill(config['today'][:7])
        page.locator('[data-currency=USD]').click()
        expect(page.locator('.stats-grid')).to_contain_text('$')
        with page.expect_download() as download:
            page.locator('#export-button').click()
        assert download.value.suggested_filename.endswith('-USD.csv')

        # Responsive navigation and absence of page-level horizontal scrolling.
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_timeout(800)
        page.locator('#toast').evaluate('(element) => element.hidden = true')
        page.screenshot(path=str(ARTIFACTS/'mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.locator('#menu-button').click()
        expect(page.locator('#sidebar')).to_have_class('sidebar open')
        page.locator('#sidebar a[data-view=transactions]').click()
        expect(page.locator('#transaction-search')).to_be_visible()
        page.locator('#transaction-search').fill('Browser test coffee')
        page.get_by_role('button',name='Delete Browser test coffee',exact=True).click()
        page.locator('#save-dialog').click()
        expect(page.locator('#editor-dialog')).not_to_be_visible()
        expect(page.locator('.empty-state h3')).to_have_text('A fresh start')

        # Stub only Gemini's preview, while confirming and reading real database
        # records. Old receipt dates and a different currency must stay visible.
        page.route('**/api/config',lambda route:route.fulfill(json={**config,'receipt_scanner':True}))
        receipt={'date':'2023-05-13','description':'Historical receipt browser test',
                 'merchant':'Historical receipt browser test','items':[{'name':'Groceries','price':'25000'}],
                 'amount':'25000','currency':'KHR','kind':'expense',
                 'category':'Groceries','note':'Receipt review regression test'}
        page.route('**/api/import/receipt/preview',lambda route:route.fulfill(json={
            'source':'receipt','rows':[{'row':1,'transaction':receipt,'error':None,'duplicate':False}],
            'warnings':[],'items':['Groceries: 25000 KHR']}))
        page.reload()
        page.goto(URL+'/#receipts')
        page.locator('#upload-file').set_input_files({'name':'receipt.png','mimeType':'image/png','buffer':b'stubbed-receipt'})
        expect(page.locator('#review-form')).to_be_visible()
        expect(page.locator('#receipt-merchant')).to_have_value(receipt['merchant'])
        expect(page.locator('.item-name')).to_have_value('Groceries')
        page.locator('.item-name').fill('បន្លែ')
        page.locator('.item-price').fill('26000')
        expect(page.locator('#receipt-amount')).to_have_value('25000')
        expect(page.locator('.item-total-note')).to_contain_text('differs')
        page.locator('.receipt-review').screenshot(path=str(ARTIFACTS/'receipt-items-mobile.png'))
        page.locator('#confirm-import').click()
        expect(page.locator('#import-result')).to_contain_text('1 transaction saved')
        expect(page.locator('#month-picker')).to_have_value('2023-05')
        page.locator('.saved-items summary').click()
        expect(page.locator('.saved-items')).to_contain_text('បន្លែ')
        saved_receipts=page.request.get(URL+'/api/transactions?month=2023-05&currency=KHR').json()
        assert saved_receipts[0]['items'] == [{'name':'បន្លែ','price':'26000.00'}]
        expect(page.locator('[data-currency=KHR]')).to_have_class('selected')
        expect(page.locator('.transaction-focused .merchant-name')).to_have_text(receipt['description'])
        assert 'transaction=' in page.url and 'month=2023-05' in page.url and 'currency=KHR' in page.url
        page.reload()
        expect(page.locator('.transaction-focused .merchant-name')).to_have_text(receipt['description'])
        expect(page.locator('#month-picker')).to_have_value('2023-05')

        # Re-scanning an existing receipt must not claim that a new row was saved.
        page.goto(URL+'/#receipts')
        page.locator('#upload-file').set_input_files({'name':'receipt.png','mimeType':'image/png','buffer':b'stubbed-receipt'})
        expect(page.locator('#review-form')).to_be_visible()
        page.locator('#confirm-import').click()
        expect(page.locator('#import-result')).to_contain_text('Already saved. No new transactions were added.')
        expect(page.locator('.transaction-focused .merchant-name')).to_have_text(receipt['description'])
        assert len(page.request.get(URL+'/api/transactions?month=2023-05&currency=KHR').json()) == 1

        # Create a separate funded account entirely through the account form.
        page.set_viewport_size({'width':1440,'height':1100})
        page.goto(URL+'/#accounts?currency=USD')
        page.get_by_role('button',name='Add account',exact=True).click()
        page.locator('#plan-name').fill('Reserve browser account')
        page.locator('#plan-opening_balance').fill('1000')
        page.locator('#plan-dialog-save').click()
        expect(page.locator('#plan-dialog')).not_to_be_visible()
        expect(page.get_by_role('heading',name='Reserve browser account',exact=True)).to_be_visible()
        account=next(a for a in page.request.get(URL+'/api/accounts?currency=USD').json() if a['name']=='Reserve browser account')

        # A 600 obligation with only 200 allocated must leave 800 available.
        page.goto(URL+'/#expected?currency=USD')
        page.get_by_role('button',name='Plan an expense',exact=True).click()
        page.locator('#plan-name').fill('Reserve browser tuition')
        page.locator('#plan-expected_amount').fill('600')
        page.locator('#plan-reserved_amount').fill('200')
        page.locator('#plan-account_id').select_option(str(account['id']))
        page.locator('#plan-due_date').fill('2026-11-24')
        page.locator('#plan-recurrence').select_option('monthly')
        page.locator('#plan-dialog-save').click()
        expect(page.locator('#plan-dialog')).not_to_be_visible()
        page.locator('#plan-filter-account').select_option(str(account['id']))
        expect(page.locator('.safe-to-spend>strong')).to_have_text('$800.00')
        expect(page.locator('.expected-card .plan-status')).to_have_text('Partially reserved')
        expect(page.locator('.expected-card .overdue-text')).to_be_visible()
        page.screenshot(path=str(ARTIFACTS/'expected-expenses-desktop.png'),full_page=True)
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_timeout(300)
        page.screenshot(path=str(ARTIFACTS/'expected-expenses-mobile.png'),full_page=True)
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        page.set_viewport_size({'width':1440,'height':1100})

        page.get_by_role('button',name='Add / release funds',exact=True).click()
        page.locator('#plan-amount').fill('100')
        page.locator('#plan-dialog-save').click()
        expect(page.locator('#plan-dialog')).not_to_be_visible()
        expect(page.locator('.safe-to-spend>strong')).to_have_text('$700.00')
        page.get_by_role('button',name='Add / release funds',exact=True).click()
        page.locator('#plan-action').select_option('release')
        page.locator('#plan-amount').fill('50')
        page.locator('#plan-dialog-save').click()
        expect(page.locator('#plan-dialog')).not_to_be_visible()
        expect(page.locator('.safe-to-spend>strong')).to_have_text('$750.00')
        page.get_by_role('button',name='Edit',exact=True).click()
        page.locator('#plan-expected_amount').fill('650')
        page.locator('#plan-dialog-save').click()
        expect(page.locator('#plan-dialog')).not_to_be_visible()
        expect(page.locator('.safe-to-spend>strong')).to_have_text('$750.00')
        page.get_by_role('button',name='Allocation history',exact=True).click()
        expect(page.locator('.allocation-history>div')).to_have_count(3)
        page.locator('#plan-dialog').get_by_role('button',name='Close',exact=True).click()
        page.get_by_role('button',name='Pay / link payment',exact=True).click()
        page.locator('#plan-dialog-save').click()
        expect(page.locator('#plan-dialog')).not_to_be_visible()
        expect(page.locator('.safe-to-spend>strong')).to_have_text('$350.00')
        expect(page.locator('.expected-card .plan-status')).to_have_text('Planned')
        expect(page.locator('.expected-card')).to_contain_text('$0.00 reserved')
        # Cancel the generated occurrence and stop the definition.
        page.get_by_role('button',name='Cancel',exact=True).click()
        page.locator('[name=stop_recurrence]').check()
        page.locator('#plan-dialog-save').click()
        expect(page.locator('#plan-dialog')).not_to_be_visible()
        expect(page.locator('.expected-cards .empty-state')).to_be_visible()

        # Linking a payment already in this account does not deduct it again.
        payment=page.request.post(URL+'/api/transactions',data={'merchant':'Browser existing payment','date':config['today'],
            'amount':'50','currency':'USD','account_id':account['id'],'kind':'expense','category':'Bills & utilities'}).json()
        page.get_by_role('button',name='Plan an expense',exact=True).click()
        page.locator('#plan-name').fill('Browser existing obligation')
        page.locator('#plan-expected_amount').fill('50')
        page.locator('#plan-reserved_amount').fill('50')
        page.locator('#plan-account_id').select_option(str(account['id']))
        page.locator('#plan-dialog-save').click()
        expect(page.locator('#plan-dialog')).not_to_be_visible()
        expect(page.locator('.safe-to-spend>strong')).to_have_text('$250.00')
        page.get_by_role('button',name='Pay / link payment',exact=True).click()
        page.locator('#plan-mode').select_option('link')
        page.locator('#plan-transaction_id').select_option(str(payment['id']))
        page.locator('#plan-dialog-save').click()
        expect(page.locator('#plan-dialog')).not_to_be_visible()
        expect(page.locator('.safe-to-spend>strong')).to_have_text('$300.00')

        # Receipt matching is deterministic and always requires explicit choice.
        page.get_by_role('button',name='Plan an expense',exact=True).click()
        page.locator('#plan-name').fill('Receipt reserve example')
        page.locator('#plan-expected_amount').fill('42')
        page.locator('#plan-funding_method').select_option('full')
        page.locator('#plan-account_id').select_option(str(account['id']))
        page.locator('#plan-dialog-save').click()
        expect(page.locator('#plan-dialog')).not_to_be_visible()
        expect(page.locator('.safe-to-spend>strong')).to_have_text('$258.00')
        outstanding=page.request.get(URL+f'/api/expected-expenses?currency=USD&account_id={account["id"]}').json()['expenses'][0]
        receipt={'date':config['today'],'description':'Receipt reserve example','merchant':'Receipt reserve example',
                 'account_id':account['id'],'items':[{'name':'Service payment','price':'42.00'}],
                 'amount':'42.00','currency':'USD','kind':'expense','category':'Bills & utilities','note':''}
        page.goto(URL+'/#receipts')
        page.locator('#upload-file').set_input_files({'name':'payment.png','mimeType':'image/png','buffer':b'stubbed-receipt'})
        expect(page.locator('#review-form')).to_be_visible()
        expect(page.locator('#receipt-account')).to_have_value(str(account['id']))
        expect(page.locator('#receipt-match-suggestions')).to_contain_text('Possible matches')
        expect(page.locator('#receipt-expected-id')).to_have_value('')
        page.locator('#receipt-expected-id').select_option(str(outstanding['id']))
        page.locator('#confirm-import').click()
        expect(page.locator('#import-result')).to_contain_text('expected expense completed')
        balance=page.request.get(URL+f'/api/finance-summary?currency=USD&account_id={account["id"]}').json()
        assert balance['actual_balance']=='258.00' and balance['reserved_balance']=='0.00' and balance['available_balance']=='258.00'
        assert len(page.request.get(URL+f'/api/transactions?currency=USD&account_id={account["id"]}').json())==3
        assert not errors, errors
        browser.close()
        print('Browser checks passed: desktop/mobile, existing transaction/import/budget/goal workflows; accounts; expected expense create/edit/fund/release/pay/link/cancel/history/recurrence; explicit receipt matching and balances; no JavaScript errors.')
finally:
    server.terminate()
    server.wait(timeout=10)
    log.close()
