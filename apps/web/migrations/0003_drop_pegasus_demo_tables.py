from django.db import migrations

# The Pegasus demo apps (`teams_example`, `pegasus.apps.employees`,
# `pegasus.apps.examples`) were removed from INSTALLED_APPS. Django never drops
# the tables of an app it no longer knows about, so this does, along with their
# rows in django_migrations so a fresh `migrate` and an old database agree.
#
# Not reversible: the demo data was sample data, and the apps that owned the
# tables are gone.
DEMO_APPS = ("teams_example", "pegasus_employees", "pegasus_examples")


class Migration(migrations.Migration):
    dependencies = [
        ("web", "0002_patch_third_party_tables"),
    ]

    operations = [
        migrations.RunSQL("DROP TABLE IF EXISTS teams_example_player", migrations.RunSQL.noop),
        migrations.RunSQL("DROP TABLE IF EXISTS pegasus_employees_employee", migrations.RunSQL.noop),
        migrations.RunSQL(
            [("DELETE FROM django_migrations WHERE app = ANY(%s)", [list(DEMO_APPS)])],
            migrations.RunSQL.noop,
        ),
    ]
