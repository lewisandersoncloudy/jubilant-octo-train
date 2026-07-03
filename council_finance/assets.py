from datetime import date, datetime
from decimal import Decimal
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from .models import db, Asset, log_action

assets_bp = Blueprint('assets', __name__, url_prefix='/assets')


@assets_bp.route('/')
@login_required
def index():
    active = Asset.query.filter_by(is_disposed=False).order_by(Asset.category, Asset.name).all()
    disposed = Asset.query.filter_by(is_disposed=True).order_by(Asset.disposal_date.desc()).all()
    total_cost = sum(Decimal(str(a.acquisition_cost)) for a in active)
    total_nbv = sum(a.net_book_value() for a in active)
    total_insured = sum(Decimal(str(a.insurance_value)) for a in active if a.insurance_value)
    return render_template('assets/index.html',
                           active=active, disposed=disposed,
                           total_cost=total_cost, total_nbv=total_nbv,
                           total_insured=total_insured)


@assets_bp.route('/add', methods=['GET', 'POST'])
@login_required
def add():
    if not current_user.can_edit:
        flash('Only the Clerk / RFO can add assets.', 'danger')
        return redirect(url_for('assets.index'))

    if request.method == 'POST':
        errors = []
        name = request.form.get('name', '').strip()
        category = request.form.get('category', 'other')
        description = request.form.get('description', '').strip()
        location = request.form.get('location', '').strip()
        date_str = request.form.get('acquisition_date', '')
        cost_str = request.form.get('acquisition_cost', '').strip()
        dep_method = request.form.get('depreciation_method', 'none')
        life_str = request.form.get('useful_life_years', '').strip()
        insured = request.form.get('insured') == '1'
        ins_val_str = request.form.get('insurance_value', '').strip()

        if not name:
            errors.append('Asset name is required.')
        if category not in Asset.CATEGORIES:
            errors.append('Invalid category.')

        try:
            acq_date = date.fromisoformat(date_str)
        except (ValueError, AttributeError):
            errors.append('Invalid acquisition date.')
            acq_date = date.today()

        try:
            cost = Decimal(cost_str)
            if cost <= 0:
                errors.append('Acquisition cost must be positive.')
        except Exception:
            errors.append('Invalid acquisition cost.')
            cost = Decimal('0')

        life = None
        if dep_method == 'straight_line':
            try:
                life = int(life_str)
                if life <= 0:
                    errors.append('Useful life must be a positive number of years.')
            except (ValueError, TypeError):
                errors.append('Useful life years is required for straight-line depreciation.')

        ins_val = None
        if insured and ins_val_str:
            try:
                ins_val = Decimal(ins_val_str)
            except Exception:
                errors.append('Invalid insurance value.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('assets/add.html', form=request.form)

        asset = Asset(
            name=name,
            category=category,
            description=description or None,
            location=location or None,
            acquisition_date=acq_date,
            acquisition_cost=cost,
            depreciation_method=dep_method,
            useful_life_years=life,
            insured=insured,
            insurance_value=ins_val,
            created_by_id=current_user.id,
        )
        db.session.add(asset)
        db.session.flush()
        log_action(current_user.id, 'asset', 'create',
                   f'Added asset: {name} (cost £{cost:,.2f})', entity_id=asset.id)
        db.session.commit()
        flash(f'Asset "{name}" added to the register.', 'success')
        return redirect(url_for('assets.index'))

    return render_template('assets/add.html', form={})


@assets_bp.route('/<int:asset_id>')
@login_required
def view(asset_id):
    asset = db.get_or_404(Asset, asset_id)
    return render_template('assets/view.html', asset=asset)


@assets_bp.route('/<int:asset_id>/dispose', methods=['GET', 'POST'])
@login_required
def dispose(asset_id):
    if not current_user.can_edit:
        flash('Access denied.', 'danger')
        return redirect(url_for('assets.index'))

    asset = db.get_or_404(Asset, asset_id)
    if asset.is_disposed:
        flash('Asset is already disposed.', 'warning')
        return redirect(url_for('assets.view', asset_id=asset_id))

    if request.method == 'POST':
        date_str = request.form.get('disposal_date', '')
        proceeds_str = request.form.get('disposal_proceeds', '0').strip() or '0'
        reason = request.form.get('disposal_reason', '').strip()

        errors = []
        try:
            disp_date = date.fromisoformat(date_str)
        except (ValueError, AttributeError):
            errors.append('Invalid disposal date.')
            disp_date = date.today()

        try:
            proceeds = Decimal(proceeds_str)
        except Exception:
            errors.append('Invalid disposal proceeds.')
            proceeds = Decimal('0')

        if not reason:
            errors.append('Disposal reason is required.')

        if errors:
            for e in errors:
                flash(e, 'danger')
            return render_template('assets/dispose.html', asset=asset, form=request.form)

        asset.is_disposed = True
        asset.disposal_date = disp_date
        asset.disposal_proceeds = proceeds
        asset.disposal_reason = reason
        log_action(current_user.id, 'asset', 'dispose',
                   f'Disposed asset: {asset.name}', entity_id=asset.id,
                   reason=reason,
                   after={'disposal_date': str(disp_date), 'proceeds': str(proceeds)})
        db.session.commit()
        flash(f'Asset "{asset.name}" marked as disposed.', 'success')
        return redirect(url_for('assets.index'))

    return render_template('assets/dispose.html', asset=asset, form={})
