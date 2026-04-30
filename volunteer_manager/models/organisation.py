from datetime import datetime
from ..database import db


class Organisation(db.Model):
    __tablename__ = "organisations"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), nullable=False)
    type = db.Column(db.String(50))          # council, charity, community_hub, etc.
    address = db.Column(db.Text)
    contact_email = db.Column(db.String(200))
    contact_phone = db.Column(db.String(50))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    volunteers = db.relationship("Volunteer", back_populates="organisation", lazy="dynamic")
    roles = db.relationship("Role", back_populates="organisation", lazy="dynamic")
    events = db.relationship("Event", back_populates="organisation", lazy="dynamic")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "type": self.type,
            "address": self.address,
            "contact_email": self.contact_email,
            "contact_phone": self.contact_phone,
        }
