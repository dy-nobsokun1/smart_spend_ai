from concurrent.futures import ThreadPoolExecutor
from datetime import date
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from backend.database import get_db
from backend.main import app
from backend.migrations import initialize_database


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr('backend.reserves.today',lambda:date(2026,11,25))


def configure_account(client,currency='USD',opening='1000'):
    record=next(a for a in client.get('/api/accounts').json() if a['currency']==currency and a['default_key'])
    response=client.put(f'/api/accounts/{record["id"]}',json={'name':record['name'],'currency':currency,'opening_balance':opening})
    assert response.status_code==200,response.text
    return record['id']


def payload(account_key,**changes):
    return {'name':'University tuition','expected_amount':'600','reserved_amount':'200','currency':'USD',
            'account_id':account_key,'category':'Education','due_date':'2026-12-01',
            'recurrence':'once','funding_method':'gradual',**changes}


def create(client,account_id,**changes):
    response=client.post('/api/expected-expenses',json=payload(account_id,**changes))
    assert response.status_code==201,response.text
    return response.json()


def balances(client,currency='USD',account_id=None):
    response=client.get('/api/finance-summary',params={'currency':currency,**({'account_id':account_id} if account_id else {})})
    assert response.status_code==200,response.text
    return {key:Decimal(response.json()[key]) for key in ('actual_balance','reserved_balance','available_balance','total_expected','remaining_unfunded')}


def payment(account_id,amount='250',**changes):
    return {'merchant':'University tuition','date':'2026-11-25','amount':amount,'currency':'USD',
            'account_id':account_id,'kind':'expense','category':'Education',**changes}


def test_expected_reserves_actual_and_budgets_are_four_separate_concepts(client):
    account=configure_account(client)
    client.post('/api/budgets',json={'month':'2026-11','currency':'USD','category':'Education','amount':'300'})
    record=create(client,account)
    assert record['status']=='partially_reserved'
    assert Decimal(record['funding_progress'])==Decimal('33.33')
    assert balances(client)=={'actual_balance':Decimal(1000),'reserved_balance':Decimal(200),'available_balance':Decimal(800),'total_expected':Decimal(600),'remaining_unfunded':Decimal(400)}
    assert client.get('/api/transactions').json()==[]
    dashboard=client.get('/api/dashboard?month=2026-11&currency=USD').json()
    assert Decimal(dashboard['spending'])==0
    assert Decimal(dashboard['budget'])==300 and Decimal(dashboard['budget_spent'])==0
    assert Decimal(dashboard['finance']['available_balance'])==800


def test_full_reservation_and_funding_releases(client):
    account=configure_account(client)
    record=create(client,account,expected_amount='250',funding_method='full',reserved_amount=None)
    assert record['status']=='fully_reserved' and balances(client)['available_balance']==750
    released=client.post(f'/api/expected-expenses/{record["id"]}/fund',json={'action':'release','amount':'100'}).json()
    assert released['status']=='partially_reserved' and balances(client)['available_balance']==850
    funded=client.post(f'/api/expected-expenses/{record["id"]}/fund',json={'action':'add','amount':'100'}).json()
    assert funded['status']=='fully_reserved'
    history=client.get(f'/api/expected-expenses/{record["id"]}').json()['allocations']
    assert [Decimal(e['amount']) for e in history]==[Decimal(250),Decimal(-100),Decimal(100)]
    assert all(e['account_id']==account and e['currency']=='USD' for e in history)


def test_edit_expected_amount_never_implicitly_allocates_funds(client):
    account=configure_account(client)
    record=create(client,account)
    edit=payload(account,expected_amount='800');edit.pop('reserved_amount')
    response=client.put(f'/api/expected-expenses/{record["id"]}',json=edit)
    assert response.status_code==200 and Decimal(response.json()['reserved_amount'])==200
    assert balances(client)['remaining_unfunded']==600
    assert client.put(f'/api/expected-expenses/{record["id"]}',json=payload(account,expected_amount='100',reserved_amount=None)).status_code==409
    assert client.put(f'/api/expected-expenses/{record["id"]}',json=payload(account,reserved_amount='300')).status_code==409
    assert balances(client)['reserved_balance']==200


