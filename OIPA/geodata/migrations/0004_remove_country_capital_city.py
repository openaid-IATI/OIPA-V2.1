# Generated by Django 2.0.6 on 2018-12-17 17:11

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('geodata', '0003_remove_region_added_manually'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='country',
            name='capital_city',
        ),
    ]