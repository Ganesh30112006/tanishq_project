"""What kind of document it was, and what the rules meant when someone ruled.

The pilot exists to find failure modes across the reports that actually
arrive, so a record that cannot distinguish a clean PDF from a photographed
page looks complete when it is not. And a ruling is an answer to a question:
if the question is later reworded, the old answers must not be silently
re-read as answers to the new one.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0006_shadow_reader_comparison'),
    ]

    operations = [
        migrations.AddField(
            model_name='readercomparison',
            name='report_class',
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name='readercomparison',
            name='text_source',
            field=models.CharField(blank=True, max_length=32),
        ),
        migrations.AddField(
            model_name='readerdisagreement',
            name='taxonomy_version',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddIndex(
            model_name='readercomparison',
            index=models.Index(fields=['report_class', 'text_source'], name='reports_rea_report__77a602_idx'),
        ),
    ]
