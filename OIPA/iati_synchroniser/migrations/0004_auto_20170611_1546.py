# -*- coding: utf-8 -*-
# Generated by Django 1.11.1 on 2017-06-11 15:46
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('iati_synchroniser', '0003_auto_20170602_1530'),
    ]

    operations = [
        migrations.AlterField(
            model_name='datasetnote',
            name='message',
            field=models.CharField(default=b'', max_length=150),
        ),
    ]