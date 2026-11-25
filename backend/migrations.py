"""Additive, idempotent upgrades for merchant details, accounts, and reserves."""
from sqlalchemy import inspect, text

from .database import Base
from .models import Account, Transaction


def initialize_database(engine):
    Base.metadata.create_all(engine)
    columns = {column['name'] for column in inspect(engine).get_columns('transactions')}
    with engine.begin() as connection:
        if 'merchant' not in columns:
            connection.execute(text("ALTER TABLE transactions ADD COLUMN merchant VARCHAR(200) NOT NULL DEFAULT ''"))
        # Earlier versions used the description field for the merchant name.
        connection.execute(text("UPDATE transactions SET merchant = description WHERE merchant = '' OR merchant IS NULL"))
        if 'account_id' not in columns:
            if engine.dialect.name == 'sqlite':
                connection.execute(text('ALTER TABLE transactions ADD COLUMN account_id INTEGER REFERENCES accounts(id)'))
            else:
                connection.execute(text('ALTER TABLE transactions ADD COLUMN account_id INTEGER NULL'))
                connection.execute(text('ALTER TABLE transactions ADD CONSTRAINT fk_transactions_account FOREIGN KEY (account_id) REFERENCES accounts(id)'))
        for currency in ('USD', 'KHR'):
            if not connection.scalar(text('SELECT id FROM accounts WHERE default_key = :currency'), {'currency':currency}):
                connection.execute(Account.__table__.insert().values(name=f'Main {currency}', currency=currency,
                                                                    opening_balance=0, default_key=currency))
        connection.execute(text('UPDATE transactions SET account_id = (SELECT id FROM accounts WHERE default_key = transactions.currency) WHERE account_id IS NULL'))
        allocation_columns={column['name'] for column in inspect(connection).get_columns('reserve_allocations')}
        if 'account_id' not in allocation_columns:
            connection.execute(text('ALTER TABLE reserve_allocations ADD COLUMN account_id INTEGER REFERENCES accounts(id)'))
        if 'currency' not in allocation_columns:
            connection.execute(text('ALTER TABLE reserve_allocations ADD COLUMN currency VARCHAR(3)'))
        connection.execute(text('UPDATE reserve_allocations SET account_id = (SELECT account_id FROM expected_expenses WHERE id = reserve_allocations.expected_expense_id), currency = (SELECT currency FROM expected_expenses WHERE id = reserve_allocations.expected_expense_id) WHERE account_id IS NULL OR currency IS NULL'))
        for index in Transaction.__table__.indexes:
            index.create(connection,checkfirst=True)
