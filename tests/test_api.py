import io
from decimal import Decimal

import pytest
from PIL import Image

from backend.categorizer import suggest


def transaction(**changes):
    return {'date': '2026-11-12', 'description': 'Brown Coffee', 'amount': '4.50', 'currency': 'USD', 'kind': 'expense', 'category': 'Food & drinks', 'note': '', **changes}


def test_currency_isolation_and_exact_money(client):
    for payload in [transaction(amount='0.10'), transaction(amount='0.20'), transaction(amount='18000', currency='KHR'), transaction(amount='100', kind='income')]:
        assert client.post('/api/transactions', json=payload).status_code == 201
    usd = client.get('/api/dashboard?month=2026-11&currency=USD').json()
    khr = client.get('/api/dashboard?month=2026-11&currency=KHR').json()
    assert Decimal(usd['spending']) == Decimal('0.30')
    assert Decimal(usd['income']) == Decimal('100')
    assert Decimal(usd['net']) == Decimal('99.70')
    assert Decimal(khr['spending']) == Decimal('18000')
    assert len(usd['daily']) == 30
    assert usd['count'] == 3


@pytest.mark.parametrize('changes', [
    {'amount':'-1'}, {'amount':'0'}, {'amount':'NaN'}, {'amount':'Infinity'},
    {'amount':'1.001'}, {'amount':'1.50','currency':'KHR'}, {'currency':'EUR'},
    {'date':'2026-02-30'}, {'description':'  '}, {'category':'Unknown'},
    {'category':'Income','kind':'expense'}, {'amount':'1000000000000'},
])
def test_invalid_financial_data_is_rejected(client, changes):
    assert client.post('/api/transactions', json=transaction(**changes)).status_code == 422
    assert client.get('/api/transactions').json() == []


def test_preview_does_not_save_and_confirm_is_idempotent(client):
    data = 'date,description,amount,currency\n2026-11-12,Brown Coffee,4.50,USD\n2026-11-13,ផ្សារថ្មី,25000,KHR\n'
    preview = client.post('/api/import/csv/preview', files={'file':('test.csv',data.encode('utf-8-sig'),'text/csv')})
    assert preview.status_code == 200
    rows = preview.json()['rows']
    assert len(rows) == 2
    assert rows[0]['transaction']['category'] == 'Food & drinks'
    assert client.get('/api/transactions').json() == []
    payload = {'source':'csv','transactions':[row['transaction'] for row in rows]}
    first = client.post('/api/import/confirm',json=payload)
    assert first.json()['inserted'] == 2 and first.json()['skipped'] == 0
    repeat = client.post('/api/import/confirm',json=payload).json()
    assert repeat['inserted'] == 0 and repeat['skipped'] == 2
    assert repeat['transactions'] == first.json()['transactions']
    assert client.post('/api/import/csv/preview',files={'file':('test.csv',data,'text/csv')}).json()['rows'][0]['duplicate']
    # A corrected category does not allow reimporting the original source row.
    record = client.get('/api/transactions?currency=USD').json()[0]
    client.put(f'/api/transactions/{record["id"]}',json=transaction(category='Other'))
    assert client.post('/api/import/confirm',json=payload).json()['skipped'] == 2


def test_import_is_atomic_and_skips_duplicate_rows_in_same_batch(client):
    payload = {'source':'csv','transactions':[transaction(),transaction(amount='-1')]}
    assert client.post('/api/import/confirm',json=payload).status_code == 422
    assert client.get('/api/transactions').json() == []
    payload['transactions'] = [transaction(),transaction(amount='4.5')]
    result = client.post('/api/import/confirm',json=payload).json()
    assert result['inserted'] == 1 and result['skipped'] == 1
    assert len(result['transactions']) == 1


