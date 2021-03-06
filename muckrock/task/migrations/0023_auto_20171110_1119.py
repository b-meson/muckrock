# -*- coding: utf-8 -*-
# Generated by Django 1.11.4 on 2017-11-10 11:19
from __future__ import unicode_literals

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('task', '0022_portaltask'),
    ]

    operations = [
        migrations.AddField(
            model_name='portaltask',
            name='reason',
            field=models.TextField(blank=True),
        ),
        migrations.AlterField(
            model_name='portaltask',
            name='category',
            field=models.CharField(choices=[(b'i', b'Incoming'), (b'a', b'Appeal'), (b'n', b'New'), (b'u', b'Update'), (b'f', b'Followup'), (b'p', b'Payment')], max_length=1),
        ),
    ]
