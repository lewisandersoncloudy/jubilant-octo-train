from ..database import db


class RoleSkillRequirement(db.Model):
    __tablename__ = "role_skill_requirements"

    role_id = db.Column(db.Integer, db.ForeignKey("roles.id"), primary_key=True)
    skill_id = db.Column(db.Integer, db.ForeignKey("skills.id"), primary_key=True)
    required = db.Column(db.Boolean, default=True)  # True=required, False=preferred

    skill = db.relationship("Skill")


class Role(db.Model):
    __tablename__ = "roles"

    id = db.Column(db.Integer, primary_key=True)
    organisation_id = db.Column(db.Integer, db.ForeignKey("organisations.id"), nullable=False)
    name = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text)
    capacity = db.Column(db.Integer)             # max volunteers in this role; None = unlimited
    requires_dbs = db.Column(db.Boolean, default=False)
    dbs_level = db.Column(db.String(20))         # basic | standard | enhanced
    active = db.Column(db.Boolean, default=True)

    organisation = db.relationship("Organisation", back_populates="roles")
    skill_requirements = db.relationship("RoleSkillRequirement", backref="role", cascade="all, delete-orphan")
    event_roles = db.relationship("EventRole", back_populates="role")

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "capacity": self.capacity,
            "requires_dbs": self.requires_dbs,
            "dbs_level": self.dbs_level,
            "active": self.active,
            "required_skills": [
                r.skill.to_dict() for r in self.skill_requirements if r.required
            ],
            "preferred_skills": [
                r.skill.to_dict() for r in self.skill_requirements if not r.required
            ],
        }
