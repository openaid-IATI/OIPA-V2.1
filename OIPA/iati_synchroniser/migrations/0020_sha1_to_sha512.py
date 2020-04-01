# Generated by Django 2.0.13 on 2020-02-17 15:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('iati_synchroniser', '0019_rename_md5_to_sha1'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='dataset',
            name='validation_sha1',
        ),
        migrations.AddField(
            model_name='dataset',
            name='validation_sha512',
            field=models.CharField(blank=True, max_length=512, null=True),
        ),
    ]