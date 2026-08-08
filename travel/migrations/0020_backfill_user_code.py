import secrets
import string

from django.db import migrations

USER_CODE_ALPHABET = string.ascii_letters + string.digits


def generate_code():
    part1 = ''.join(secrets.choice(USER_CODE_ALPHABET) for _ in range(4))
    part2 = ''.join(secrets.choice(USER_CODE_ALPHABET) for _ in range(4))
    return f'{part1}-{part2}'


def backfill_user_codes(apps, schema_editor):
    Profile = apps.get_model('travel', 'Profile')
    existing = set(Profile.objects.exclude(user_code__isnull=True).values_list('user_code', flat=True))
    for profile in Profile.objects.filter(user_code__isnull=True):
        code = generate_code()
        while code in existing:
            code = generate_code()
        existing.add(code)
        profile.user_code = code
        profile.save(update_fields=['user_code'])


def noop(apps, schema_editor):
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('travel', '0019_profile_user_code'),
    ]

    operations = [
        migrations.RunPython(backfill_user_codes, noop),
    ]
