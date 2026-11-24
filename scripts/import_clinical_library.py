#!/usr/bin/env python3
"""
Import the PhysioExpertPro bilingual clinical library into a STAGING PostgreSQL DB.

Safety:
- Requires CLINICAL_IMPORT_TARGET=staging in the environment.
- Requires --confirm-staging --apply for writes.
- Refuses non-PostgreSQL databases.
- Creates only the new clinical_* tables; never drops or alters legacy tables.
- Insert-only: existing IDs are never overwritten by a repeat import.
"""

import argparse
import hashlib
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from app import app, db
from clinical_models import register_clinical_models

MODELS = register_clinical_models(db)


def read_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def validate(registry, library):
    diagnoses = registry.get("diagnoses", [])
    protocols = library.get("protocols", [])
    condition_ids = [d.get("condition_id") for d in diagnoses]
    protocol_ids = [p.get("protocol_id") for p in protocols]
    phase_ids, exercise_ids = [], []
    phase_count = exercise_count = 0

    errors = []
    if len(condition_ids) != len(set(condition_ids)):
        errors.append("Duplicate condition_id values in registry.")
    if len(protocol_ids) != len(set(protocol_ids)):
        errors.append("Duplicate protocol_id values in library.")

    known_conditions = set(condition_ids)
    for protocol in protocols:
        if protocol.get("condition_id") not in known_conditions:
            errors.append(
                f"Protocol {protocol.get('protocol_id')} references an unknown condition_id."
            )
        if not isinstance(protocol.get("content", {}).get("en"), dict):
            errors.append(f"Protocol {protocol.get('protocol_id')} has no English content object.")
        for phase in protocol.get("phases", []):
            phase_count += 1
            phase_ids.append(phase.get("phase_id"))
            for exercise in phase.get("exercises", []):
                exercise_count += 1
                exercise_ids.append(exercise.get("exercise_id"))

    for label, values in (
        ("phase_id", phase_ids),
        ("exercise_id", exercise_ids),
    ):
        if None in values or len(values) != len(set(values)):
            errors.append(f"Missing or duplicate {label} values.")

    expected = {"conditions": 80, "protocols": 86, "phases": 258, "exercises": 577}
    actual = {
        "conditions": len(diagnoses),
        "protocols": len(protocols),
        "phases": phase_count,
        "exercises": exercise_count,
    }
    if actual != expected:
        errors.append(f"Unexpected source counts: expected {expected}, got {actual}.")

    return errors, actual


