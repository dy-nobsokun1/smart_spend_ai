"""Shared transaction serialization, account assignment, and import identities."""
import hashlib
from decimal import Decimal

from fastapi import HTTPException
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select

from .models import Account, Transaction, TransactionItem


def serialize(record):
    data = {c.name:getattr(record,c.name) for c in record.__table__.columns if c.name != 'import_key'}
    if isinstance(record, Transaction):
        data['merchant'] = record.merchant or record.description
        data['items'] = [{'name':item.name,'price':item.price} for item in record.items]
    return jsonable_encoder(data, custom_encoder={Decimal:lambda value:format(value,'.2f')})


def resolve_account(db, currency, account_id=None):
    account = db.get(Account, account_id) if account_id else db.scalar(select(Account).where(Account.default_key == currency))
    if account is None:
        raise HTTPException(404, 'Account not found.')
    if account.currency != currency:
        raise HTTPException(422, 'The account and transaction must use the same currency.')
    return account


def new_transaction(payload, db, **extra):
    values = payload.model_dump(exclude={'items'})
    values['account_id'] = resolve_account(db, payload.currency, payload.account_id).id
    return Transaction(**values, items=[TransactionItem(**item.model_dump()) for item in payload.items], **extra)


def fingerprint(payload, db):
    parts = [str(payload.date), payload.description.casefold().strip(), format(payload.amount.normalize(),'f'), payload.currency, payload.kind]
    account = resolve_account(db, payload.currency, payload.account_id)
    # Preserve identities from the earlier single-ledger version for defaults.
    if not account.default_key:
        parts.append(f'account:{account.id}')
    return hashlib.sha256('|'.join(parts).encode()).hexdigest()


def receipt_duplicate(payload, db):
    record=db.scalar(select(Transaction).where(Transaction.import_key==fingerprint(payload,db)))
    if record is not None:return record
    account=resolve_account(db,payload.currency,payload.account_id)
    candidates=db.scalars(select(Transaction).where(Transaction.kind==payload.kind,
        Transaction.account_id==account.id,Transaction.currency==payload.currency,
        Transaction.date==payload.date,Transaction.amount==payload.amount)).all()
    candidates=[t for t in candidates if (t.merchant or t.description).casefold()==payload.merchant.casefold()]
    if len(candidates)>1:
        raise HTTPException(409,'Several existing payments match this receipt. Review Transactions or use Pay / link payment to choose the correct payment.')
    return candidates[0] if candidates else None
