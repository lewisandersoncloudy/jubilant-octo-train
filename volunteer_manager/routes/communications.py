from flask import Blueprint, request, jsonify, abort, current_app
from datetime import datetime
from ..database import db
from ..models import MessageTemplate, Message, Volunteer, Event, Role

bp = Blueprint("communications", __name__)


@bp.get("/templates")
def list_templates():
    org_id = request.args.get("org_id", type=int)
    q = MessageTemplate.query
    if org_id:
        q = q.filter_by(organisation_id=org_id)
    return jsonify([t.to_dict() for t in q.all()])


@bp.post("/templates")
def create_template():
    data = request.get_json(force=True)
    if not data.get("organisation_id") or not data.get("name") or not data.get("body"):
        abort(400, description="organisation_id, name and body are required")
    t = MessageTemplate(
        organisation_id=data["organisation_id"],
        name=data["name"],
        template_type=data.get("template_type"),
        subject=data.get("subject"),
        body=data["body"],
    )
    db.session.add(t)
    db.session.commit()
    return jsonify(t.to_dict()), 201


@bp.patch("/templates/<int:template_id>")
def update_template(template_id):
    t = MessageTemplate.query.get_or_404(template_id)
    data = request.get_json(force=True)
    for field in ("name", "template_type", "subject", "body"):
        if field in data:
            setattr(t, field, data[field])
    db.session.commit()
    return jsonify(t.to_dict())


@bp.post("/send")
def send_message():
    """
    Send a message to one or more volunteers.
    Body:
      {
        "organisation_id": 1,
        "template_id": 2,           # optional
        "subject": "...",
        "body": "...",              # required if no template_id
        "scope": "individual|role|event",
        "scope_ref_id": 5,          # role_id or event_id
        "recipient_ids": [1, 2, 3], # for individual scope
        "sent_by": "coordinator@example.com"
      }
    """
    data = request.get_json(force=True)
    org_id = data.get("organisation_id")
    if not org_id:
        abort(400, description="organisation_id is required")

    scope = data.get("scope", "individual")
    template = None

    if data.get("template_id"):
        template = MessageTemplate.query.get_or_404(data["template_id"])

    body = data.get("body") or (template.body if template else None)
    subject = data.get("subject") or (template.subject if template else "(no subject)")
    if not body:
        abort(400, description="body or template_id is required")

    # Resolve recipients
    recipients: list[Volunteer] = []
    if scope == "individual":
        ids = data.get("recipient_ids", [])
        recipients = Volunteer.query.filter(Volunteer.id.in_(ids)).all()
    elif scope == "role":
        role_id = data.get("scope_ref_id")
        if role_id:
            from ..models import EventAssignment
            assigned_ids = {
                a.volunteer_id
                for a in EventAssignment.query.join(
                    Event, EventAssignment.event_id == Event.id
                ).filter(EventAssignment.event_role_id == role_id).all()
            }
            if not assigned_ids:
                # Fall back to volunteers who have this role skill
                role = Role.query.get(role_id)
                if role:
                    skill_ids = {sr.skill_id for sr in role.skill_requirements}
                    from ..models import VolunteerSkill
                    vol_ids = {
                        vs.volunteer_id
                        for vs in VolunteerSkill.query.filter(
                            VolunteerSkill.skill_id.in_(skill_ids)
                        ).all()
                    }
                    recipients = Volunteer.query.filter(
                        Volunteer.id.in_(vol_ids),
                        Volunteer.organisation_id == org_id,
                    ).all()
            else:
                recipients = Volunteer.query.filter(Volunteer.id.in_(assigned_ids)).all()
    elif scope == "event":
        event_id = data.get("scope_ref_id")
        if event_id:
            event = Event.query.get_or_404(event_id)
            recipient_ids = {a.volunteer_id for a in event.assignments}
            recipients = Volunteer.query.filter(Volunteer.id.in_(recipient_ids)).all()

    if not recipients:
        return jsonify({"error": "no_recipients", "message": "No recipients found."}), 400

    # Render and store messages (in a real deployment these would be queued/sent)
    sent = []
    for volunteer in recipients:
        context = {
            "volunteer_name": volunteer.full_name,
            "organisation_name": "your organisation",
        }
        rendered_subject, rendered_body = subject, body
        if template:
            rendered_subject, rendered_body = template.render(context)

        msg = Message(
            organisation_id=org_id,
            template_id=template.id if template else None,
            sent_by=data.get("sent_by"),
            channel=data.get("channel", "email"),
            recipient_email=volunteer.email,
            recipient_volunteer_id=volunteer.id,
            subject=rendered_subject,
            body=rendered_body,
            scope=scope,
            scope_ref_id=data.get("scope_ref_id"),
        )
        db.session.add(msg)
        sent.append(volunteer.email)

    db.session.commit()
    return jsonify({
        "sent": len(sent),
        "recipients": sent,
    })


@bp.get("/history")
def message_history():
    org_id = request.args.get("org_id", type=int)
    volunteer_id = request.args.get("volunteer_id", type=int)

    q = Message.query
    if org_id:
        q = q.filter_by(organisation_id=org_id)
    if volunteer_id:
        q = q.filter_by(recipient_volunteer_id=volunteer_id)

    messages = q.order_by(Message.sent_at.desc()).limit(200).all()
    return jsonify([m.to_dict() for m in messages])
