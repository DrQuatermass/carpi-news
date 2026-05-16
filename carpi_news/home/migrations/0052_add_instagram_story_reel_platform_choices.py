# Generated for Instagram Story + Reel auto-publishing feature
# Aggiunge anche 'facebook_story' come scelta canonica (oltre al legacy 'facebook_reel'
# che resta per compatibilita' con record gia' nel DB).

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0051_add_facebook_reel_platform_choice'),
    ]

    operations = [
        migrations.AlterField(
            model_name='socialpublicationlog',
            name='platform',
            field=models.CharField(
                choices=[
                    ('telegram', 'Telegram'),
                    ('facebook', 'Facebook'),
                    ('facebook_reel', 'Facebook Reel'),
                    ('facebook_story', 'Facebook Story'),
                    ('instagram', 'Instagram'),
                    ('instagram_story', 'Instagram Story'),
                    ('instagram_reel', 'Instagram Reel'),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
