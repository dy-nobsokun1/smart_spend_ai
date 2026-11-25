from calendar import monthrange
from datetime import date, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo
from datetime import datetime

from sqlalchemy import select

from .models import Account, Budget, Goal, Transaction


def seed(db):
    if any(db.scalar(select(model.id).limit(1)) is not None for model in (Transaction, Budget, Goal)):
        return
    today = datetime.now(ZoneInfo('Asia/Phnom_Penh')).date()
    rows = [('Brown Coffee', 'Food & drinks', '4.50'), ('Lucky Supermarket', 'Groceries', '32.80'), ('Grab ride', 'Transport', '3.25'), ('Lunch at Eleven One', 'Food & drinks', '8.50'), ('Internet subscription', 'Bills & utilities', '25.00'), ('Zando', 'Shopping', '24.90'), ('Legend Cinema', 'Entertainment', '7.00'), ('ផ្សារថ្មី · Central Market', 'Groceries', '18.00'), ('Coffee with friends', 'Food & drinks', '6.00'), ('PassApp', 'Transport', '2.50'), ('Electricity bill', 'Bills & utilities', '42.00'), ('Dinner at Malis', 'Food & drinks', '22.50'), ('U-Care Pharmacy', 'Health', '12.00')]
    for offset in (0, 1):
        first = today.replace(day=1)
        if offset:
            first = (first - timedelta(days=1)).replace(day=1)
        last_day = monthrange(first.year, first.month)[1] if offset else today.day
        for index in range(36 if offset else max(5, today.day + 4)):
            name, category, amount = rows[index % len(rows)]
            day = (index * 7 + 3) % last_day + 1
            db.add(Transaction(date=first.replace(day=day), description=name, category=category, amount=Decimal(amount) * (Decimal('1.15') if offset else 1), currency='USD', kind='expense', source='demo'))
        db.add(Transaction(date=first, description='Monthly salary', category='Income', amount=Decimal('1800'), currency='USD', kind='income', source='demo'))
    for day, name, amount, category in [(2, 'ផ្សារអូរឫស្សី', 85000, 'Groceries'), (7, 'អាហារថ្ងៃត្រង់', 18000, 'Food & drinks'), (12, 'សាំង', 25000, 'Transport')]:
        db.add(Transaction(date=today.replace(day=min(day, today.day)), description=name, category=category, amount=Decimal(amount), currency='KHR', kind='expense', source='demo'))
    db.add(Transaction(date=today.replace(day=1), description='Freelance project', category='Income', amount=Decimal('600000'), currency='KHR', kind='income', source='demo'))
    for currency, multiplier in [('USD', 1), ('KHR', 4000)]:
        for category, amount in [('Food & drinks', 250), ('Groceries', 200), ('Transport', 100), ('Shopping', 150), ('Bills & utilities', 200)]:
            db.add(Budget(month=today.strftime('%Y-%m'), category=category, currency=currency, amount=Decimal(amount * multiplier)))
    for name, target, saved, days, currency in [('A little peace of mind', 2000, 1250, 180, 'USD'), ('Weekend in Siem Reap', 600, 240, 90, 'USD'), ('New laptop fund', 4000000, 1200000, 240, 'KHR')]:
        db.add(Goal(name=name, target=Decimal(target), saved=Decimal(saved), currency=currency, deadline=today + timedelta(days=days)))
    with db.no_autoflush:
        accounts = {a.currency:a.id for a in db.scalars(select(Account).where(Account.default_key.is_not(None)))}
    for record in list(db.new):
        if isinstance(record, Transaction):
            record.account_id = accounts[record.currency]
    db.commit()
