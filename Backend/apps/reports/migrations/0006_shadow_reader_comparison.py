"""The shadow dataset: where the two readers disagreed, and why.

Two tables that hold no clinical value and are read by no clinical code. They
exist so that the question "is the document service a better reader?" can be
answered with a record of real disagreements on real reports rather than with
a belief. Rows cascade with the report they describe.
"""

import django.db.models.deletion
import uuid
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0005_thyroid_and_electrolyte_report_classes'),
    ]

    operations = [
        migrations.CreateModel(
            name='ReaderComparison',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('public_id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('mode', models.CharField(max_length=12)),
                ('existing_outcome', models.CharField(max_length=20)),
                ('second_disposition', models.CharField(blank=True, max_length=20)),
                ('second_available', models.BooleanField(default=False)),
                ('unavailable_reason', models.CharField(blank=True, max_length=200)),
                ('existing_value_count', models.PositiveIntegerField(default=0)),
                ('second_value_count', models.PositiveIntegerField(default=0)),
                ('agreed', models.BooleanField(default=False)),
                ('detail', models.JSONField(blank=True, default=dict)),
                ('report', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='reader_comparisons', to='reports.report')),
            ],
            options={
                'db_table': 'reports_reader_comparison',
            },
        ),
        migrations.CreateModel(
            name='ReaderDisagreement',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('public_id', models.UUIDField(db_index=True, default=uuid.uuid4, editable=False, unique=True)),
                ('analyte', models.CharField(blank=True, max_length=120)),
                ('kind', models.CharField(choices=[('ONLY_EXISTING', 'Only the existing reader produced a value'), ('ONLY_SECOND', 'Only the second reader produced a value'), ('VALUE_DIFFERS', 'Both produced a value and they differ'), ('UNIT_DIFFERS', 'Same number, different unit'), ('NOT_PERSISTABLE', 'Second reader would not stand behind it'), ('DOCUMENT_UNREADABLE', 'Second reader could not read the document'), ('ROUTING_DIFFERS', 'The readers would route the report differently')], max_length=24)),
                ('existing_value', models.CharField(blank=True, max_length=64)),
                ('existing_unit', models.CharField(blank=True, max_length=32)),
                ('existing_state', models.CharField(blank=True, max_length=16)),
                ('second_value', models.CharField(blank=True, max_length=64)),
                ('second_unit', models.CharField(blank=True, max_length=32)),
                ('second_status', models.CharField(blank=True, max_length=16)),
                ('second_reason', models.CharField(blank=True, max_length=120)),
                ('second_persistable', models.BooleanField(default=False)),
                ('printed_label', models.CharField(blank=True, max_length=200)),
                ('excerpt', models.CharField(blank=True, max_length=300)),
                ('classification', models.CharField(choices=[('SAFE_IMPROVEMENT', 'The second reader was right'), ('SAFE_ABSTENTION', 'The second reader declined to guess'), ('PARSER_ERROR', 'The second reader misread the line'), ('NORMALIZATION_ERROR', 'The unit conversion was wrong'), ('REFERENCE_RANGE_DIFFERENCE', 'The readers used different reference intervals'), ('CONFLICT_DETECTION', 'The second reader found a real contradiction'), ('OCR_FAILURE', 'The text could not be recovered'), ('OLD_READER_ERROR', 'The existing pipeline was wrong'), ('UNKNOWN', 'Not yet classified')], default='UNKNOWN', max_length=28)),
                ('classified_by', models.CharField(blank=True, max_length=120)),
                ('classified_at', models.DateTimeField(blank=True, null=True)),
                ('classification_note', models.TextField(blank=True)),
                ('comparison', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='disagreements', to='reports.readercomparison')),
            ],
            options={
                'db_table': 'reports_reader_disagreement',
            },
        ),
        migrations.AddIndex(
            model_name='readercomparison',
            index=models.Index(fields=['mode', 'agreed'], name='reports_rea_mode_1b26d8_idx'),
        ),
        migrations.AddIndex(
            model_name='readercomparison',
            index=models.Index(fields=['created_at'], name='reports_rea_created_8e8fe4_idx'),
        ),
        migrations.AddIndex(
            model_name='readerdisagreement',
            index=models.Index(fields=['classification'], name='reports_rea_classif_346a04_idx'),
        ),
        migrations.AddIndex(
            model_name='readerdisagreement',
            index=models.Index(fields=['kind'], name='reports_rea_kind_48d5c7_idx'),
        ),
        migrations.AddIndex(
            model_name='readerdisagreement',
            index=models.Index(fields=['analyte'], name='reports_rea_analyte_1e235b_idx'),
        ),
    ]
