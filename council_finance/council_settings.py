from datetime import datetime
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, CouncilSettings, BankAccount, log_action

council_settings_bp = Blueprint('council_settings', __name__, url_prefix='/settings')


def _get_settings():
    s = CouncilSettings.query.first()
    if not s:
        s = CouncilSettings()
        db.session.add(s)
        db.session.commit()
    return s


@council_settings_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('dashboard'))

    settings = _get_settings()

    if request.method == 'POST':
        settings.council_name = request.form.get('council_name', '').strip() or 'Parish Council'
        settings.council_address = request.form.get('council_address', '').strip()
        new_basis = request.form.get('accounting_basis', 'receipts_payments')
        if new_basis not in ('receipts_payments', 'income_expenditure'):
            new_basis = 'receipts_payments'

        if settings.accounting_basis != new_basis:
            log_action(current_user.id, 'council_settings', 'change_accounting_basis',
                       f'Changed accounting basis from {settings.accounting_basis} to {new_basis}',
                       reason=request.form.get('basis_change_reason', ''))
        settings.accounting_basis = new_basis

        settings.vat_registered = request.form.get('vat_registered') == '1'
        settings.vat_number = request.form.get('vat_number', '').strip() or None

        # SharePoint config
        settings.sharepoint_site_url = request.form.get('sharepoint_site_url', '').strip() or None
        settings.sharepoint_library = request.form.get('sharepoint_library', '').strip() or 'Shared Documents'
        settings.sharepoint_folder = request.form.get('sharepoint_folder', '').strip() or 'Council Finance/Documents'
        settings.updated_at = datetime.utcnow()

        log_action(current_user.id, 'council_settings', 'update',
                   f'Updated council settings for {settings.council_name}')
        db.session.commit()
        flash('Settings saved.', 'success')
        return redirect(url_for('council_settings.index'))

    bank_accounts = BankAccount.query.order_by(BankAccount.is_primary.desc(), BankAccount.name).all()
    from . import sharepoint as sp
    return render_template('council_settings/index.html',
                           settings=settings, bank_accounts=bank_accounts,
                           sp_configured=sp.is_configured())


@council_settings_bp.route('/bank-accounts/add', methods=['POST'])
@login_required
def add_bank_account():
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('council_settings.index'))

    name = request.form.get('name', '').strip()
    account_type = request.form.get('account_type', 'current')
    bank_name = request.form.get('bank_name', '').strip()
    last4 = request.form.get('account_number_last4', '').strip()[-4:] or None
    sort_code = request.form.get('sort_code', '').strip() or None
    make_primary = request.form.get('is_primary') == '1'

    if not name:
        flash('Account name is required.', 'danger')
        return redirect(url_for('council_settings.index'))

    if make_primary:
        BankAccount.query.update({'is_primary': False})

    acct = BankAccount(
        name=name,
        account_type=account_type,
        bank_name=bank_name or None,
        account_number_last4=last4,
        sort_code=sort_code,
        is_primary=make_primary,
    )
    db.session.add(acct)
    db.session.flush()
    log_action(current_user.id, 'bank_account', 'create',
               f'Added bank account: {name}', entity_id=acct.id)
    db.session.commit()
    flash(f'Bank account "{name}" added.', 'success')
    return redirect(url_for('council_settings.index'))


@council_settings_bp.route('/bank-accounts/<int:acct_id>/deactivate', methods=['POST'])
@login_required
def deactivate_bank_account(acct_id):
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('council_settings.index'))

    acct = db.get_or_404(BankAccount, acct_id)
    acct.is_active = False
    log_action(current_user.id, 'bank_account', 'deactivate',
               f'Deactivated bank account: {acct.name}', entity_id=acct.id)
    db.session.commit()
    flash(f'Bank account "{acct.name}" deactivated.', 'success')
    return redirect(url_for('council_settings.index'))
