from django.db import migrations, models


def backfill_instagram_media_ids(apps, schema_editor):
    SocialPublicationLog = apps.get_model("home", "SocialPublicationLog")
    for log in SocialPublicationLog.objects.exclude(instagram_media_id="").iterator():
        log.instagram_media_ids = [log.instagram_media_id]
        log.save(update_fields=["instagram_media_ids"])


def reverse_backfill(apps, schema_editor):
    SocialPublicationLog = apps.get_model("home", "SocialPublicationLog")
    SocialPublicationLog.objects.update(instagram_media_ids=[])


class Migration(migrations.Migration):

    dependencies = [
        ("home", "0053_social_link_tracking"),
    ]

    operations = [
        migrations.AddField(
            model_name="socialpublicationlog",
            name="instagram_media_ids",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.AddField(
            model_name="socialpublicationlog",
            name="updated_at",
            field=models.DateTimeField(auto_now=True),
        ),
        migrations.AddIndex(
            model_name="socialpublicationlog",
            index=models.Index(fields=["platform", "success", "-updated_at"], name="home_soc_plat_succ_upd_idx"),
        ),
        migrations.RunPython(backfill_instagram_media_ids, reverse_backfill),
    ]
