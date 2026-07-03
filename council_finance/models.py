import json
from datetime import datetime, date
from decimal import Decimal
from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

db = SQLAlchemy()


# ---------------------------------------------------------------------------
# Council configuration
# ---------------------------------------------------------------------------

class CouncilSettings(db.Model):
    __tablename__ = 'council_settings'

    id = db.Column(db.Integer, primary_key=True)
    council_name = db.Column(db.String(200), nullable=False, default='Our Parish Council')
    council_address = db.Column(db.Text, nullable=True)
    # 'receipts_payments' or 'income_expenditure'
    accounting_basis = db.Column(db.String(30), nullable=False, default='receipts_payments')
    vat_registered = db.Column(db.Boolean, default=False)
    vat_number = db.Column(db.String(30), nullable=True)
    # SharePoint document storage (optional)
    sharepoint_site_url = db.Column(db.String(500), nullable=True)
    sharepoint_library = db.Column(db.String(200), nullable=True, default='Shared Documents')
    sharepoint_folder = db.Column(db.String(500), nullable=True, default='Council Finance/Documents')
    updated_at = db.Column(db.DateTime, nullable=True)

    @property
    def is_ie(self):
        return self.accounting_basis == 'income_expenditure'

    @property
    def basis_label(self):
        return ('Income & Expenditure' if self.is_ie
                else 'Receipts & Payments')


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
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


# ---------------------------------------------------------------------------
# Bank accounts
# ---------------------------------------------------------------------------

class BankAccount(db.Model):
    __tablename__ = 'bank_accounts'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    # 'current', 'savings', 'deposit', 'investment'
    account_type = db.Column(db.String(20), nullable=False, default='current')
    bank_name = db.Column(db.String(100), nullable=True)
    # Store last 4 digits only
    account_number_last4 = db.Column(db.String(4), nullable=True)
    sort_code = db.Column(db.String(10), nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    # Primary operating account used as default
    is_primary = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    @property
    def display_name(self):
        suffix = f' ···{self.account_number_last4}' if self.account_number_last4 else ''
        return f'{self.name}{suffix}'


# ---------------------------------------------------------------------------
# Financial years
# ---------------------------------------------------------------------------

class FinancialYear(db.Model):
    __tablename__ = 'financial_years'

    id = db.Column(db.Integer, primary_key=True)
    label = db.Column(db.String(20), nullable=False)
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
    accruals = db.relationship('Accrual', backref='financial_year', lazy='dynamic')

    @property
    def budget_locked(self):
        return self.budget_approved_at is not None


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

class BudgetHeading(db.Model):
    __tablename__ = 'budget_headings'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    category = db.Column(db.String(20), nullable=False)  # 'receipts'/'income' or 'payments'/'expenditure'
    sort_order = db.Column(db.Integer, default=0)
    is_active = db.Column(db.Boolean, default=True)
    # Section 137 flag — headings where S137 spend may occur
    is_section_137 = db.Column(db.Boolean, default=False)

    budgets = db.relationship('Budget', backref='heading', lazy='dynamic')
    transactions = db.relationship('Transaction', backref='heading', lazy='dynamic')

    @property
    def category_label(self):
        if self.category in ('receipts', 'income'):
            return 'Income / Receipts'
        return 'Payments / Expenditure'

    @property
    def is_income(self):
        return self.category in ('receipts', 'income')


class Budget(db.Model):
    __tablename__ = 'budgets'

    id = db.Column(db.Integer, primary_key=True)
    financial_year_id = db.Column(db.Integer, db.ForeignKey('financial_years.id'), nullable=False)
    budget_heading_id = db.Column(db.Integer, db.ForeignKey('budget_headings.id'), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    adjusted_amount = db.Column(db.Numeric(12, 2), nullable=True)
    adjustment_note = db.Column(db.Text, nullable=True)
    adjusted_at = db.Column(db.DateTime, nullable=True)
    adjusted_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)

    adjusted_by = db.relationship('User', foreign_keys=[adjusted_by_id])
    __table_args__ = (db.UniqueConstraint('financial_year_id', 'budget_heading_id'),)

    @property
    def effective_amount(self):
        return self.adjusted_amount if self.adjusted_amount is not None else self.amount


# ---------------------------------------------------------------------------
# Transactions (cashbook)
# ---------------------------------------------------------------------------

class Transaction(db.Model):
    __tablename__ = 'transactions'

    id = db.Column(db.Integer, primary_key=True)
    financial_year_id = db.Column(db.Integer, db.ForeignKey('financial_years.id'), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=True)
    date = db.Column(db.Date, nullable=False)
    reference = db.Column(db.String(50), nullable=False)
    payee_payer = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    budget_heading_id = db.Column(db.Integer, db.ForeignKey('budget_headings.id'), nullable=False)
    transaction_type = db.Column(db.String(10), nullable=False)  # 'receipt' or 'payment'
    net_amount = db.Column(db.Numeric(12, 2), nullable=False)
    vat_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    vat_reclaimable = db.Column(db.Boolean, nullable=False, default=False)
    notes = db.Column(db.Text, nullable=True)
    # Section 137 expenditure flag
    section_137 = db.Column(db.Boolean, nullable=False, default=False)
    # Grant association (optional)
    grant_id = db.Column(db.Integer, db.ForeignKey('grants.id'), nullable=True)
    # SharePoint document
    document_url = db.Column(db.String(2000), nullable=True)
    document_filename = db.Column(db.String(500), nullable=True)
    # Voiding
    is_void = db.Column(db.Boolean, default=False)
    void_reason = db.Column(db.Text, nullable=True)
    void_at = db.Column(db.DateTime, nullable=True)
    void_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=True)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    void_by = db.relationship('User', foreign_keys=[void_by_id])
    bank_account = db.relationship('BankAccount', foreign_keys=[bank_account_id])
    grant = db.relationship('Grant', foreign_keys=[grant_id], back_populates='transactions')

    @property
    def gross_amount(self):
        return Decimal(str(self.net_amount)) + Decimal(str(self.vat_amount))

    @property
    def type_label(self):
        return 'Receipt' if self.transaction_type == 'receipt' else 'Payment'