def test_cancel_releases_reserves_without_spending_and_is_idempotent(client):
    account=configure_account(client);record=create(client,account)
    url=f'/api/expected-expenses/{record["id"]}/cancel'
    assert client.post(url,json={}).json()['status']=='cancelled'
    assert client.post(url,json={}).status_code==200
    b=balances(client)
    assert b['actual_balance']==1000 and b['available_balance']==1000 and b['reserved_balance']==0
    assert client.get('/api/transactions').json()==[]
    assert len(client.get(f'/api/expected-expenses/{record["id"]}').json()['allocations'])==2


@pytest.mark.parametrize('expected,reserved,actual,available',[('250','250','250','750'),('50','50','42','958'),('50','50','60','940'),('600','200','650','350'),('100','0','100','900')])
def test_payment_releases_reserve_and_deducts_actual_exactly_once(client,expected,reserved,actual,available):
    account=configure_account(client);record=create(client,account,expected_amount=expected,reserved_amount=reserved)
    url=f'/api/expected-expenses/{record["id"]}/complete'
    data={'transaction':payment(account,actual)}
    first=client.post(url,json=data)
    assert first.status_code==200,first.text
    assert not first.json()['already_paid'] and first.json()['expense']['status']=='paid'
    again=client.post(url,json=data).json()
    assert again['already_paid'] and again['transaction']['id']==first.json()['transaction']['id']
    b=balances(client)
    assert b['reserved_balance']==0 and b['actual_balance']==Decimal(available) and b['available_balance']==Decimal(available)
    assert len(client.get('/api/transactions').json())==1


def test_link_existing_payment_never_deducts_again_and_cannot_link_twice(client):
    account=configure_account(client)
    transaction=client.post('/api/transactions',json=payment(account)).json()
    one=create(client,account,expected_amount='250',reserved_amount='250')
    two=create(client,account,expected_amount='250',reserved_amount='0')
    before=balances(client)['actual_balance']
    response=client.post(f'/api/expected-expenses/{one["id"]}/complete',json={'transaction_id':transaction['id']})
    assert response.status_code==200,response.text
    assert balances(client)['actual_balance']==before
    assert len(client.get('/api/transactions').json())==1
    assert client.post(f'/api/expected-expenses/{two["id"]}/complete',json={'transaction_id':transaction['id']}).status_code==409
    assert Decimal(client.get(f'/api/expected-expenses/{two["id"]}').json()['reserved_amount'])==0


def test_insufficient_funding_rolls_back_entire_plan_and_reserve(client):
    account=configure_account(client,opening='100')
    response=client.post('/api/expected-expenses',json=payload(account,funding_method='full'))
    assert response.status_code==409
    assert client.get('/api/expected-expenses?status=all').json()['expenses']==[]
    record=create(client,account,expected_amount='200',reserved_amount='80')
    assert client.post(f'/api/expected-expenses/{record["id"]}/fund',json={'action':'add','amount':'21'}).status_code==409
    assert balances(client)['reserved_balance']==80
    assert client.post(f'/api/expected-expenses/{record["id"]}/fund',json={'action':'release','amount':'81'}).status_code==422


def test_negative_payment_balance_needs_explicit_confirmation(client):
    account=configure_account(client,opening='100');record=create(client,account,expected_amount='50',reserved_amount='50')
    url=f'/api/expected-expenses/{record["id"]}/complete';body={'transaction':payment(account,'120')}
    assert client.post(url,json=body).status_code==409
    assert client.get('/api/transactions').json()==[] and balances(client)['reserved_balance']==50
    assert client.post(url,json={**body,'allow_negative_available':True}).status_code==200
    assert balances(client)['available_balance']==-20


