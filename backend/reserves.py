"""Expected obligations, virtual reserve allocations, and atomic settlement.

Amounts are Decimal throughout. The allocation ledger never creates spending.
All finance mutations lock the account rows (or SQLite's writer lock) before
reading balances, preventing two concurrent requests from allocating the same funds.
"""
import calendar
import re
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from difflib import SequenceMatcher
from zoneinfo import ZoneInfo

from fastapi import HTTPException
from sqlalchemy import select, text

from .ledger import fingerprint, new_transaction, receipt_duplicate, resolve_account, serialize
from .models import Account, ExpectedExpense, RecurringExpense, ReserveAllocation, Transaction, utcnow
from .schemas import validate_precision

ZERO = Decimal('0.00')


def today():
    return datetime.now(ZoneInfo('Asia/Phnom_Penh')).date()


def lock_finances(db):
    if db.bind.dialect.name == 'sqlite':
        driver = db.connection().connection.driver_connection
        if not driver.in_transaction:
            db.execute(text('BEGIN IMMEDIATE'))
    else:
        db.scalars(select(Account).order_by(Account.id).with_for_update()).all()


def read_snapshot(db):
    if db.bind.dialect.name == 'sqlite':
        driver = db.connection().connection.driver_connection
        if not driver.in_transaction:
            db.execute(text('BEGIN'))


def allocation_totals(db):
    totals = defaultdict(lambda:ZERO)
    for expense_id, amount in db.execute(select(ReserveAllocation.expected_expense_id, ReserveAllocation.amount)):
        totals[expense_id] += amount
    return totals


def account_balances(db, currency=None):
    read_snapshot(db)
    accounts = db.scalars(select(Account).order_by(Account.id)).all()
    totals = {a.id:{'actual_balance':a.opening_balance,'reserved_balance':ZERO} for a in accounts}
    defaults = {a.currency:a.id for a in accounts if a.default_key}
    for account_id, currency_code, kind, amount in db.execute(select(Transaction.account_id,Transaction.currency,Transaction.kind,Transaction.amount).where(Transaction.date <= today())):
        key = account_id or defaults.get(currency_code)
        if key in totals:
            totals[key]['actual_balance'] += amount if kind == 'income' else -amount
    allocations = allocation_totals(db)
    for expense in db.scalars(select(ExpectedExpense).where(ExpectedExpense.state == 'active')):
        totals[expense.account_id]['reserved_balance'] += allocations[expense.id]
    return [{**serialize(a),**totals[a.id],
             'available_balance':totals[a.id]['actual_balance']-totals[a.id]['reserved_balance']}
            for a in accounts if not currency or a.currency == currency]


def expense_data(db, expense, allocations=None):
    allocated = (allocations if allocations is not None else allocation_totals(db))[expense.id]
    status = expense.state
    if status == 'active':
        status = 'planned' if not allocated else 'fully_reserved' if allocated >= expense.expected_amount else 'partially_reserved'
    account = db.get(Account,expense.account_id)
    recurrence = db.get(RecurringExpense,expense.recurring_id) if expense.recurring_id else None
    due_in = (expense.due_date-today()).days
    return {**serialize(expense),'reserved_amount':allocated,
            'unfunded_amount':max(ZERO,expense.expected_amount-allocated) if expense.state == 'active' else ZERO,
            'funding_progress':min(Decimal(100),(allocated/expense.expected_amount*100).quantize(Decimal('.01'))),
            'status':status,'overdue':expense.state == 'active' and due_in < 0,'days_until_due':due_in,
            'reminder_due':expense.state == 'active' and expense.reminder_days is not None and due_in <= expense.reminder_days,
            'account_name':account.name,'recurrence':recurrence.frequency if recurrence else 'once',
            'recurrence_active':recurrence.active if recurrence else False,
            'actual_amount':db.get(Transaction,expense.transaction_id).amount if expense.transaction_id else None}


def financial_summary(db, currency, account_id=None):
    balances = account_balances(db,currency)
    if account_id:
        resolve_account(db,currency,account_id)
        balances = [b for b in balances if b['id'] == account_id]
    ids = [b['id'] for b in balances]
    allocations = allocation_totals(db)
    active = db.scalars(select(ExpectedExpense).where(ExpectedExpense.state == 'active',ExpectedExpense.account_id.in_(ids)).order_by(ExpectedExpense.due_date,ExpectedExpense.id)).all()
    actual = sum((b['actual_balance'] for b in balances),ZERO)
    reserved = sum((b['reserved_balance'] for b in balances),ZERO)
    expected = sum((e.expected_amount for e in active),ZERO)
    return {'currency':currency,'as_of':today(),'actual_balance':actual,'reserved_balance':reserved,
            'available_balance':actual-reserved,'total_expected':expected,'remaining_unfunded':expected-reserved,
            'upcoming_count':len(active),'overdue_count':sum(e.due_date < today() for e in active),
            'accounts':balances,'upcoming':[expense_data(db,e,allocations) for e in active[:6]]}


