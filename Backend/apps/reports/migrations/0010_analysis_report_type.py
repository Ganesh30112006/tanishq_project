from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('reports', '0009_report_analysis'),
    ]

    operations = [
        migrations.AddField(
            model_name='reportanalysis',
            name='report_type',
            field=models.CharField(blank=True, max_length=20),
        ),
    ]