def test_overdue_and_reminder_flags_never_release_reserves(client):
    account=configure_account(client)
    record=create(client,account,due_date='2026-11-20',reminder_days=3)
    assert record['overdue'] and record['reminder_due'] and record['days_until_due']==-5
    assert Decimal(record['reserved_amount'])==200
    response=client.get('/api/expected-expenses?status=overdue').json()
    assert len(response['expenses'])==1 and response['summary']['overdue_count']==1
    assert balances(client)['reserved_balance']==200


@pytest.mark.parametrize('frequency,anchor,next_date',[('weekly','2026-11-25','2026-12-02'),('monthly','2026-01-31','2026-02-28'),('yearly','2024-02-29','2025-02-28')])
def test_recurring_definitions_generate_one_unfunded_occurrence(client,frequency,anchor,next_date):
    account=configure_account(client)
    record=create(client,account,expected_amount='50',reserved_amount='50',recurrence=frequency,due_date=anchor)
    url=f'/api/expected-expenses/{record["id"]}/complete'
    body={'transaction':payment(account,'42')}
    for _ in range(3):assert client.post(url,json=body).status_code==200
    rows=client.get('/api/expected-expenses?status=all').json()['expenses']
    assert len(rows)==2
    next_record=next(e for e in rows if e['status']=='planned')
    assert next_record['due_date']==next_date and Decimal(next_record['reserved_amount'])==0
    assert next_record['recurring_id']==record['recurring_id'] and next_record['occurrence']==1
    assert balances(client)['reserved_balance']==0
    assert len(client.get('/api/recurring-expenses').json())==1


def test_monthly_anchor_preserves_31st_and_stopping_recurrence_preserves_history(client):
    account=configure_account(client)
    record=create(client,account,recurrence='monthly',due_date='2026-01-31',expected_amount='10',reserved_amount='0')
    client.post(f'/api/expected-expenses/{record["id"]}/complete',json={'transaction':payment(account,'10')})
    feb=client.get('/api/expected-expenses').json()['expenses'][0]
    client.post(f'/api/expected-expenses/{feb["id"]}/complete',json={'transaction':payment(account,'10')})
    march=client.get('/api/expected-expenses').json()['expenses'][0]
    assert march['due_date']=='2026-03-31'
    assert client.post(f'/api/expected-expenses/{march["id"]}/cancel',json={'stop_recurrence':True}).status_code==200
    assert len(client.get('/api/expected-expenses?status=all').json()['expenses'])==3
    assert not client.get('/api/recurring-expenses').json()[0]['active']


def test_accounts_and_currencies_cannot_borrow_each_others_reserves(client):
    usd=configure_account(client,opening='100');khr=configure_account(client,'KHR','500000')
    second=client.post('/api/accounts',json={'name':'Second USD','currency':'USD','opening_balance':'900'}).json()['id']
    assert client.post('/api/expected-expenses',json=payload(usd,expected_amount='200',reserved_amount='150')).status_code==409
    record=create(client,second,expected_amount='600',reserved_amount='200')
    riel=create(client,khr,currency='KHR',expected_amount='100000',reserved_amount='25000')
    assert balances(client,account_id=usd)['available_balance']==100
    assert balances(client,account_id=second)['available_balance']==700
    assert balances(client,'KHR')['available_balance']==475000
    assert client.post(f'/api/expected-expenses/{record["id"]}/complete',json={'transaction':payment(usd,'50')}).status_code==422
    assert client.post(f'/api/expected-expenses/{riel["id"]}/fund',json={'action':'add','amount':'1.5'}).status_code==422
    assert client.post('/api/transactions',json=payment(khr,'50')).status_code==422
    assert client.delete(f'/api/accounts/{second}').status_code==409
    assert client.put(f'/api/accounts/{second}',json={'name':'Second USD','currency':'USD','opening_balance':'100'}).status_code==409