def test_csv_reports_bad_rows_and_requires_columns(client):
    data='date,description,amount,currency\nwrong,Test,no,USD\n2026-11-12,Other,2.50,USD\n'
    result=client.post('/api/import/csv/preview',files={'file':('test.csv',data,'text/csv')})
    assert result.status_code == 200
    assert result.json()['rows'][0]['error']
    assert not result.json()['rows'][1]['error']
    assert client.post('/api/import/csv/preview',files={'file':('test.csv','name,total\nTest,5','text/csv')}).status_code == 422
    assert client.post('/api/import/csv/preview',files={'file':('test.csv','date,description,amount,currency\n2026-11-12,Too,many,3,USD','text/csv')}).status_code == 422
    assert client.post('/api/import/csv/preview',files={'file':('test.csv',b'\xff\xfe','text/csv')}).status_code == 422


def test_transaction_edit_delete_and_filters(client):
    created=client.post('/api/transactions',json=transaction()).json()
    record_id=created['id']
    assert client.put(f'/api/transactions/{record_id}',json=transaction(description='Fresh market',category='Groceries',amount='20')).status_code == 200
    assert len(client.get('/api/transactions?search=MARKET&category=Groceries').json()) == 1
    assert client.get('/api/transactions?month=2026-10').json() == []
    assert client.delete(f'/api/transactions/{record_id}').status_code == 204
    assert client.delete(f'/api/transactions/{record_id}').status_code == 404


def test_budget_remaining_only_counts_budgeted_categories(client):
    payload={'month':'2026-11','currency':'USD','category':'Food & drinks','amount':'100'}
    assert client.post('/api/budgets',json=payload).status_code == 201
    assert client.post('/api/budgets',json={**payload,'amount':'200'}).status_code == 201
    client.post('/api/transactions',json=transaction(amount='30'))
    client.post('/api/transactions',json=transaction(amount='50',category='Shopping'))
    client.post('/api/transactions',json=transaction(amount='20000',currency='KHR'))
    d=client.get('/api/dashboard?month=2026-11&currency=USD').json()
    assert len(d['budgets']) == 1
    assert Decimal(d['budget']) == 200
    assert Decimal(d['budget_spent']) == 30
    assert Decimal(d['spending']) == 80
    assert client.post('/api/budgets',json={**payload,'month':'2026-13'}).status_code == 422
    assert client.delete(f'/api/budgets/{d["budgets"][0]["id"]}').status_code == 204


def test_savings_goal_updates_do_not_change_transactions(client):
    payload={'name':'Emergency fund','currency':'USD','target':'1000','saved':'100','deadline':None}
    goal=client.post('/api/goals',json=payload).json()
    assert client.put(f'/api/goals/{goal["id"]}',json={**payload,'saved':'250'}).status_code == 200
    assert Decimal(client.get('/api/goals?currency=USD').json()[0]['saved']) == 250
    assert client.get('/api/goals?currency=KHR').json() == []
    assert client.get('/api/transactions').json() == []
    assert client.delete(f'/api/goals/{goal["id"]}').status_code == 204


def test_receipts_require_key_and_preview_never_saves(client, monkeypatch):
    assert client.post('/api/import/receipt/preview',files={'file':('receipt.png',b'test','image/png')}).status_code == 503
    monkeypatch.setenv('GEMINI_API_KEY','test-key-not-real')
    assert client.post('/api/import/receipt/preview',files={'file':('receipt.png',b'not an image','image/png')}).status_code == 422
    from backend.main import ReceiptData
    monkeypatch.setattr('backend.main.extract_receipt',lambda data,mime:ReceiptData(merchant='កាហ្វេ',date=None,amount='4.50',currency='USD',items=[{'name':'Coffee','price':'4.50'}],warnings=['Confirm the missing date.']))
    image=io.BytesIO();Image.new('RGB',(40,40)).save(image,format='PNG')
    result=client.post('/api/import/receipt/preview',files={'file':('receipt.png',image.getvalue(),'image/png')})
    assert result.status_code == 200
    assert result.json()['rows'][0]['transaction']['date'] == ''
    assert result.json()['warnings']
    assert client.get('/api/transactions').json() == []


