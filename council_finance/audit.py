from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required
from .models import AuditLog, User

audit_bp = Blueprint('audit', __name__, url_prefix='/audit')


@audit_bp.route('/')
@login_required
def index():
    page = request.args.get('page', 1, type=int)
    entity_type = request.args.get('entity_type', '')
    user_id = request.args.get('user_id', '')

    query = AuditLog.query.order_by(AuditLog.timestamp.desc())
    if entity_type:
        query = query.filter_by(entity_type=entity_type)
    if user_id.isdigit():
        query = query.filter_by(user_id=int(user_id))

    logs = query.paginate(page=page, per_page=50, error_out=False)
    users = User.query.order_by(User.name).all()

    return render_template('audit/index.html',
                           logs=logs,
                           users=users,
                           filter_entity=entity_type,
                           filter_user=user_id)