def test_linked_payment_financial_edits_and_deletion_are_blocked(client):
    account=configure_account(client);record=create(client,account,expected_amount='250',reserved_amount='250')
    result=client.post(f'/api/expected-expenses/{record["id"]}/complete',json={'transaction':payment(account)}).json()
    transaction=result['transaction'];url=f'/api/transactions/{transaction["id"]}'
    for changes in ({'amount':'251'},{'date':'2026-11-24'},{'category':'Other'},{'kind':'income'}):
        assert client.put(url,json=payment(account,**changes)).status_code==409
    assert client.delete(url).status_code==409
    assert client.put(url,json=payment(account,note='Receipt filed')).status_code==200
    assert balances(client)['actual_balance']==750
    assert client.post(f'/api/expected-expenses/{record["id"]}/cancel',json={}).status_code==409


def test_receipt_matches_are_suggestions_and_confirm_links_existing_import(client):
    account=configure_account(client)
    record=create(client,account,name='Brown Coffee',expected_amount='50',reserved_amount='50',category='Food & drinks',due_date='2026-11-25')
    receipt=payment(account,'50',merchant='Brown Coffee',description='Brown Coffee',category='Food & drinks')
    suggestions=client.post('/api/expected-expenses/matches',json=receipt).json()
    assert suggestions['suggestions'][0]['id']==record['id']
    assert balances(client)['reserved_balance']==50 and client.get('/api/transactions').json()==[]
    imported=client.post('/api/import/confirm',json={'source':'receipt','transactions':[receipt]}).json()['transactions'][0]
    paid=client.post(f'/api/expected-expenses/{record["id"]}/complete',json={'source':'receipt','transaction':receipt})
    assert paid.status_code==200 and paid.json()['transaction']['id']==imported['id']
    assert len(client.get('/api/transactions').json())==1 and balances(client)['available_balance']==950


def test_future_transactions_do_not_fund_current_reserves_or_complete_payments(client):
    account=configure_account(client,opening='0')
    future=client.post('/api/transactions',json=payment(account,'1000',date='2026-12-01',kind='income')).json()
    assert balances(client)['actual_balance']==0
    record=create(client,account,expected_amount='50',reserved_amount='0')
    assert client.post(f'/api/expected-expenses/{record["id"]}/complete',json={'transaction':payment(account,'50',date='2026-12-01')}).status_code==422
    assert client.post(f'/api/expected-expenses/{record["id"]}/complete',json={'transaction_id':future['id']}).status_code==422


def test_receipt_completion_reuses_a_manual_payment_only_after_user_confirmation(client):
    account=configure_account(client)
    receipt=payment(account,'50',merchant='Internet provider',category='Bills & utilities')
    actual=client.post('/api/transactions',json=receipt).json()
    record=create(client,account,name='Internet provider',category='Bills & utilities',expected_amount='50',reserved_amount='50')
    result=client.post(f'/api/expected-expenses/{record["id"]}/complete',json={'transaction':receipt,'source':'receipt'})
    assert result.status_code==200 and result.json()['transaction']['id']==actual['id']
    assert len(client.get('/api/transactions').json())==1
    assert balances(client)['available_balance']==950


def test_exact_decimal_funding(client):
    account=configure_account(client,opening='0.30')
    record=create(client,account,expected_amount='0.20',reserved_amount='0.10')
    assert client.post(f'/api/expected-expenses/{record["id"]}/fund',json={'action':'add','amount':'0.10'}).status_code==200
    assert balances(client)['available_balance']==Decimal('0.10')


def test_unfunded_expectation_leaves_all_money_available(client):
    account=configure_account(client)
    body=payload(account);body.pop('reserved_amount')
    record=client.post('/api/expected-expenses',json=body).json()
    assert record['status']=='planned' and Decimal(record['reserved_amount'])==0
    assert balances(client)['available_balance']==1000
    assert balances(client)['total_expected']==600