def test_export_and_invalid_queries(client):
    client.post('/api/transactions',json=transaction(description='=HYPERLINK("bad")'))
    result=client.get('/api/export?month=2026-11&currency=USD')
    assert result.status_code == 200
    assert "'=HYPERLINK" in result.text
    assert 'attachment' in result.headers['content-disposition']
    assert client.get('/api/dashboard?month=2026-99').status_code == 422
    assert client.get('/api/dashboard?month=2026-11&currency=EUR').status_code == 422
    assert client.get('/').status_code == 200


def test_classifier_handles_english_khmer_and_unknown():
    assert suggest('Brown Coffee')['category'] == 'Food & drinks'
    assert suggest('កាហ្វេ')['category'] == 'Food & drinks'
    assert suggest('PassApp ride')['category'] == 'Transport'
    assert suggest('zzzzzzz')['category'] == 'Other'
    assert suggest('my merchant',[('my merchant','Shopping')]*5)['category'] == 'Shopping'


def test_gemini_adapter_uses_typed_json_and_configured_model(monkeypatch):
    from unittest.mock import MagicMock, patch
    from backend.main import ReceiptData, extract_receipt
    monkeypatch.setenv('GEMINI_API_KEY', 'fake-test-key')
    monkeypatch.setenv('GEMINI_MODEL', 'test-image-model')
    client = MagicMock()
    client.__enter__.return_value = client
    client.models.generate_content.return_value.text = '{"merchant":"Coffee","date":"2026-11-12","amount":"4.50","currency":"USD","items":[{"name":"Coffee","price":"4.50"}],"warnings":[]}'
    with patch('google.genai.Client', return_value=client):
        result = extract_receipt(b'image-bytes', 'image/png')
    assert result.amount == '4.50'
    args = client.models.generate_content.call_args.kwargs
    assert args['model'] == 'test-image-model'
    assert args['config'].response_mime_type == 'application/json'
    assert args['config'].response_schema is ReceiptData
    assert args['contents'][0].inline_data.data == b'image-bytes'
    assert args['contents'][0].inline_data.mime_type == 'image/png'


def test_receipt_save_returns_persisted_location_and_existing_duplicate(client, monkeypatch):
    from backend.main import ReceiptData
    monkeypatch.setenv('GEMINI_API_KEY', 'fake-test-key')
    monkeypatch.setattr('backend.main.extract_receipt',lambda data,mime:ReceiptData(
        merchant='Historical receipt', date='2023-05-13', amount='25000',
        currency='KHR', items=[{'name':'Groceries','price':'25000'}], warnings=[]))
    image=io.BytesIO(); Image.new('RGB',(40,40)).save(image,format='PNG')
    preview=client.post('/api/import/receipt/preview', files={'file':('receipt.png',image.getvalue(),'image/png')}).json()
    payload={'source':'receipt','transactions':[preview['rows'][0]['transaction']]}
    saved=client.post('/api/import/confirm',json=payload).json()
    assert saved['inserted'] == 1
    record=saved['transactions'][0]
    assert record['id'] > 0 and record['source'] == 'receipt'
    assert record['date'] == '2023-05-13' and record['currency'] == 'KHR'
    assert client.get('/api/transactions?month=2023-05&currency=KHR').json() == [record]
    assert client.get('/api/transactions?month=2026-11&currency=USD').json() == []
    # If a user corrects a scanned date, a repeated import must open the record's
    # current location rather than the stale date/currency from the new preview.
    correction={**payload['transactions'][0], 'date':'2024-06-01','currency':'USD'}
    client.put(f'/api/transactions/{record["id"]}',json=correction)
    duplicate=client.post('/api/import/confirm',json=payload).json()
    assert duplicate['inserted'] == 0 and duplicate['skipped'] == 1
    assert duplicate['transactions'][0]['id'] == record['id']
    assert duplicate['transactions'][0]['date'] == '2024-06-01'
    assert duplicate['transactions'][0]['currency'] == 'USD'
    assert len(client.get('/api/transactions').json()) == 1
