# Generated for Facebook Reel auto-publishing feature

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0050_add_titolo_seo'),
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
                    ('instagram', 'Instagram'),
                ],
                db_index=True,
                max_length=20,
            ),
        ),
    ]
