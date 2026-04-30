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

    for bp in (auth_bp, cashbook_bp, reconciliation_bp, budget_bp,
               reserves_bp, vat_bp, agar_bp, audit_bp, reports_bp,
               financial_years_bp):
        app.register_blueprint(bp)

    @app.route('/')
    def index():
        if current_user.is_authenticated:
            return redirect(url_for('dashboard'))
        return redirect(url_for('auth.login'))

    @app.route('/dashboard')
    @login_required
    def dashboard():
        from .models import FinancialYear, Transaction, BankReconciliation
        from decimal import Decimal
        from datetime import date
        import calendar

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

            # Build month-by-month workflow status for the current year
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

        return render_template('dashboard.html',
                               fy=fy, stats=stats, month_status=month_status)

    @app.context_processor
    def inject_globals():
        from .models import FinancialYear
        current_fy = FinancialYear.query.filter_by(is_current=True).first()
        return dict(current_fy=current_fy)

    with app.app_context():
        db.create_all()
        _seed_defaults()

    return app


def _seed_defaults():
    """Create default data on first run."""
    from .models import User, BudgetHeading, FinancialYear, Reserve
    from datetime import date

    # Default clerk account
    if not User.query.first():
        clerk = User(email='clerk@council.local', name='Council Clerk', role='clerk')
        clerk.set_password('changeme123')
        db.session.add(clerk)

    # Default budget headings
    if not BudgetHeading.query.first():
        headings = [
            ('Precept', 'receipts', 1),
            ('Grants Received', 'receipts', 2),
            ('Interest Received', 'receipts', 3),
            ('Other Income', 'receipts', 4),
            ('Administration', 'payments', 10),
            ('Clerk Salary', 'payments', 11),
            ('Insurance', 'payments', 12),
            ('Audit Fees', 'payments', 13),
            ('Subscriptions', 'payments', 14),
            ('Maintenance', 'payments', 15),
            ('Grants Paid', 'payments', 16),
            ('Capital Expenditure', 'payments', 17),
            ('Other Expenditure', 'payments', 18),
        ]
        for name, cat, order in headings:
            db.session.add(BudgetHeading(name=name, category=cat, sort_order=order))

    # Default financial year (2025/26)
    if not FinancialYear.query.first():
        fy = FinancialYear(
            label='2025/26',
            start_date=date(2025, 4, 1),
            end_date=date(2026, 3, 31),
            is_current=True,
        )
        db.session.add(fy)

    # General reserve
    if not Reserve.query.first():
        db.session.add(Reserve(
            name='General Reserve',
            description='Unrestricted general reserve',
            is_general=True,
        ))

    db.session.commit()