# ---------------------------------------------------------------------------
# Bank reconciliation
# ---------------------------------------------------------------------------

class BankReconciliation(db.Model):
    __tablename__ = 'bank_reconciliations'

    id = db.Column(db.Integer, primary_key=True)
    financial_year_id = db.Column(db.Integer, db.ForeignKey('financial_years.id'), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=True)
    month = db.Column(db.Integer, nullable=False)
    year = db.Column(db.Integer, nullable=False)
    opening_balance = db.Column(db.Numeric(12, 2), nullable=False)
    closing_balance = db.Column(db.Numeric(12, 2), nullable=False)
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
    bank_account = db.relationship('BankAccount', foreign_keys=[bank_account_id])

    __table_args__ = (
        db.UniqueConstraint('financial_year_id', 'bank_account_id', 'month', 'year'),
    )

    MONTH_NAMES = [
        '', 'January', 'February', 'March', 'April', 'May', 'June',
        'July', 'August', 'September', 'October', 'November', 'December',
    ]

    @property
    def month_name(self):
        return self.MONTH_NAMES[self.month]

    @property
    def label(self):
        acct = f' — {self.bank_account.name}' if self.bank_account else ''
        return f'{self.month_name} {self.year}{acct}'

    @property
    def cashbook_balance(self):
        return (Decimal(str(self.opening_balance))
                + Decimal(str(self.outstanding_receipts))
                - Decimal(str(self.outstanding_payments)))

    @property
    def difference(self):
        return Decimal(str(self.closing_balance)) - self.cashbook_balance

    @property
    def is_balanced(self):
        return abs(self.difference) < Decimal('0.01')


# ---------------------------------------------------------------------------
# Reserves
# ---------------------------------------------------------------------------

class Reserve(db.Model):
    __tablename__ = 'reserves'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text, nullable=True)
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
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reason = db.Column(db.Text, nullable=False)
    minute_reference = db.Column(db.String(200), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])


# ---------------------------------------------------------------------------
# Fixed assets
# ---------------------------------------------------------------------------

class Asset(db.Model):
    __tablename__ = 'assets'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    # 'land', 'buildings', 'equipment', 'vehicles', 'infrastructure', 'other'
    category = db.Column(db.String(30), nullable=False, default='other')
    description = db.Column(db.Text, nullable=True)
    location = db.Column(db.String(200), nullable=True)
    acquisition_date = db.Column(db.Date, nullable=False)
    acquisition_cost = db.Column(db.Numeric(12, 2), nullable=False)
    # Depreciation (I&E basis)
    useful_life_years = db.Column(db.Integer, nullable=True)
    # 'none' (land/R&P), 'straight_line'
    depreciation_method = db.Column(db.String(20), nullable=False, default='none')
    # Insurance
    insured = db.Column(db.Boolean, default=True)
    insurance_value = db.Column(db.Numeric(12, 2), nullable=True)
    # Disposal
    is_disposed = db.Column(db.Boolean, default=False)
    disposal_date = db.Column(db.Date, nullable=True)
    disposal_proceeds = db.Column(db.Numeric(12, 2), nullable=True)
    disposal_reason = db.Column(db.Text, nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])

    CATEGORIES = ['land', 'buildings', 'equipment', 'vehicles', 'infrastructure', 'other']

    def annual_depreciation(self):
        if (self.depreciation_method == 'straight_line'
                and self.useful_life_years
                and self.useful_life_years > 0):
            return Decimal(str(self.acquisition_cost)) / self.useful_life_years
        return Decimal('0')

    def accumulated_depreciation(self, as_at=None):
        if as_at is None:
            as_at = date.today()
        if self.depreciation_method != 'straight_line' or not self.useful_life_years:
            return Decimal('0')
        end = self.disposal_date if self.is_disposed else as_at
        years = (end - self.acquisition_date).days / 365.25
        total = min(years, self.useful_life_years) * float(self.annual_depreciation())
        return Decimal(str(round(total, 2)))

    def net_book_value(self, as_at=None):
        return Decimal(str(self.acquisition_cost)) - self.accumulated_depreciation(as_at)


