"""Default expected-report schemas (spec section 14).

Seeded by a data migration. Values are normalized-unit ranges (the pipeline
converts extracted values to canonical units first). Ranges are deliberately
wide plausibility bounds, not clinical reference ranges.
"""
from __future__ import annotations

from apps.common.enums import ReportClass

DEFAULT_SCHEMAS: list[dict] = [
    {
        "report_class": ReportClass.GLUCOSE,
        "version": 1,
        "definition": {
            "required_fields": ["glucose"],
            "optional_fields": [],
            "aliases": {"fasting glucose": "glucose", "fbs": "glucose"},
            "accepted_units": {"glucose": ["mg/dL", "mmol/L"]},
            "validation_rules": {"glucose": {"min": 1.0, "max": 60.0, "unit": "mmol/L"}},
            "expected_sections": ["CHEMISTRY"],
            "temporal_requirements": {"collected_at": "required"},
        },
    },
    {
        "report_class": ReportClass.HBA1C,
        "version": 1,
        "definition": {
            "required_fields": ["hba1c"],
            "optional_fields": [],
            "aliases": {"a1c": "hba1c", "glycated hemoglobin": "hba1c"},
            "accepted_units": {"hba1c": ["%", "mmol/mol"]},
            "validation_rules": {"hba1c": {"min": 20.0, "max": 195.0, "unit": "mmol/mol"}},
            "expected_sections": ["CHEMISTRY"],
            "temporal_requirements": {"collected_at": "required"},
        },
    },
    {
        "report_class": ReportClass.LIPID,
        "version": 1,
        "definition": {
            "required_fields": ["cholesterol", "hdl", "ldl", "triglycerides"],
            "optional_fields": [],
            "aliases": {
                "total cholesterol": "cholesterol",
                "hdl cholesterol": "hdl",
                "ldl cholesterol": "ldl",
                "tg": "triglycerides",
            },
            "accepted_units": {k: ["mg/dL", "mmol/L"] for k in ("cholesterol", "hdl", "ldl", "triglycerides")},
            "validation_rules": {
                "cholesterol": {"min": 1.0, "max": 20.0, "unit": "mmol/L"},
                "hdl": {"min": 0.1, "max": 5.0, "unit": "mmol/L"},
                "ldl": {"min": 0.1, "max": 15.0, "unit": "mmol/L"},
                "triglycerides": {"min": 0.1, "max": 30.0, "unit": "mmol/L"},
            },
            "expected_sections": ["LIPID PANEL"],
            "temporal_requirements": {"collected_at": "required"},
        },
    },
    {
        "report_class": ReportClass.CBC,
        "version": 1,
        "definition": {
            "required_fields": ["hemoglobin", "wbc", "platelets"],
            "optional_fields": [],
            "aliases": {"hb": "hemoglobin", "hgb": "hemoglobin", "plt": "platelets"},
            "accepted_units": {"hemoglobin": ["g/dL", "g/L"]},
            "validation_rules": {
                "hemoglobin": {"min": 20.0, "max": 250.0, "unit": "g/L"},
            },
            "expected_sections": ["COMPLETE BLOOD COUNT"],
            "temporal_requirements": {"collected_at": "required"},
        },
    },
]
