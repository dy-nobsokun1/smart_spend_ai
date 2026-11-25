import re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

CATEGORIES = ['Food & drinks', 'Groceries', 'Transport', 'Shopping', 'Bills & utilities', 'Entertainment', 'Health', 'Education', 'Travel', 'Other', 'Income']
Currency = Literal['USD', 'KHR']
Money = Decimal


def validate_precision(value: Decimal, currency: str):
    unit = Decimal('1') if currency == 'KHR' else Decimal('0.01')
    if value != value.quantize(unit):
        raise ValueError('Use whole riel amounts for KHR and at most two decimal places for USD.')


class TransactionItemIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    # A price is the total for this receipt line, including any quantity.
    price: Money = Field(ge=0, lt=Decimal('1000000000000'), max_digits=14, decimal_places=2)


class TransactionIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    date: date
    description: str = Field(default='', max_length=200)
    merchant: str = Field(default='', max_length=200)
    items: list[TransactionItemIn] = Field(default_factory=list, max_length=100)
    amount: Money = Field(gt=0, lt=Decimal('1000000000000'), max_digits=14, decimal_places=2)
    currency: Currency
    account_id: int | None = Field(default=None, gt=0)
    kind: Literal['expense', 'income'] = 'expense'
    category: str = 'Other'
    note: str = Field(default='', max_length=1000)

    @field_validator('category')
    @classmethod
    def valid_category(cls, value):
        if value not in CATEGORIES:
            raise ValueError('Choose an existing category.')
        return value

    @model_validator(mode='after')
    def valid_money(self):
        self.merchant = self.merchant or self.description
        self.description = self.description or self.merchant
        if not self.merchant:
            raise ValueError('Enter the merchant name.')
        validate_precision(self.amount, self.currency)
        for item in self.items:
            validate_precision(item.price, self.currency)
        if self.kind == 'income':
            self.category = 'Income'
        elif self.category == 'Income':
            raise ValueError('Income is only available for income transactions.')
        return self


class ImportIn(BaseModel):
    transactions: list[TransactionIn] = Field(min_length=1, max_length=1000)
    source: Literal['csv', 'receipt']


class BudgetIn(BaseModel):
    month: str
    currency: Currency
    category: str
    amount: Money = Field(gt=0, lt=Decimal('1000000000000'), decimal_places=2)

    @model_validator(mode='after')
    def valid(self):
        if not re.fullmatch(r'\d{4}-(0[1-9]|1[0-2])', self.month):
            raise ValueError('Month must use YYYY-MM.')
        date.fromisoformat(self.month + '-01')
        if self.category not in CATEGORIES[:-1]:
            raise ValueError('Choose an expense category.')
        validate_precision(self.amount, self.currency)
        return self


class GoalIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    currency: Currency
    target: Money = Field(gt=0, lt=Decimal('1000000000000'), decimal_places=2)
    saved: Money = Field(default=Decimal(0), ge=0, lt=Decimal('1000000000000'), decimal_places=2)
    deadline: date | None = None

    @model_validator(mode='after')
    def valid(self):
        validate_precision(self.target, self.currency)
        validate_precision(self.saved, self.currency)
        return self


class SuggestIn(BaseModel):
    description: str = Field(min_length=1, max_length=200)


class AccountIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=100)
    currency: Currency
    opening_balance: Money = Field(default=Decimal(0), gt=Decimal('-1000000000000'), lt=Decimal('1000000000000'), decimal_places=2)

    @model_validator(mode='after')
    def precision(self):
        validate_precision(self.opening_balance, self.currency)
        return self


class ExpectedExpenseIn(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=200)
    description: str = Field(default='', max_length=1000)
    expected_amount: Money = Field(gt=0, lt=Decimal('1000000000000'), decimal_places=2)
    reserved_amount: Money | None = Field(default=None, ge=0, lt=Decimal('1000000000000'), decimal_places=2)
    currency: Currency
    category: str = 'Other'
    account_id: int = Field(gt=0)
    due_date: date
    recurrence: Literal['once', 'weekly', 'monthly', 'yearly'] = 'once'
    amount_type: Literal['fixed', 'estimated'] = 'fixed'
    funding_method: Literal['full', 'gradual'] = 'gradual'
    reminder_days: int | None = Field(default=None, ge=0, le=365)

    @model_validator(mode='after')
    def valid(self):
        if self.category not in CATEGORIES[:-1]:
            raise ValueError('Choose an expense category.')
        validate_precision(self.expected_amount, self.currency)
        if self.reserved_amount is not None:
            validate_precision(self.reserved_amount, self.currency)
            if self.reserved_amount > self.expected_amount:
                raise ValueError('Reserved funds cannot exceed the expected amount.')
        return self


class FundingIn(BaseModel):
    action: Literal['add', 'release']
    amount: Money = Field(gt=0, lt=Decimal('1000000000000'), decimal_places=2)


class CancelExpectedIn(BaseModel):
    stop_recurrence: bool = False


class CompleteExpectedIn(BaseModel):
    transaction_id: int | None = Field(default=None, gt=0)
    transaction: TransactionIn | None = None
    source: Literal['manual', 'receipt'] = 'manual'
    allow_negative_available: bool = False

    @model_validator(mode='after')
    def one_payment(self):
        if (self.transaction_id is None) == (self.transaction is None):
            raise ValueError('Choose an existing transaction or enter a new payment, but not both.')
        return self
