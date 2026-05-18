from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0052_add_facebook_story_platform_choice'),
        ('home', '0052_add_instagram_story_reel_platform_choices'),
    ]

    operations = [
        migrations.CreateModel(
            name='ShortLink',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('platform', models.CharField(db_index=True, max_length=50)),
                ('medium', models.CharField(db_index=True, max_length=50)),
                ('token', models.CharField(db_index=True, max_length=12, unique=True)),
                ('clicks_count', models.PositiveIntegerField(default=0)),
                ('last_referer', models.URLField(blank=True, max_length=500)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('articolo', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='short_links', to='home.articolo')),
            ],
            options={
                'verbose_name': 'Short Link',
                'verbose_name_plural': 'Short Link',
                'ordering': ['-created_at'],
                'unique_together': {('articolo', 'platform', 'medium')},
            },
        ),
        migrations.AddField(
            model_name='socialpublicationlog',
            name='instagram_media_id',
            field=models.CharField(blank=True, db_index=True, max_length=100),
        ),
        migrations.AddField(
            model_name='socialpublicationlog',
            name='shared_url',
            field=models.URLField(blank=True, help_text='URL pubblicato effettivamente', max_length=500),
        ),
        migrations.AddField(
            model_name='socialpublicationlog',
            name='short_link',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='social_publications', to='home.shortlink'),
        ),
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
        migrations.CreateModel(
            name='InstagramAutoDMLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ig_user_id', models.CharField(db_index=True, max_length=100)),
                ('trigger_type', models.CharField(choices=[('story_reaction', 'Reazione Story'), ('story_reply', 'Risposta Story'), ('reel_comment', 'Commento Reel')], max_length=30)),
                ('trigger_value', models.CharField(blank=True, max_length=255)),
                ('media_id', models.CharField(blank=True, db_index=True, max_length=100)),
                ('dm_sent', models.BooleanField(default=False)),
                ('dm_error', models.TextField(blank=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('articolo', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='instagram_dm_logs', to='home.articolo')),
                ('short_link', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='instagram_dm_logs', to='home.shortlink')),
            ],
            options={
                'verbose_name': 'Log Instagram Auto-DM',
                'verbose_name_plural': 'Log Instagram Auto-DM',
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='InstagramOptOut',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('ig_user_id', models.CharField(db_index=True, max_length=100, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'verbose_name': 'Opt-out Instagram',
                'verbose_name_plural': 'Opt-out Instagram',
                'ordering': ['-created_at'],
            },
        ),
        migrations.AddIndex(
            model_name='shortlink',
            index=models.Index(fields=['articolo', 'platform', 'medium'], name='home_shortl_articol_b1efc0_idx'),
        ),
        migrations.AddIndex(
            model_name='instagramautodmlog',
            index=models.Index(fields=['ig_user_id', '-created_at'], name='home_instag_ig_user_bb81ab_idx'),
        ),
        migrations.AddIndex(
            model_name='instagramautodmlog',
            index=models.Index(fields=['media_id', '-created_at'], name='home_instag_media_i_b66ba9_idx'),
        ),
    ]