def run_import(registry_path, protocols_path, apply_changes, confirm_staging):
    registry = read_json(registry_path)
    library = read_json(protocols_path)
    errors, counts = validate(registry, library)
    if errors:
        raise ValueError("Validation failed:\n- " + "\n- ".join(errors))

    registry_bytes = Path(registry_path).read_bytes()
    protocol_bytes = Path(protocols_path).read_bytes()
    source_hash = hashlib.sha256(registry_bytes + b"\0" + protocol_bytes).hexdigest()

    print("VALIDATION PASSED")
    print(json.dumps(counts, indent=2))
    print("Source SHA256:", source_hash)

    if not apply_changes:
        print("DRY RUN ONLY: no database writes were made.")
        return

    if not confirm_staging or os.environ.get("CLINICAL_IMPORT_TARGET", "").lower() != "staging":
        raise RuntimeError(
            "Blocked: set CLINICAL_IMPORT_TARGET=staging and pass --confirm-staging."
        )

    with app.app_context():
        if db.engine.dialect.name != "postgresql":
            raise RuntimeError("Blocked: importer accepts PostgreSQL only.")

        # Defense in depth: the database name itself must identify Staging.
        # This prevents a mistaken CLINICAL_IMPORT_TARGET value from authorizing Production.
        database_name = (db.engine.url.database or "").lower()
        if "staging" not in database_name:
            raise RuntimeError(
                "Blocked: connected PostgreSQL database name does not contain 'staging'. "
                "Verify the Staging DATABASE_URL before importing."
            )

        # Create only the new tables. No legacy table is dropped or altered.
        table_order = [
            MODELS["ClinicalCondition"].__table__,
            MODELS["ClinicalProtocol"].__table__,
            MODELS["ClinicalProtocolPhase"].__table__,
            MODELS["ClinicalExercise"].__table__,
            MODELS["ClinicalPhaseExercise"].__table__,
            MODELS["ClinicalImportBatch"].__table__,
            MODELS["ClinicalProtocolReview"].__table__,
        ]

        with db.engine.begin() as connection:
            for table in table_order:
                table.create(bind=connection, checkfirst=True)

        session = db.session
        try:
            existing_batch = MODELS["ClinicalImportBatch"].query.filter_by(
                source_hash=source_hash
            ).first()
            if existing_batch:
                print("This exact pair of JSON files was already imported. No changes made.")
                return

            inserted = {"conditions": 0, "protocols": 0, "phases": 0, "exercises": 0, "links": 0}

            for item in registry["diagnoses"]:
                if MODELS["ClinicalCondition"].query.get(item["condition_id"]):
                    continue
                session.add(MODELS["ClinicalCondition"](
                    condition_id=item["condition_id"],
                    canonical_name=item["canonical_name"],
                    specialty=item.get("specialty") or "General",
                    source_categories=item.get("source_categories", []),
                    aliases=item.get("aliases", []),
                    source_records=item.get("source_records", []),
                    record_relationship=item.get("record_relationship", "single_source_record"),
                    merge_review_required=bool(item.get("merge_review_required", False)),
                    age_group=item.get("age_group", "not_specified"),
                    content_status=item.get("content_status", "in_review"),
                    clinical_approval_status=item.get("clinical_approval_status", "not_approved"),
                    notes=item.get("notes"),
                ))
                inserted["conditions"] += 1
            session.flush()

            for protocol in library["protocols"]:
                if MODELS["ClinicalProtocol"].query.get(protocol["protocol_id"]):
                    continue
                content = protocol.get("content") or {}
                session.add(MODELS["ClinicalProtocol"](
                    protocol_id=protocol["protocol_id"],
                    condition_id=protocol["condition_id"],
                    source_record_id=protocol["source_record_id"],
                    source_condition_name=protocol["source_condition_name"],
                    specialty=protocol.get("specialty"),
                    default_language=protocol.get("default_language", "en"),
                    available_languages=protocol.get("available_languages", ["en"]),
                    translation_status=protocol.get("translation_status", {}),
                    content_en=content.get("en") or {},
                    content_ar=content.get("ar"),
                    content_status=protocol.get("content_status", "in_review"),
                    clinical_approval_status=protocol.get("clinical_approval_status", "not_approved"),
                    source_preservation=protocol.get("source_preservation", {}),
                ))
                inserted["protocols"] += 1
            session.flush()

            for protocol in library["protocols"]:
                for phase_index, phase in enumerate(protocol.get("phases", []), 1):
                    if MODELS["ClinicalProtocolPhase"].query.get(phase["phase_id"]):
                        continue
                    session.add(MODELS["ClinicalProtocolPhase"](
                        phase_id=phase["phase_id"],
                        protocol_id=protocol["protocol_id"],
                        phase_key=phase["phase_key"],
                        sort_order=phase_index,
                        content_en=phase.get("content", {}).get("en") or {},
                        content_ar=phase.get("content", {}).get("ar"),
                        translation_status=phase.get("translation_status", {}),
                    ))
                    inserted["phases"] += 1
            session.flush()

            # Exercises are globally unique after the ID repair in Clinical Protocols v1.0.1.
            exercise_map = {}
            for protocol in library["protocols"]:
                for phase in protocol.get("phases", []):
                    for exercise in phase.get("exercises", []):
                        ex_id = exercise["exercise_id"]
                        exercise_map[ex_id] = exercise
            for ex_id, exercise in exercise_map.items():
                if MODELS["ClinicalExercise"].query.get(ex_id):
                    continue
                session.add(MODELS["ClinicalExercise"](
                    exercise_id=ex_id,
                    content_en=exercise.get("content", {}).get("en") or {},
                    content_ar=exercise.get("content", {}).get("ar"),
                    translation_status=exercise.get("translation_status", {}),
                    clinical_review_status=exercise.get("clinical_review_status", "in_review"),
                ))
                inserted["exercises"] += 1
            session.flush()

            for protocol in library["protocols"]:
                for phase in protocol.get("phases", []):
                    for order, exercise in enumerate(phase.get("exercises", []), 1):
                        exists = MODELS["ClinicalPhaseExercise"].query.filter_by(
                            phase_id=phase["phase_id"], sort_order=order
                        ).first()
                        if exists:
                            continue
                        session.add(MODELS["ClinicalPhaseExercise"](
                            phase_id=phase["phase_id"],
                            exercise_id=exercise["exercise_id"],
                            sort_order=order,
                        ))
                        inserted["links"] += 1

            session.flush()
            session.add(MODELS["ClinicalImportBatch"](
                source_hash=source_hash,
                source_registry_file=os.path.basename(registry_path),
                source_protocol_file=os.path.basename(protocols_path),
                conditions_seen=counts["conditions"],
                protocols_seen=counts["protocols"],
                phases_seen=counts["phases"],
                exercises_seen=counts["exercises"],
                imported_at=datetime.now(timezone.utc).replace(tzinfo=None),
            ))
            session.commit()
            print("IMPORT COMPLETED")
            print(json.dumps(inserted, indent=2))
            print("All new content remains in_review / not_approved.")
        except Exception:
            session.rollback()
            raise


def main():
    parser = argparse.ArgumentParser(description="Import PhysioExpertPro clinical library.")
    parser.add_argument("--registry", default="data/master_diagnosis_registry.json")
    parser.add_argument("--protocols", default="data/clinical_protocols.json")
    parser.add_argument("--apply", action="store_true", help="Perform database writes.")
    parser.add_argument("--confirm-staging", action="store_true", help="Confirm target is Staging.")
    args = parser.parse_args()

    run_import(
        args.registry,
        args.protocols,
        apply_changes=args.apply,
        confirm_staging=args.confirm_staging,
    )


if __name__ == "__main__":
    main()

