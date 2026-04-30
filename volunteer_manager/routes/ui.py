from flask import Blueprint, render_template, redirect, url_for
from ..database import db
from ..models import Organisation, Volunteer, Event, Role

bp = Blueprint("ui", __name__)


@bp.get("/")
def index():
    orgs = Organisation.query.all()
    if len(orgs) == 1:
        return redirect(url_for("ui.dashboard", org_id=orgs[0].id))
    return render_template("index.html", organisations=orgs)


@bp.get("/org/<int:org_id>/dashboard")
def dashboard(org_id):
    org = Organisation.query.get_or_404(org_id)
    return render_template("dashboard.html", org=org)


@bp.get("/org/<int:org_id>/volunteers")
def volunteers(org_id):
    org = Organisation.query.get_or_404(org_id)
    status_filter = "active"
    vols = Volunteer.query.filter_by(organisation_id=org_id, status=status_filter).order_by(
        Volunteer.last_name, Volunteer.first_name
    ).all()
    return render_template("volunteers/list.html", org=org, volunteers=vols, status_filter=status_filter)


@bp.get("/org/<int:org_id>/volunteers/<int:volunteer_id>")
def volunteer_detail(org_id, volunteer_id):
    org = Organisation.query.get_or_404(org_id)
    volunteer = Volunteer.query.filter_by(id=volunteer_id, organisation_id=org_id).first_or_404()
    return render_template("volunteers/detail.html", org=org, volunteer=volunteer)


@bp.get("/org/<int:org_id>/events")
def events(org_id):
    org = Organisation.query.get_or_404(org_id)
    upcoming = Event.query.filter(
        Event.organisation_id == org_id,
        Event.status.in_(["planned", "active"]),
    ).order_by(Event.start_datetime).all()
    past = Event.query.filter(
        Event.organisation_id == org_id,
        Event.status == "completed",
    ).order_by(Event.start_datetime.desc()).limit(20).all()
    return render_template("events/list.html", org=org, upcoming=upcoming, past=past)


@bp.get("/org/<int:org_id>/events/<int:event_id>")
def event_detail(org_id, event_id):
    org = Organisation.query.get_or_404(org_id)
    event = Event.query.filter_by(id=event_id, organisation_id=org_id).first_or_404()
    return render_template("events/detail.html", org=org, event=event)


@bp.get("/org/<int:org_id>/roles")
def roles(org_id):
    org = Organisation.query.get_or_404(org_id)
    role_list = Role.query.filter_by(organisation_id=org_id, active=True).order_by(Role.name).all()
    return render_template("roles/list.html", org=org, roles=role_list)


@bp.get("/org/<int:org_id>/compliance")
def compliance(org_id):
    org = Organisation.query.get_or_404(org_id)
    return render_template("compliance/overview.html", org=org)


@bp.get("/org/<int:org_id>/reports")
def reports(org_id):
    org = Organisation.query.get_or_404(org_id)
    return render_template("reports/index.html", org=org)
