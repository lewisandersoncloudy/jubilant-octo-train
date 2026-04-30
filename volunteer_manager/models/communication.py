from datetime import datetime
from ..database import db


class MessageTemplate(db.Model):
    __tablename__ = "message_templates"

    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisations.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    template_type = db.Column(db.String(50))  # joining | reminder | follow_up | thanks | dbs_expiry | training_expiry
    subject = db.Column(db.String(300))
    body = db.Column(db.Text, nullable=False)
    # Supported placeholders: {{volunteer_name}}, {{event_name}}, {{event_date}}, {{organisation_name}}
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "template_type": self.template_type,
            "subject": self.subject,
            "body": self.body,
        }

    def render(self, context: dict) -> tuple[str, str]:
        """Return (rendered_subject, rendered_body) with placeholders substituted."""
        subject = self.subject or ""
        body = self.body or ""
        for key, value in context.items():
            placeholder = "{{" + key + "}}"
            subject = subject.replace(placeholder, str(value))
            body = body.replace(placeholder, str(value))
        return subject, body


class Message(db.Model):
    __tablename__ = "messages"

    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisations.id"), nullable=False)
    template_id = db.Column(db.Integer, db.ForeignKey("message_templates.id"))
    sent_by = db.Column(db.String(200))
    channel = db.Column(db.String(20), default="email")   # email | sms
    recipient_email = db.Column(db.String(200))
    recipient_volunteer_id = db.Column(db.Integer, db.ForeignKey("volunteers.id"))
    subject = db.Column(db.String(300))
    body = db.Column(db.Text)
    sent_at = db.Column(db.DateTime, default=datetime.utcnow)
    status = db.Column(db.String(20), default="sent")     # sent | delivered | failed | bounced
    # Scope: individual | role | event
    scope = db.Column(db.String(20), default="individual")
    scope_ref_id = db.Column(db.Integer)                  # role_id or event_id when scope != individual

    recipient = db.relationship("Volunteer")
    template = db.relationship("MessageTemplate")

    def to_dict(self):
        return {
            "id": self.id,
            "channel": self.channel,
            "recipient_email": self.recipient_email,
            "subject": self.subject,
            "sent_at": self.sent_at.isoformat() if self.sent_at else None,
            "status": self.status,
            "scope": self.scope,
        }
