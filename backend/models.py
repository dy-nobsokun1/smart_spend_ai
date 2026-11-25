from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


class Transaction(Base):
    __tablename__ = 'transactions'
    id: Mapped[int] = mapped_column(primary_key=True)
    date: Mapped[date] = mapped_column(Date, index=True)
    description: Mapped[str] = mapped_column(String(200))
    merchant: Mapped[str] = mapped_column(String(200), default='')
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3), index=True)
    kind: Mapped[str] = mapped_column(String(10))
    category: Mapped[str] = mapped_column(String(40))
    note: Mapped[str] = mapped_column(String(1000), default='')
    source: Mapped[str] = mapped_column(String(12), default='manual')
    import_key: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    account_id: Mapped[int | None] = mapped_column(ForeignKey('accounts.id'), index=True, nullable=True)
    items: Mapped[list['TransactionItem']] = relationship(
        back_populates='transaction', cascade='all, delete-orphan', lazy='selectin',
        order_by='TransactionItem.id',
    )


class TransactionItem(Base):
    __tablename__ = 'transaction_items'
    id: Mapped[int] = mapped_column(primary_key=True)
    transaction_id: Mapped[int] = mapped_column(ForeignKey('transactions.id'), index=True)
    name: Mapped[str] = mapped_column(String(200))
    price: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    transaction: Mapped[Transaction] = relationship(back_populates='items')


class Budget(Base):
    __tablename__ = 'budgets'
    __table_args__ = (UniqueConstraint('month', 'currency', 'category'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    month: Mapped[str] = mapped_column(String(7), index=True)
    currency: Mapped[str] = mapped_column(String(3))
    category: Mapped[str] = mapped_column(String(40))
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))


class Goal(Base):
    __tablename__ = 'goals'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3))
    target: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    saved: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Account(Base):
    __tablename__ = 'accounts'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    currency: Mapped[str] = mapped_column(String(3))
    opening_balance: Mapped[Decimal] = mapped_column(Numeric(16, 2), default=0)
    default_key: Mapped[str | None] = mapped_column(String(3), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class RecurringExpense(Base):
    __tablename__ = 'recurring_expenses'
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(1000), default='')
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3))
    category: Mapped[str] = mapped_column(String(40))
    account_id: Mapped[int] = mapped_column(ForeignKey('accounts.id'))
    anchor_date: Mapped[date] = mapped_column(Date)
    frequency: Mapped[str] = mapped_column(String(10))
    amount_type: Mapped[str] = mapped_column(String(10), default='fixed')
    reminder_days: Mapped[int | None] = mapped_column(nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExpectedExpense(Base):
    __tablename__ = 'expected_expenses'
    __table_args__ = (UniqueConstraint('recurring_id', 'occurrence'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(1000), default='')
    expected_amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    currency: Mapped[str] = mapped_column(String(3))
    category: Mapped[str] = mapped_column(String(40))
    account_id: Mapped[int] = mapped_column(ForeignKey('accounts.id'), index=True)
    due_date: Mapped[date] = mapped_column(Date, index=True)
    amount_type: Mapped[str] = mapped_column(String(10), default='fixed')
    funding_method: Mapped[str] = mapped_column(String(10), default='gradual')
    state: Mapped[str] = mapped_column(String(10), default='active')
    reminder_days: Mapped[int | None] = mapped_column(nullable=True)
    recurring_id: Mapped[int | None] = mapped_column(ForeignKey('recurring_expenses.id'), nullable=True)
    occurrence: Mapped[int] = mapped_column(default=0)
    transaction_id: Mapped[int | None] = mapped_column(ForeignKey('transactions.id'), unique=True, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ReserveAllocation(Base):
    __tablename__ = 'reserve_allocations'
    id: Mapped[int] = mapped_column(primary_key=True)
    expected_expense_id: Mapped[int] = mapped_column(ForeignKey('expected_expenses.id'), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(16, 2))
    account_id: Mapped[int | None] = mapped_column(ForeignKey('accounts.id'), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    reason: Mapped[str] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