# ---------------------------------------------------------------------------
# Accruals / prepayments (I&E basis)
# ---------------------------------------------------------------------------

class Accrual(db.Model):
    """Year-end accruals, prepayments, debtors, creditors for I&E accounting."""
    __tablename__ = 'accruals'

    id = db.Column(db.Integer, primary_key=True)
    financial_year_id = db.Column(db.Integer, db.ForeignKey('financial_years.id'), nullable=False)
    # 'accrued_income','accrued_expenditure','prepayment','debtor','creditor'
    accrual_type = db.Column(db.String(30), nullable=False)
    budget_heading_id = db.Column(db.Integer, db.ForeignKey('budget_headings.id'), nullable=True)
    date = db.Column(db.Date, nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    description = db.Column(db.Text, nullable=False)
    counterparty = db.Column(db.String(200), nullable=True)
    is_reversed = db.Column(db.Boolean, default=False)
    reversed_at = db.Column(db.DateTime, nullable=True)
    reversed_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    reversed_by = db.relationship('User', foreign_keys=[reversed_by_id])
    heading = db.relationship('BudgetHeading', foreign_keys=[budget_heading_id])

    TYPE_LABELS = {
        'accrued_income': 'Accrued Income',
        'accrued_expenditure': 'Accrued Expenditure',
        'prepayment': 'Prepayment',
        'debtor': 'Debtor',
        'creditor': 'Creditor',
    }

    @property
    def type_label(self):
        return self.TYPE_LABELS.get(self.accrual_type, self.accrual_type)

    @property
    def is_asset(self):
        return self.accrual_type in ('accrued_income', 'prepayment', 'debtor')


# ---------------------------------------------------------------------------
# Grants
# ---------------------------------------------------------------------------

class Grant(db.Model):
    __tablename__ = 'grants'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    grantor = db.Column(db.String(200), nullable=False)
    # 'received' = grant to the council; 'awarded' = grant from the council
    grant_type = db.Column(db.String(20), nullable=False, default='received')
    awarded_amount = db.Column(db.Numeric(12, 2), nullable=False)
    award_date = db.Column(db.Date, nullable=True)
    expenditure_deadline = db.Column(db.Date, nullable=True)
    conditions = db.Column(db.Text, nullable=True)
    purpose = db.Column(db.Text, nullable=True)
    is_active = db.Column(db.Boolean, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    transactions = db.relationship('Transaction', back_populates='grant', lazy='dynamic')

    @property
    def received_amount(self):
        return sum(
            Decimal(str(t.net_amount))
            for t in self.transactions.filter_by(is_void=False, transaction_type='receipt').all()
        )

    @property
    def spent_amount(self):
        return sum(
            Decimal(str(t.net_amount))
            for t in self.transactions.filter_by(is_void=False, transaction_type='payment').all()
        )

    @property
    def unspent(self):
        return self.received_amount - self.spent_amount


# ---------------------------------------------------------------------------
# Recurring transactions (standing orders / direct debits)
# ---------------------------------------------------------------------------

class RecurringTransaction(db.Model):
    __tablename__ = 'recurring_transactions'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    transaction_type = db.Column(db.String(10), nullable=False)
    payee_payer = db.Column(db.String(200), nullable=False)
    description = db.Column(db.String(500), nullable=False)
    budget_heading_id = db.Column(db.Integer, db.ForeignKey('budget_headings.id'), nullable=False)
    bank_account_id = db.Column(db.Integer, db.ForeignKey('bank_accounts.id'), nullable=True)
    net_amount = db.Column(db.Numeric(12, 2), nullable=False)
    vat_amount = db.Column(db.Numeric(12, 2), nullable=False, default=0)
    vat_reclaimable = db.Column(db.Boolean, default=False)
    # 'monthly','quarterly','annual','weekly'
    frequency = db.Column(db.String(20), nullable=False, default='monthly')
    next_due_date = db.Column(db.Date, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_by_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    created_by = db.relationship('User', foreign_keys=[created_by_id])
    heading = db.relationship('BudgetHeading', foreign_keys=[budget_heading_id])
    bank_account = db.relationship('BankAccount', foreign_keys=[bank_account_id])

    @property
    def is_overdue(self):
        return self.next_due_date <= date.today() and self.is_active


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

class AuditLog(db.Model):
    """Immutable audit log — records are never updated or deleted."""
    __tablename__ = 'audit_logs'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    entity_type = db.Column(db.String(50), nullable=False)
    entity_id = db.Column(db.Integer, nullable=True)
    action = db.Column(db.String(50), nullable=False)
    description = db.Column(db.Text, nullable=False)
    reason = db.Column(db.Text, nullable=True)
    before_state = db.Column(db.Text, nullable=True)
    after_state = db.Column(db.Text, nullable=True)

    user = db.relationship('User', backref='audit_logs')


def log_action(user_id, entity_type, action, description,
               entity_id=None, reason=None, before=None, after=None):
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
