import csv
import io
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, text

from backend.migrations import initialize_database


def purchase(**changes):
    return {'merchant':'ផ្សារថ្មី · Central Market','date':'2026-11-25','amount':'5.50',
            'currency':'USD','kind':'expense','category':'Groceries',
            'items':[{'name':'បន្លែ','price':'2.00'},{'name':'Rice','price':'3.50'}], **changes}


def test_merchant_items_persist_edit_and_search(client):
    result=client.post('/api/transactions',json=purchase())
    assert result.status_code == 201
    record=result.json()
    assert record['merchant'] == purchase()['merchant']
    assert record['description'] == record['merchant']
    assert record['items'] == purchase()['items']
    records=client.get('/api/transactions?search=Rice').json()
    assert len(records) == 1 and records[0]['items'] == record['items']
    changed=purchase(merchant='New merchant',items=[{'name':'Milk','price':'4.00'}])
    assert client.put(f'/api/transactions/{record["id"]}',json=changed).json()['items'] == changed['items']
    assert client.get('/api/transactions?search=Rice').json() == []
    assert client.get('/api/transactions?search=Milk').json()[0]['merchant'] == 'New merchant'
    # Printed total remains authoritative when there are fees or discounts.
    d=client.get('/api/dashboard?month=2026-11&currency=USD').json()
    assert Decimal(d['spending']) == Decimal('5.50')
    assert client.delete(f'/api/transactions/{record["id"]}').status_code == 204
    assert client.get('/api/transactions').json() == []


@pytest.mark.parametrize('items,currency',[
    ([{'name':'','price':'1'}],'USD'),([{'name':'Test','price':'-1'}],'USD'),
    ([{'name':'Test','price':'NaN'}],'USD'),([{'name':'Test','price':'1.001'}],'USD'),
    ([{'name':'Test','price':'1.50'}],'KHR'),([{'name':'Test','price':None}],'USD'),
    ([{'name':'Test','price':'1'}]*101,'USD'),
])
def test_invalid_item_prices_never_save(client,items,currency):
    result=client.post('/api/transactions',json=purchase(items=items,currency=currency,amount='5'))
    assert result.status_code == 422
    assert client.get('/api/transactions').json() == []


def test_legacy_edit_preserves_items_unless_explicitly_cleared(client):
    record=client.post('/api/transactions',json=purchase()).json()
    payload=purchase();payload.pop('items')
    assert client.put(f'/api/transactions/{record["id"]}',json=payload).json()['items'] == record['items']
    payload['items']=[]
    assert client.put(f'/api/transactions/{record["id"]}',json=payload).json()['items'] == []


def test_itemized_receipt_can_enrich_an_older_import_once(client):
    payload={'source':'receipt','transactions':[purchase(items=[])]}
    original=client.post('/api/import/confirm',json=payload).json()['transactions'][0]
    payload['transactions']=[purchase()]
    enriched=client.post('/api/import/confirm',json=payload).json()
    assert enriched['inserted'] == 0 and enriched['updated'] == 1
    assert enriched['transactions'][0]['id'] == original['id']
    assert enriched['transactions'][0]['items'] == purchase()['items']
    # A later OCR result never replaces details already checked by the user.
    payload['transactions']=[purchase(items=[{'name':'Incorrect OCR item','price':'5.50'}])]
    repeated=client.post('/api/import/confirm',json=payload).json()
    assert repeated['updated'] == 0
    assert repeated['transactions'][0]['items'] == purchase()['items']
    assert len(client.get('/api/transactions').json()) == 1


def test_csv_export_reimport_keeps_merchant_and_item_prices(client):
    record=client.post('/api/transactions',json=purchase()).json()
    exported=client.get('/api/export?month=2026-11&currency=USD').text
    columns=next(csv.reader(io.StringIO(exported.lstrip('\ufeff'))))
    assert 'merchant' in columns and 'items' in columns
    preview=client.post('/api/import/csv/preview',files={'file':('items.csv',exported,'text/csv')}).json()
    transaction=preview['rows'][0]['transaction']
    assert transaction['merchant'] == record['merchant'] and transaction['items'] == record['items']
    result=client.post('/api/import/confirm',json={'source':'csv','transactions':[transaction]})
    assert result.status_code == 201
    assert result.json()['transactions'][0]['items'] == record['items']


def test_upgrade_preserves_legacy_records_and_is_repeatable():
    engine=create_engine('sqlite://')
    with engine.begin() as db:
        db.execute(text('''CREATE TABLE transactions (
            id INTEGER PRIMARY KEY, date DATE NOT NULL, description VARCHAR(200) NOT NULL,
            amount NUMERIC(16,2) NOT NULL, currency VARCHAR(3) NOT NULL, kind VARCHAR(10) NOT NULL,
            category VARCHAR(40) NOT NULL, note VARCHAR(1000) NOT NULL,
            source VARCHAR(12) NOT NULL, import_key VARCHAR(64) UNIQUE)'''))
        db.execute(text("""INSERT INTO transactions VALUES
            (1,'2024-06-01','កាហ្វេ',4.50,'USD','expense','Food & drinks','Original note','receipt','original-key')"""))
    initialize_database(engine)
    initialize_database(engine)
    with engine.connect() as db:
        record=db.execute(text('SELECT * FROM transactions')).mappings().one()
        assert record['id'] == 1 and record['merchant'] == 'កាហ្វេ'
        assert record['note'] == 'Original note' and record['import_key'] == 'original-key'
        assert Decimal(str(record['amount'])) == Decimal('4.50')
        assert db.scalar(text('SELECT COUNT(*) FROM transaction_items')) == 0
    assert 'merchant' in {column['name'] for column in inspect(engine).get_columns('transactions')}
    engine.dispose()
