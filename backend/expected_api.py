from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .database import get_db
from .ledger import resolve_account, serialize
from .models import Account, ExpectedExpense, RecurringExpense, ReserveAllocation, Transaction
from .reserves import (account_balances, allocation_totals, cancel_expected, change_allocation,
                       complete_expected, create_expected, edit_expected, expense_data,
                       financial_summary, find_matches, get_expense, lock_finances, read_snapshot, today)
from .schemas import (AccountIn, CancelExpectedIn, CompleteExpectedIn, Currency,
                      ExpectedExpenseIn, FundingIn, TransactionIn, validate_precision)

router = APIRouter(prefix='/api',tags=['Accounts and expected expenses'])
DB = Annotated[Session,Depends(get_db)]


def encode(value):
    return jsonable_encoder(value,custom_encoder={Decimal:lambda amount:format(amount,'.2f')})


def commit(db):
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(409,'This record was changed or linked by another request. Refresh and try again.')


@router.get('/accounts')
def accounts(db:DB,currency:Currency | None=None):
    return encode(account_balances(db,currency))


@router.post('/accounts',status_code=201)
def create_account(payload:AccountIn,db:DB):
    lock_finances(db)
    record=Account(**payload.model_dump())
    db.add(record);commit(db)
    return serialize(record)


@router.put('/accounts/{record_id}')
def edit_account(record_id:int,payload:AccountIn,db:DB):
    lock_finances(db)
    record=resolve_account(db,payload.currency,record_id)
    balance=next(b for b in account_balances(db,payload.currency) if b['id']==record.id)
    delta=payload.opening_balance-record.opening_balance
    if delta<0 and balance['reserved_balance']>0 and balance['available_balance']+delta<0:
        raise HTTPException(409,'Release reserved funds before reducing the opening balance below allocated funds.')
    record.name=payload.name;record.opening_balance=payload.opening_balance
    commit(db)
    return serialize(record)


@router.delete('/accounts/{record_id}',status_code=204)
def delete_account(record_id:int,db:DB):
    lock_finances(db)
    record=db.get(Account,record_id)
    if record is None:
        raise HTTPException(404,'Account not found.')
    if record.default_key or any(db.scalar(select(model.id).where(model.account_id==record_id).limit(1)) for model in (Transaction,ExpectedExpense,RecurringExpense)):
        raise HTTPException(409,'Accounts with financial history and default accounts cannot be deleted.')
    db.delete(record);commit(db)


@router.get('/finance-summary')
def summary(db:DB,currency:Currency='USD',account_id:int | None=None):
    return encode(financial_summary(db,currency,account_id))


@router.get('/expected-expenses')
def expected_expenses(db:DB,currency:Currency='USD',account_id:int | None=None,status:str='active',category:str='',due_from:date | None=None,due_to:date | None=None):
    if status not in ('all','active','planned','partially_reserved','fully_reserved','paid','cancelled','overdue'):
        raise HTTPException(422,'Choose a valid expected expense status.')
    if due_from and due_to and due_from>due_to:
        raise HTTPException(422,'The start date must not follow the end date.')
    read_snapshot(db)
    if account_id:
        resolve_account(db,currency,account_id)
    query=select(ExpectedExpense).where(ExpectedExpense.currency==currency)
    if account_id:query=query.where(ExpectedExpense.account_id==account_id)
    if category:query=query.where(ExpectedExpense.category==category)
    if due_from:query=query.where(ExpectedExpense.due_date>=due_from)
    if due_to:query=query.where(ExpectedExpense.due_date<=due_to)
    totals=allocation_totals(db)
    rows=[expense_data(db,e,totals) for e in db.scalars(query.order_by(ExpectedExpense.due_date,ExpectedExpense.id))]
    rows=[e for e in rows if status=='all' or (status=='active' and e['state']=='active') or (status=='overdue' and e['overdue']) or e['status']==status]
    return encode({'expenses':rows,'summary':financial_summary(db,currency,account_id)})


@router.post('/expected-expenses',status_code=201)
def add_expected(payload:ExpectedExpenseIn,db:DB):
    lock_finances(db)
    record=create_expected(db,payload)
    commit(db)
    return encode(expense_data(db,record))


@router.post('/expected-expenses/matches')
def matches(payload:TransactionIn,db:DB):
    read_snapshot(db)
    return encode(find_matches(db,payload))


@router.get('/expected-expenses/{record_id}')
def get_expected(record_id:int,db:DB):
    read_snapshot(db)
    record=get_expense(db,record_id)
    allocations=db.scalars(select(ReserveAllocation).where(ReserveAllocation.expected_expense_id==record_id).order_by(ReserveAllocation.id)).all()
    return encode({**expense_data(db,record),'allocations':[serialize(entry) for entry in allocations]})


@router.put('/expected-expenses/{record_id}')
def update_expected(record_id:int,payload:ExpectedExpenseIn,db:DB):
    lock_finances(db)
    record=get_expense(db,record_id,active=True)
    edit_expected(db,record,payload);commit(db)
    return encode(expense_data(db,record))


@router.get('/expected-expenses/{record_id}/payments')
def eligible_payments(record_id:int,db:DB):
    expense=get_expense(db,record_id)
    linked=select(ExpectedExpense.transaction_id).where(ExpectedExpense.transaction_id.is_not(None))
    records=db.scalars(select(Transaction).where(Transaction.kind=='expense',Transaction.currency==expense.currency,
        Transaction.account_id==expense.account_id,Transaction.date<=today(),Transaction.id.not_in(linked))
        .order_by(Transaction.date.desc(),Transaction.id.desc())).all()
    return [serialize(t) for t in records]


@router.post('/expected-expenses/{record_id}/fund')
def fund_expected(record_id:int,payload:FundingIn,db:DB):
    lock_finances(db)
    record=get_expense(db,record_id,active=True)
    try:
        validate_precision(payload.amount,record.currency)
    except ValueError as error:
        raise HTTPException(422,str(error))
    current=allocation_totals(db)[record.id]
    target=current+payload.amount if payload.action=='add' else current-payload.amount
    change_allocation(db,record,target,payload.action);commit(db)
    return encode(expense_data(db,record))


@router.post('/expected-expenses/{record_id}/cancel')
def cancel(record_id:int,payload:CancelExpectedIn,db:DB):
    lock_finances(db)
    record=get_expense(db,record_id)
    if record.state=='paid':
        raise HTTPException(409,'A paid expense cannot be cancelled. Its linked payment is preserved.')
    if record.state=='active':cancel_expected(db,record,payload.stop_recurrence)
    elif payload.stop_recurrence and record.recurring_id:db.get(RecurringExpense,record.recurring_id).active=False
    commit(db)
    return encode(expense_data(db,record))


@router.post('/expected-expenses/{record_id}/complete')
def complete(record_id:int,payload:CompleteExpectedIn,db:DB):
    lock_finances(db)
    record=get_expense(db,record_id)
    transaction,already_paid=complete_expected(db,record,payload)
    commit(db)
    return encode({'expense':expense_data(db,record),'transaction':serialize(transaction),'already_paid':already_paid})


@router.get('/recurring-expenses')
def recurring_expenses(db:DB,currency:Currency='USD'):
    return encode([serialize(r) for r in db.scalars(select(RecurringExpense).where(RecurringExpense.currency==currency))])


@router.post('/recurring-expenses/{record_id}/stop')
def stop_recurring(record_id:int,db:DB):
    lock_finances(db)
    record=db.get(RecurringExpense,record_id)
    if record is None:raise HTTPException(404,'Recurring definition not found.')
    record.active=False;commit(db)
    return serialize(record)
