import uuid

from django.db import migrations, models


def backfill_share_tokens(apps, schema_editor):
    TravelPlan = apps.get_model('travel', 'TravelPlan')
    for plan in TravelPlan.objects.all():
        plan.share_token = uuid.uuid4()
        plan.save(update_fields=['share_token'])


class Migration(migrations.Migration):

    dependencies = [
        ('travel', '0003_scheduleitem_alarm_enabled_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='travelplan',
            name='share_token',
            field=models.UUIDField(editable=False, null=True),
        ),
        migrations.RunPython(backfill_share_tokens, migrations.RunPython.noop),
        migrations.AlterField(
            model_name='travelplan',
            name='share_token',
            field=models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
        ),
    ]