def get_expense(db, record_id, active=False):
    expense = db.get(ExpectedExpense,record_id)
    if expense is None:
        raise HTTPException(404,'Expected expense not found.')
    if active and expense.state != 'active':
        raise HTTPException(409,'This expected expense is already paid or cancelled.')
    return expense


def change_allocation(db, expense, target, reason):
    validate_precision(target,expense.currency)
    current = allocation_totals(db)[expense.id]
    if target < 0 or target > expense.expected_amount:
        raise HTTPException(422,'Reserved funds must be between zero and the expected amount.')
    difference = target-current
    if difference > 0:
        balance = next(b for b in account_balances(db,expense.currency) if b['id'] == expense.account_id)
        if difference > balance['available_balance']:
            raise HTTPException(409,f"Insufficient unallocated funds in {balance['name']}. Available: {balance['available_balance']:.2f} {expense.currency}. Reserve a smaller amount or record the missing income first.")
    if difference:
        db.add(ReserveAllocation(expected_expense_id=expense.id,amount=difference,reason=reason,
                                 account_id=expense.account_id,currency=expense.currency))
        expense.updated_at = utcnow()
        db.flush()


def create_expected(db,payload):
    resolve_account(db,payload.currency,payload.account_id)
    values = payload.model_dump(exclude={'reserved_amount','recurrence'})
    if payload.recurrence != 'once':
        template = RecurringExpense(**{key:values[key] for key in ('name','description','expected_amount','currency','category','account_id','amount_type','reminder_days')},
                                    anchor_date=payload.due_date,frequency=payload.recurrence)
        db.add(template);db.flush()
        values['recurring_id'] = template.id
    expense = ExpectedExpense(**values)
    db.add(expense);db.flush()
    target = payload.expected_amount if payload.funding_method == 'full' else payload.reserved_amount or ZERO
    change_allocation(db,expense,target,'initial')
    return expense


def edit_expected(db,expense,payload):
    resolve_account(db,payload.currency,payload.account_id)
    recurrence = db.get(RecurringExpense,expense.recurring_id) if expense.recurring_id else None
    if payload.recurrence != (recurrence.frequency if recurrence else 'once'):
        raise HTTPException(409,'The recurrence of an existing occurrence cannot change. Cancel the series and create a new plan.')
    current = allocation_totals(db)[expense.id]
    if current and (payload.account_id != expense.account_id or payload.currency != expense.currency):
        raise HTTPException(409,'Release reserved funds before changing the account or currency.')
    if payload.expected_amount < current:
        raise HTTPException(409,'Release the excess reserved funds before reducing the expected amount.')
    # Editing an obligation never silently changes its allocation.
    if payload.reserved_amount is not None and payload.reserved_amount != current:
        raise HTTPException(409,'Use Add or release funds to change the reserved amount.')
    for key,value in payload.model_dump(exclude={'reserved_amount','recurrence'}).items():
        setattr(expense,key,value)
    expense.updated_at = utcnow()
    db.flush()


def occurrence_date(template,index):
    anchor = template.anchor_date
    if template.frequency == 'weekly':
        return anchor+timedelta(weeks=index)
    months = index*(12 if template.frequency == 'yearly' else 1)
    year,month = divmod(anchor.year*12+anchor.month-1+months,12)
    return date(year,month+1,min(anchor.day,calendar.monthrange(year,month+1)[1]))


def next_occurrence(db,expense):
    if not expense.recurring_id:
        return None
    template = db.get(RecurringExpense,expense.recurring_id)
    if not template.active:
        return None
    index = expense.occurrence+1
    existing = db.scalar(select(ExpectedExpense).where(ExpectedExpense.recurring_id == template.id,ExpectedExpense.occurrence == index))
    if existing:
        return existing
    try:
        due = occurrence_date(template,index)
    except (ValueError,OverflowError):
        template.active = False
        return None
    record = ExpectedExpense(**{key:getattr(template,key) for key in ('name','description','expected_amount','currency','category','account_id','amount_type','reminder_days')},
                             due_date=due,recurring_id=template.id,occurrence=index,funding_method='gradual')
    db.add(record);db.flush()
    return record


