# -*- coding: utf-8 -*-
# Generated by Django 1.10.6 on 2017-03-28 15:41
from __future__ import unicode_literals

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('iati_organisation', '0002_organisation_type'),
    ]

    operations = [
        migrations.AddField(
            model_name='organisation',
            name='normalized_organisation_identifier',
            field=models.CharField(db_index=True, default=django.utils.timezone.now, max_length=150),
            preserve_default=False,
        ),
    ]
