"""What abstaining costs.

Extraction is schema-driven, so a document the classifier will not name yields
nothing at all. That is the safe choice and it has a price, and the price has
to be measured rather than assumed: a policy that routes every multi-panel
report to a person is only proportionate if such reports are rare.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0007_shadow_pilot_stratification'),
    ]

    operations = [
        migrations.AddField(
            model_name='readercomparison',
            name='classification_reason',
            field=models.CharField(blank=True, max_length=40),
        ),
        migrations.AddField(
            model_name='readercomparison',
            name='values_forgone',
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddIndex(
            model_name='readercomparison',
            index=models.Index(fields=['classification_reason'], name='reports_rea_classif_48d0a9_idx'),
        ),
    ]
