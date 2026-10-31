from django.db import migrations

# The "Ask Koala" chat (`apps.chat`, `apps.ai`) was the Pegasus demo -- weather and
# admin-database agents with no access to budget data -- and was removed from
# INSTALLED_APPS. Django never drops the tables of an app it no longer knows
# about, so this does, along with its rows in django_migrations so a fresh
# `migrate` and an old database agree.
#
# Not reversible: the app that owned the tables is gone.


class Migration(migrations.Migration):
    dependencies = [
        ("web", "0003_drop_pegasus_demo_tables"),
    ]

    operations = [
        # Messages first: they point at their chat.
        migrations.RunSQL("DROP TABLE IF EXISTS chat_chatmessage", migrations.RunSQL.noop),
        migrations.RunSQL("DROP TABLE IF EXISTS chat_chat", migrations.RunSQL.noop),
        migrations.RunSQL(
            [("DELETE FROM django_migrations WHERE app = %s", ["chat"])],
            migrations.RunSQL.noop,
        ),
    ]
