import json
from datetime import datetime, date
from decimal import Decimal
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    # clerk = full edit, councillor = read-only, auditor = time-limited read-only
    role = db.Column(db.String(20), nullable=False, default='councillor')
    is_active = db.Column(db.Boolean, default=True)
    auditor_access_until = db.Column(db.Date, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def can_edit(self):
        return self.role == 'clerk'

    @property
    def has_access(self):
        if not self.is_active:
            return False
        if self.role == 'auditor' and self.auditor_access_until:
            return date.today() <= self.auditor_access_until
        return True

    @property
    def role_label(self):
        labels = {'clerk': 'Clerk / RFO', 'councillor': 'Councillor', 'auditor': 'Auditor'}
        return labels.get(self.role, self.role)


class FinancialYear(db.Model):
    __tablename__ = 'financial_years'

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(20), nullable=False)   # e.g. "2025/26"
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    is_current = db.Column(db.Boolean, default=False)
    budget_approved_at = db.Column(db.DateTime, nullable=True)
    budget_approved_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    notes = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    budget_approved_by = db.relationship('User', foreign_keys=[budget_approved_by_id])
    transactions = db.relationship('Transaction', backref='financial_year', lazy='dynamic')
    budgets = db.relationship('Budget', backref='financial_year', lazy='dynamic')
    reconciliations = db.relationship('BankReconciliation', backref='financial_year', lazy='dynamic')

    @property
    def budget_locked(self):
        return self.budget_approved_at is not None


class BudgetHeading(db.Model):
    __tablename__ = 'budget_headings'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # 'receipts' or 'payments'
    category = db.Column(db.String(20), nullable=False)
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)

    budgets = db.relationship('Budget', backref='heading', lazy='dynamic')
    transactions = db.relationship('Transaction', backref='heading', lazy='dynamic')

    @property
    def category_label(self):
        return 'Receipts' if self.category == 'receipts' else 'Payments'


class Budget(db.Model):
    __tablename__ = 'budgets'

    id = db.Column(db.Integer, primary_key=True)
    financial_year_id = db.Column(db.Integer, db.ForeignKey('financial_years.id'), nullable=False)
    budget_heading_id = db.Column(db.Integer, db.ForeignKey('budget_headings.id'), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    # Adjustment fields (mid-year, requires audit note)
    adjusted_amount = db.Column(db.Numeric(12, 2), nullable=True)
    adjustment_note = db.Column(db.Text, nullable=True)
    adjusted_at = db.Column(db.DateTime, nullable=True)
    adjusted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    adjusted_by = db.relationship('User', foreign_keys=[adjusted_by_id])
    __table_args__ = (db.UniqueConstraint('financial_year_id', 'budget_heading_id'),)

    @property
    def effective_amount(self):
        if self.adjusted_amount is not None:
            return self.adjusted_amount
        return self.amount


class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    financial_year_id = db.Column(db.Integer, db.ForeignKey('financial_years.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    reference = db.Column(db.String(50), nullable=False)
    payee_payer = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    budget_heading_id = db.Column(db.Integer, db.ForeignKey('budget_headings.id'), nullable=False)
    # 'receipt' or 'payment'
    transaction_type = db.Column(db.String(10), nullable=False)
    net_amount = db.Column(db.Numeric(12, 2), nullable=False)
    vat_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    vat_reclaimable = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text, nullable=True)
    # Rows are never deleted — only voided
    is_void = db.Column(db.Boolean, default=False)
    void_reason = db.Column(db.Text, nullable=True)
    void_at = db.Column(db.DateTime, nullable=True)
    void_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    void_by = db.relationship('User', foreign_keys=[void_by_id])

    @property
    def gross_amount(self):
        return Decimal(str(self.net_amount)) + Decimal(str(self.vat_amount))

    @property
    def type_label(self):
        return 'Receipt' if self.transaction_type == 'receipt' else 'Payment'


class BankReconciliation(db.Model):
    __tablename__ = 'bank_reconciliations'

    id = db.Column(db.Integer, primary_key=True)
    financial_year_id = db.Column(db.Integer, db.ForeignKey('financial_years.id'), nullable=False)
    month = db.Column(db.Integer, nullable=False)   # 1–12
    year = db.Column(db.Integer, nullable=False)
    opening_balance = db.Column(db.Numeric(12, 2), nullable=False)
    closing_balance = db.Column(db.Numeric(12, 2), nullable=False)
    # Transactions recorded in the cashbook not yet cleared at bank
    outstanding_receipts = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    outstanding_payments = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    notes = db.Column(db.Text, nullable=True)
    is_complete = db.Column(db.Boolean, default=False)
    signed_off_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    signed_off_at = db.Column(db.DateTime, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True)

    signed_off_by = db.relationship('User', foreign_keys=[signed_off_by_id])
    created_by = db.relationship('User', foreign_keys=[created_by_id])

    __table_args__ = (db.UniqueConstraint('financial_year_id', 'month', 'year'),)

    MONTH_NAMES = [
        '', 'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December'
    ]

    @property
    def month_name(self):
        return self.MONTH_NAMES[self.month]

    @property
    def label(self):
        return f'{self.month_name} {self.year}'

    @property
    def cashbook_balance(self):
        # Opening + outstanding receipts − outstanding payments
        return (Decimal(str(self.opening_balance))
                + Decimal(str(self.outstanding_receipts))
                - Decimal(str(self.outstanding_payments)))

    @property
    def difference(self):
        return Decimal(str(self.closing_balance)) - self.cashbook_balance

    @property
    def is_balanced(self):
        return abs(self.difference) < Decimal('0.01')


class Reserve(db.Model):
    __tablename__ = 'reserves'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
    # The general reserve cannot be deleted; earmarked reserves are named
    is_general = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    transfers = db.relationship('ReserveTransfer', backref='reserve', lazy='dynamic',
                                order_by='ReserveTransfer.date')

    @property
    def balance(self):
        return sum(Decimal(str(t.amount)) for t in self.transfers.all())


class ReserveTransfer(db.Model):
    __tablename__ = 'reserve_transfers'

    id = db.Column(db.Integer, primary_key=True)
    reserve_id = db.Column(db.Integer, db.ForeignKey('reserves.id'), nullable=False)
    date = db.Column(db.Date, nullable=False)
    # Positive = funds added, negative = funds withdrawn
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    minute_reference = db.Column(db.String(200), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])


class AuditLog(db.Model):
    """Immutable audit log. Records are never updated or deleted."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    reason = db.Column(db.Text, nullable=True)
    before_state = db.Column(db.Text, nullable=True)   # JSON
    after_state = db.Column(db.Text, nullable=True)    # JSON

    user = db.relationship('User', backref='audit_logs')


def log_action(user_id, entity_type, action, description,
               entity_id=None, reason=None, before=None, after=None):
    """Write one immutable audit record."""
    entry = AuditLog(
        user_id=user_id,
        entity_type=entity_type,
        entity_id=entity_id,
        action=action,
        description=description,
        reason=reason,
        before_state=json.dumps(before, default=str) if before else None,
        after_state=json.dumps(after, default=str) if after else None,
    )
    db.session.add(entry)
