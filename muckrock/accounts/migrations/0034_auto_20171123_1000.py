# -*- coding: utf-8 -*-
# Generated by Django 1.11.4 on 2017-11-23 10:00
from __future__ import unicode_literals

from django.conf import settings
import django.core.files.storage
from django.db import migrations, models
import django.db.models.deletion
import easy_thumbnails.fields


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('accounts', '0033_auto_20171103_1713'),
    ]

    operations = [
        migrations.CreateModel(
            name='RecurringDonation',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('email', models.EmailField(max_length=254)),
                ('amount', models.PositiveIntegerField()),
                ('customer_id', models.CharField(max_length=255)),
                ('subscription_id', models.CharField(max_length=255, unique=True)),
                ('payment_failed', models.BooleanField(default=False)),
                ('active', models.BooleanField(default=True)),
                ('created_datetime', models.DateTimeField(auto_now_add=True)),
                ('deactivated_datetime', models.DateTimeField(blank=True, null=True)),
                ('user', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='donations', to=settings.AUTH_USER_MODEL)),
            ],
        ),
    ]
