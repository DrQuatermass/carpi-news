from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("home", "0059_extend_article_image_field_lengths"),
    ]

    operations = [
        migrations.AddField(
            model_name="articolo",
            name="foto_valida",
            field=models.BooleanField(
                default=True,
                help_text="False se la verifica dell'URL esterno in foto e' fallita (validata all'ingest, non al render)",
            ),
        ),
    ]
