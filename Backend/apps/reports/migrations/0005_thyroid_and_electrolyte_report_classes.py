"""Widen ReportClass with THYROID and ELECTROLYTES.

Choices only - no column changes. The document-intelligence schemas now cover
thyroid function and serum electrolytes, and the two vocabularies are kept
aligned so a classified report is never stored as OTHER simply because Django
had no name for it.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0004_alter_reporttest_state'),
    ]

    operations = [
        migrations.AlterField(
            model_name='report',
            name='class_hint',
            field=models.CharField(blank=True, choices=[('CBC', 'Complete blood count'), ('LIPID', 'Lipid profile'), ('GLUCOSE', 'Glucose'), ('HBA1C', 'HbA1c'), ('LIVER', 'Liver function'), ('KIDNEY', 'Kidney function'), ('THYROID', 'Thyroid function'), ('ELECTROLYTES', 'Serum electrolytes'), ('URINALYSIS', 'Urinalysis'), ('PATHOLOGY', 'Pathology'), ('RADIOLOGY', 'Radiology'), ('PRESCRIPTION', 'Prescription'), ('DISCHARGE', 'Discharge summary'), ('CLINICAL_NOTE', 'Clinical note'), ('OTHER', 'Other / unclassified')], help_text='Report type asserted by the uploader; verified against the schema', max_length=20),
        ),
        migrations.AlterField(
            model_name='report',
            name='report_class',
            field=models.CharField(blank=True, choices=[('CBC', 'Complete blood count'), ('LIPID', 'Lipid profile'), ('GLUCOSE', 'Glucose'), ('HBA1C', 'HbA1c'), ('LIVER', 'Liver function'), ('KIDNEY', 'Kidney function'), ('THYROID', 'Thyroid function'), ('ELECTROLYTES', 'Serum electrolytes'), ('URINALYSIS', 'Urinalysis'), ('PATHOLOGY', 'Pathology'), ('RADIOLOGY', 'Radiology'), ('PRESCRIPTION', 'Prescription'), ('DISCHARGE', 'Discharge summary'), ('CLINICAL_NOTE', 'Clinical note'), ('OTHER', 'Other / unclassified')], max_length=20),
        ),
        migrations.AlterField(
            model_name='reportschema',
            name='report_class',
            field=models.CharField(choices=[('CBC', 'Complete blood count'), ('LIPID', 'Lipid profile'), ('GLUCOSE', 'Glucose'), ('HBA1C', 'HbA1c'), ('LIVER', 'Liver function'), ('KIDNEY', 'Kidney function'), ('THYROID', 'Thyroid function'), ('ELECTROLYTES', 'Serum electrolytes'), ('URINALYSIS', 'Urinalysis'), ('PATHOLOGY', 'Pathology'), ('RADIOLOGY', 'Radiology'), ('PRESCRIPTION', 'Prescription'), ('DISCHARGE', 'Discharge summary'), ('CLINICAL_NOTE', 'Clinical note'), ('OTHER', 'Other / unclassified')], max_length=20),
        ),
    ]
