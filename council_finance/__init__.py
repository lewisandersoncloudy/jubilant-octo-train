import os
from flask import Flask, redirect, url_for, render_template
from flask_login import LoginManager, current_user, login_required
from .models import db, User

login_manager = LoginManager()


def create_app():
    app = Flask(
        __name__,
        template_folder='../templates',
        static_folder='../static',
    )

    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-in-production')
    db_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'council_finance.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', f'sqlite:///{db_path}')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['WTF_CSRF_ENABLED'] = True
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50 MB upload limit

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'warning'

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .auth import auth_bp
    from .cashbook import cashbook_bp
    from .reconciliation import reconciliation_bp
    from .budget import budget_bp
    from .reserves import reserves_bp
    from .vat import vat_bp
    from .agar import agar_bp
    from .audit import audit_bp
    from .reports import reports_bp
    from .financial_years import financial_years_bp
    from .council_settings import council_settings_bp
    from .assets import assets_bp
    from .accruals import accruals_bp
    from .grants import grants_bp
    from .recurring import recurring_bp

    for bp in (auth_bp, cashbook_bp, reconciliation_bp, budget_bp,
               reserves_bp, vat_bp, agar_bp, audit_bp, reports_bp,
               financial_years_bp, council_settings_bp, assets_bp,
               accruals_bp, grants_bp, recurring_bp):
        app.register_blueprint(bp)

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return redirect(url_for('auth.login'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        from .models import FinancialYear, Transaction, BankReconciliation, CouncilSettings, RecurringTransaction
        from decimal import Decimal
        from datetime import date
        import calendar

        settings = CouncilSettings.query.first()
        fy = FinancialYear.query.filter_by(is_current=True).first()
        stats = {}
        month_status = []

        if fy:
            active_txns = fy.transactions.filter_by(is_void=False)
            receipts = sum(Decimal(str(t.net_amount)) + Decimal(str(t.vat_amount))
                           for t in active_txns.filter_by(transaction_type='receipt').all())
            payments = sum(Decimal(str(t.net_amount)) + Decimal(str(t.vat_amount))
                           for t in active_txns.filter_by(transaction_type='payment').all())
            stats = {
                'total_receipts': receipts,
                'total_payments': payments,
                'net_movement': receipts - payments,
                'transaction_count': active_txns.count(),
            }

            today = date.today()
            yr_start = fy.start_date
            for m_offset in range(12):
                mo = (yr_start.month - 1 + m_offset) % 12 + 1
                yr = yr_start.year + (yr_start.month - 1 + m_offset) // 12
                if date(yr, mo, 1) > today:
                    break
                recon = BankReconciliation.query.filter_by(
                    financial_year_id=fy.id, month=mo, year=yr
                ).first()
                txn_count = active_txns.filter(
                    Transaction.date >= date(yr, mo, 1),
                    Transaction.date <= date(yr, mo, calendar.monthrange(yr, mo)[1])
                ).count()
                month_status.append({
                    'month': mo,
                    'year': yr,
                    'label': f'{BankReconciliation.MONTH_NAMES[mo]} {yr}',
                    'txn_count': txn_count,
                    'reconciled': recon is not None and recon.is_complete,
                    'recon_id': recon.id if recon else None,
                })

        # Overdue recurring transactions
        overdue_recurring = RecurringTransaction.query.filter(
            RecurringTransaction.is_active == True,
            RecurringTransaction.next_due_date <= date.today()
        ).count()

        return render_template('dashboard.html',
                               fy=fy, stats=stats, month_status=month_status,
                               settings=settings, overdue_recurring=overdue_recurring)

    @app.context_processor
    def inject_globals():
        from .models import FinancialYear, CouncilSettings
        current_fy = FinancialYear.query.filter_by(is_current=True).first()
        settings = CouncilSettings.query.first()
        return dict(current_fy=current_fy, settings=settings)

    with app.app_context():
        db.create_all()
        _run_migrations(app)
        _seed_defaults()

    return app


def _run_migrations(app):
    """Add new columns to existing tables without dropping data."""
    db_uri = app.config['SQLALCHEMY_DATABASE_URI']
    if not db_uri.startswith('sqlite'):
        return  # Only needed for SQLite — use Alembic for Postgres/MySQL

    import sqlite3
    db_path = db_uri.replace('sqlite:///', '')
    if not db_path or db_path == ':memory:':
        return

    try:
        with sqlite3.connect(db_path) as conn:
            c = conn.cursor()

            def _add_col(table, col, defn):
                c.execute(f'PRAGMA table_info({table})')
                if col not in [r[1] for r in c.fetchall()]:
                    c.execute(f'ALTER TABLE {table} ADD COLUMN {col} {defn}')

            _add_col('transactions', 'bank_account_id', 'INTEGER REFERENCES bank_accounts(id)')
            _add_col('transactions', 'section_137', 'BOOLEAN NOT NULL DEFAULT 0')
            _add_col('transactions', 'grant_id', 'INTEGER REFERENCES grants(id)')
            _add_col('transactions', 'document_url', 'TEXT')
            _add_col('transactions', 'document_filename', 'TEXT')
            _add_col('bank_reconciliations', 'bank_account_id', 'INTEGER REFERENCES bank_accounts(id)')
            _add_col('budget_headings', 'is_section_137', 'BOOLEAN NOT NULL DEFAULT 0')
            conn.commit()
    except Exception:
        pass  # Table may not exist yet (first run) — db.create_all() handles it


def _seed_defaults():
    """Populate default data on first run."""
    from .models import User, BudgetHeading, FinancialYear, Reserve, CouncilSettings
    from datetime import date

    if not CouncilSettings.query.first():
        db.session.add(CouncilSettings(
            council_name='Our Parish Council',
            accounting_basis='receipts_payments',
        ))

    if not User.query.first():
        clerk = User(email='clerk@council.local', name='Council Clerk', role='clerk')
        clerk.set_password('changeme123')
        db.session.add(clerk)

    if not BudgetHeading.query.first():
        headings = [
            ('Precept', 'receipts', 1),
            ('Grants Received', 'receipts', 2),
            ('Interest Received', 'receipts', 3),
            ('CIL Receipts', 'receipts', 4),
            ('Other Income', 'receipts', 5),
            ('Clerk Salary & Pension', 'payments', 10),
            ('Administration', 'payments', 11),
            ('Insurance', 'payments', 12),
            ('Audit Fees', 'payments', 13),
            ('Subscriptions (NALC / SLCC)', 'payments', 14),
            ('Maintenance & Grounds', 'payments', 15),
            ('Grants Awarded', 'payments', 16),
            ('Section 137 Expenditure', 'payments', 17),
            ('Capital Expenditure', 'payments', 18),
            ('Other Expenditure', 'payments', 19),
        ]
        for name, cat, order in headings:
            is_s137 = name == 'Section 137 Expenditure'
            db.session.add(BudgetHeading(name=name, category=cat,
                                          sort_order=order, is_section_137=is_s137))

    if not FinancialYear.query.first():
        db.session.add(FinancialYear(
            label='2025/26',
            start_date=date(2025, 4, 1),
            end_date=date(2026, 3, 31),
            is_current=True,
        ))

    if not Reserve.query.first():
        db.session.add(Reserve(
            name='General Reserve',
            description='Unrestricted general reserve',
            is_general=True,
        ))

    db.session.commit()
