# Generated by Django 2.2.15 on 2020-10-30 14:17

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('public_chat', '0002_auto_20201023_0454'),
    ]

    operations = [
        migrations.DeleteModel(
            name='PublicRoomChatMessageManager',
        ),
    ]
