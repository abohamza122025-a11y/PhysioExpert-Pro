"""
PhysioExpertPro clinical content models.
Import this module from app.py after `db = SQLAlchemy(app)` is initialized.
The register function is idempotent within a single Python process.
"""

def register_clinical_models(db):
    # Guard against accidental duplicate class registration during development reloads.
    existing = getattr(db, "_physio_clinical_models", None)
    if existing:
        return existing

    class ClinicalCondition(db.Model):
        __tablename__ = "clinical_conditions"
        condition_id = db.Column(db.String(120), primary_key=True)
        canonical_name = db.Column(db.JSON, nullable=False)
        specialty = db.Column(db.String(120), nullable=False)
        source_categories = db.Column(db.JSON, nullable=False, default=list)
        aliases = db.Column(db.JSON, nullable=False, default=list)
        source_records = db.Column(db.JSON, nullable=False, default=list)
        record_relationship = db.Column(db.String(50), nullable=False)
        merge_review_required = db.Column(db.Boolean, nullable=False, default=False)
        age_group = db.Column(db.String(80), nullable=False, default="not_specified")
        content_status = db.Column(db.String(30), nullable=False, default="in_review")
        clinical_approval_status = db.Column(db.String(30), nullable=False, default="not_approved")
        notes = db.Column(db.Text)

    class ClinicalProtocol(db.Model):
        __tablename__ = "clinical_protocols"
        protocol_id = db.Column(db.String(160), primary_key=True)
        condition_id = db.Column(
            db.String(120),
            db.ForeignKey("clinical_conditions.condition_id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
        source_record_id = db.Column(db.String(80), nullable=False, unique=True)
        source_condition_name = db.Column(db.String(240), nullable=False)
        specialty = db.Column(db.String(120))
        default_language = db.Column(db.String(5), nullable=False, default="en")
        available_languages = db.Column(db.JSON, nullable=False, default=lambda: ["en"])
        translation_status = db.Column(db.JSON, nullable=False, default=dict)
        content_en = db.Column(db.JSON, nullable=False)
        content_ar = db.Column(db.JSON)
        content_status = db.Column(db.String(30), nullable=False, default="in_review")
        clinical_approval_status = db.Column(db.String(30), nullable=False, default="not_approved")
        source_preservation = db.Column(db.JSON, nullable=False, default=dict)

    class ClinicalProtocolPhase(db.Model):
        __tablename__ = "clinical_protocol_phases"
        phase_id = db.Column(db.String(200), primary_key=True)
        protocol_id = db.Column(
            db.String(160),
            db.ForeignKey("clinical_protocols.protocol_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
        phase_key = db.Column(db.String(30), nullable=False)
        sort_order = db.Column(db.Integer, nullable=False)
        content_en = db.Column(db.JSON, nullable=False)
        content_ar = db.Column(db.JSON)
        translation_status = db.Column(db.JSON, nullable=False, default=dict)

    class ClinicalExercise(db.Model):
        __tablename__ = "clinical_exercises"
        exercise_id = db.Column(db.String(160), primary_key=True)
        content_en = db.Column(db.JSON, nullable=False)
        content_ar = db.Column(db.JSON)
        translation_status = db.Column(db.JSON, nullable=False, default=dict)
        clinical_review_status = db.Column(db.String(30), nullable=False, default="in_review")

    class ClinicalPhaseExercise(db.Model):
        __tablename__ = "clinical_phase_exercises"
        id = db.Column(db.Integer, primary_key=True)
        phase_id = db.Column(
            db.String(200),
            db.ForeignKey("clinical_protocol_phases.phase_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
        exercise_id = db.Column(
            db.String(160),
            db.ForeignKey("clinical_exercises.exercise_id", ondelete="RESTRICT"),
            nullable=False,
            index=True,
        )
        sort_order = db.Column(db.Integer, nullable=False)
        __table_args__ = (
            db.UniqueConstraint("phase_id", "sort_order", name="uq_clinical_phase_exercise_order"),
        )

    class ClinicalImportBatch(db.Model):
        __tablename__ = "clinical_import_batches"
        id = db.Column(db.Integer, primary_key=True)
        source_hash = db.Column(db.String(64), nullable=False, unique=True)
        source_registry_file = db.Column(db.String(255), nullable=False)
        source_protocol_file = db.Column(db.String(255), nullable=False)
        conditions_seen = db.Column(db.Integer, nullable=False, default=0)
        protocols_seen = db.Column(db.Integer, nullable=False, default=0)
        phases_seen = db.Column(db.Integer, nullable=False, default=0)
        exercises_seen = db.Column(db.Integer, nullable=False, default=0)
        imported_at = db.Column(db.DateTime, nullable=False)

    class ClinicalProtocolReview(db.Model):
        __tablename__ = "clinical_protocol_reviews"
        id = db.Column(db.Integer, primary_key=True)
        protocol_id = db.Column(
            db.String(160),
            db.ForeignKey("clinical_protocols.protocol_id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        )
        reviewer = db.Column(db.String(150))
        review_status = db.Column(db.String(30), nullable=False, default="pending")
        comments = db.Column(db.Text)
        reviewed_at = db.Column(db.DateTime)

    models = {
        "ClinicalCondition": ClinicalCondition,
        "ClinicalProtocol": ClinicalProtocol,
        "ClinicalProtocolPhase": ClinicalProtocolPhase,
        "ClinicalExercise": ClinicalExercise,
        "ClinicalPhaseExercise": ClinicalPhaseExercise,
        "ClinicalImportBatch": ClinicalImportBatch,
        "ClinicalProtocolReview": ClinicalProtocolReview,
    }
    db._physio_clinical_models = models
    return models