def cancel_expected(db,expense,stop_recurrence):
    current = allocation_totals(db)[expense.id]
    change_allocation(db,expense,ZERO,'cancelled')
    expense.state = 'cancelled';expense.updated_at = utcnow()
    if expense.recurring_id and stop_recurrence:
        db.get(RecurringExpense,expense.recurring_id).active = False
    db.flush()
    next_occurrence(db,expense)
    return current


def linked_expense(db,transaction_id):
    return db.scalar(select(ExpectedExpense).where(ExpectedExpense.transaction_id == transaction_id))


def complete_expected(db,expense,payload):
    if expense.state == 'paid':
        transaction = db.get(Transaction,expense.transaction_id)
        if payload.transaction_id and payload.transaction_id != transaction.id:
            raise HTTPException(409,'This expected expense has already been paid with a different transaction.')
        if payload.transaction and (payload.transaction.amount != transaction.amount or payload.transaction.currency != transaction.currency
            or payload.transaction.kind != transaction.kind or payload.transaction.date != transaction.date
            or resolve_account(db,payload.transaction.currency,payload.transaction.account_id).id != transaction.account_id):
            raise HTTPException(409,'This expected expense has already been paid. No new transaction was created.')
        return transaction,True
    if expense.state != 'active':
        raise HTTPException(409,'A cancelled expense cannot be paid.')
    transaction = None
    if payload.transaction_id:
        transaction = db.get(Transaction,payload.transaction_id)
        if transaction is None:
            raise HTTPException(404,'Payment transaction not found.')
    else:
        item = payload.transaction
        account = resolve_account(db,item.currency,item.account_id)
        if item.kind != 'expense' or item.currency != expense.currency or account.id != expense.account_id:
            raise HTTPException(422,'The payment must be an expense in the expected expense’s account and currency.')
        if item.date > today():
            raise HTTPException(422,'An actual payment date cannot be in the future.')
        key = fingerprint(item,db)
        if payload.source == 'receipt':
            transaction = receipt_duplicate(item,db)
        if transaction is None:
            balance = next(b for b in account_balances(db,expense.currency) if b['id'] == expense.account_id)
            reserve = allocation_totals(db)[expense.id]
            if balance['available_balance']+reserve-item.amount < 0 and not payload.allow_negative_available:
                raise HTTPException(409,'This payment would leave available funds below zero. Confirm the negative balance explicitly to record it.')
            transaction = new_transaction(item,db,source=payload.source,import_key=key if payload.source == 'receipt' else None)
            db.add(transaction);db.flush()
    if transaction.kind != 'expense' or transaction.currency != expense.currency or transaction.account_id != expense.account_id:
        raise HTTPException(422,'Choose an expense transaction from the same account and currency.')
    if transaction.date > today():
        raise HTTPException(422,'A future-dated transaction cannot complete an expected expense.')
    other = linked_expense(db,transaction.id)
    if other and other.id != expense.id:
        raise HTTPException(409,'This transaction already pays another expected expense.')
    change_allocation(db,expense,ZERO,'paid')
    expense.state = 'paid';expense.transaction_id = transaction.id;expense.updated_at = utcnow()
    db.flush()
    next_occurrence(db,expense)
    return transaction,False


def find_matches(db,payload):
    query = select(ExpectedExpense).where(ExpectedExpense.state == 'active',ExpectedExpense.currency == payload.currency)
    if payload.account_id:
        resolve_account(db,payload.currency,payload.account_id)
        query = query.where(ExpectedExpense.account_id == payload.account_id)
    records = db.scalars(query.order_by(ExpectedExpense.due_date,ExpectedExpense.id)).all()
    allocations = allocation_totals(db)
    text_value = ' '.join(re.findall(r'\w+',f'{payload.merchant} {payload.description}'.casefold()))
    matches = []
    for record in records:
        name = record.name.casefold()
        score,reasons = 0,[]
        if name in text_value or text_value in name or SequenceMatcher(None,name,text_value).ratio() >= .55:
            score += 40;reasons.append('Similar merchant or expense name')
        difference = abs(record.expected_amount-payload.amount)/record.expected_amount
        if difference <= Decimal('.05'):
            score += 30;reasons.append('Similar payment amount')
        elif difference <= Decimal('.20'):
            score += 10
        if abs((record.due_date-payload.date).days) <= 7:
            score += 20;reasons.append('Payment date near due date')
        if record.category == payload.category:
            score += 10;reasons.append('Same expense category')
        if score >= 30:
            matches.append({**expense_data(db,record,allocations),'match_score':score,'match_reasons':reasons})
    return {'suggestions':sorted(matches,key=lambda m:-m['match_score'])[:5],
            'outstanding':[expense_data(db,e,allocations) for e in records]}