def test_riel_payment_does_not_change_dollar_balance(client):
    configure_account(client)
    riel=configure_account(client,'KHR','500000')
    record=create(client,riel,currency='KHR',expected_amount='50000',reserved_amount='50000')
    result=client.post(f'/api/expected-expenses/{record["id"]}/complete',json={'transaction':payment(riel,'42000',currency='KHR')})
    assert result.status_code==200
    assert balances(client,'KHR')['available_balance']==458000
    assert balances(client,'KHR')['reserved_balance']==0
    assert balances(client)['actual_balance']==1000


def test_cancelling_one_recurring_occurrence_releases_funds_and_generates_only_one_next(client):
    account=configure_account(client)
    record=create(client,account,recurrence='weekly',due_date='2026-11-25')
    url=f'/api/expected-expenses/{record["id"]}/cancel'
    assert client.post(url,json={}).status_code==200
    assert client.post(url,json={}).status_code==200
    rows=client.get('/api/expected-expenses?status=all').json()['expenses']
    assert len(rows)==2 and rows[1]['due_date']=='2026-12-02'
    assert balances(client)['available_balance']==1000 and balances(client)['reserved_balance']==0
    assert client.get('/api/transactions').json()==[]


def test_scanning_proof_after_manual_settlement_does_not_create_a_second_expense(client):
    account=configure_account(client)
    record=create(client,account,expected_amount='50',reserved_amount='50')
    receipt=payment(account,'50')
    paid=client.post(f'/api/expected-expenses/{record["id"]}/complete',json={'transaction':receipt}).json()
    scan=client.post('/api/import/confirm',json={'source':'receipt','transactions':[receipt]}).json()
    assert scan['inserted']==0 and scan['skipped']==1
    assert scan['transactions'][0]['id']==paid['transaction']['id']
    assert balances(client)['available_balance']==950 and len(client.get('/api/transactions').json())==1


@pytest.mark.parametrize('changes',[{'expected_amount':'0'},{'reserved_amount':'-1'},{'reserved_amount':'601'},
    {'expected_amount':'NaN'},{'expected_amount':'1.001'},{'category':'Income'},
    {'recurrence':'daily'},{'due_date':'2026-02-30'},{'account_id':9999}])
def test_invalid_expected_data_never_changes_balance(client,changes):
    account=configure_account(client)
    assert client.post('/api/expected-expenses',json=payload(account,**changes)).status_code in (422,404)
    assert balances(client)['reserved_balance']==0


def test_concurrent_reservations_cannot_overallocate_and_payments_are_idempotent():
    # Separate connections to a file database reproduce real SQLite writer locks.
    folder=Path(__file__).resolve().parent.parent/'test-results'
    folder.mkdir(exist_ok=True)
    engine=create_engine('sqlite:///'+(folder/f'concurrency-{uuid4().hex}.db').as_posix(),connect_args={'check_same_thread':False,'timeout':10})
    initialize_database(engine);sessions=sessionmaker(engine,expire_on_commit=False)
    def override():
        with sessions() as db:yield db
    app.dependency_overrides[get_db]=override
    try:
        with TestClient(app) as client:
            account=configure_account(client,opening='100')
            def reserve(_):return client.post('/api/expected-expenses',json=payload(account,expected_amount='80',reserved_amount='80'))
            with ThreadPoolExecutor(2) as executor:responses=list(executor.map(reserve,range(2)))
            assert sorted(r.status_code for r in responses)==[201,409]
            record=next(r.json() for r in responses if r.status_code==201)
            assert balances(client)['reserved_balance']==80
            def pay(_):return client.post(f'/api/expected-expenses/{record["id"]}/complete',json={'transaction':payment(account,'80')})
            with ThreadPoolExecutor(2) as executor:payments=list(executor.map(pay,range(2)))
            assert all(r.status_code==200 for r in payments)
            assert len({r.json()['transaction']['id'] for r in payments})==1
            assert len(client.get('/api/transactions').json())==1
    finally:
        app.dependency_overrides.clear();engine.dispose()
