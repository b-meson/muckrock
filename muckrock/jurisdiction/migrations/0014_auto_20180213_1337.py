# -*- coding: utf-8 -*-
# Generated by Django 1.11.4 on 2018-02-13 13:37
from __future__ import unicode_literals

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('jurisdiction', '0013_jurisdiction_aliases'),
    ]

    operations = [
        migrations.AddField(
            model_name='law',
            name='days',
            field=models.PositiveSmallIntegerField(blank=True, help_text=b'How many days do they have to respond?', null=True),
        ),
        migrations.AddField(
            model_name='law',
            name='has_appeal',
            field=models.BooleanField(default=True, help_text=b'Does this jurisdiction have an appeals process?'),
        ),
        migrations.AddField(
            model_name='law',
            name='intro',
            field=models.TextField(blank=True, help_text=b'Intro paragraph for request - usually includes the pertinant FOI law'),
        ),
        migrations.AddField(
            model_name='law',
            name='law_analysis',
            field=models.TextField(blank=True, help_text=b'Our analysis of the state FOIA law, as a part of FOI95.'),
        ),
        migrations.AddField(
            model_name='law',
            name='requires_proxy',
            field=models.BooleanField(default=False),
        ),
        migrations.AddField(
            model_name='law',
            name='use_business_days',
            field=models.BooleanField(default=True, help_text=b'Response time in business days (or calendar days)?'),
        ),
        migrations.AddField(
            model_name='law',
            name='waiver',
            field=models.TextField(blank=True, help_text=b'Optional - custom waiver paragraph if FOI law has special line for waivers'),
        ),
        migrations.AlterField(
            model_name='law',
            name='jurisdiction',
            field=models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, to='jurisdiction.Jurisdiction'),
        ),
    ]