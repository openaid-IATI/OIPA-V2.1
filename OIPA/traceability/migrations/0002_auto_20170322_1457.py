# -*- coding: utf-8 -*-
# Generated by Django 1.10.6 on 2017-03-22 14:57
from __future__ import unicode_literals

from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        ('traceability', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='chain',
            name='last_updated',
            field=models.DateTimeField(default=django.utils.timezone.now),
        ),
    ]
