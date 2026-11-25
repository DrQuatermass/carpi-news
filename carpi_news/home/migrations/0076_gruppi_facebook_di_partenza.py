from django.db import migrations, models


# Gruppi da cui si apre la finestra del post: gli altri si scelgono su Facebook
# con "Aggiungi gruppi". Sono i quattro che avevano portato piu' lettori.
PARTENZE = ['vivi-carpi', 'sei-di-carpi-se', 'sei-di-carpi-se-2', 'se-sei-di-carpi']


def imposta_partenze(apps, schema_editor):
    GruppoFacebook = apps.get_model('home', 'GruppoFacebook')
    CondivisioneGruppo = apps.get_model('home', 'CondivisioneGruppo')

    CondivisioneGruppo.objects.all().delete()
    GruppoFacebook.objects.update(attivo=False, ordine=0)
    for posizione, slug in enumerate(PARTENZE, start=1):
        GruppoFacebook.objects.filter(slug=slug).update(attivo=True, ordine=posizione)


class Migration(migrations.Migration):

    dependencies = [
        ('home', '0075_articolo_reel_tono'),
    ]

    operations = [
        migrations.AddField(
            model_name='gruppofacebook',
            name='ordine',
            field=models.PositiveSmallIntegerField(default=0, help_text='Posizione del pulsante nella pagina di condivisione (1 = primo)'),
        ),
        migrations.RunPython(imposta_partenze, migrations.RunPython.noop),
        migrations.AlterModelOptions(
            name='gruppofacebook',
            options={'ordering': ['ordine', 'nome'], 'verbose_name': 'Gruppo Facebook di partenza', 'verbose_name_plural': 'Gruppi Facebook di partenza'},
        ),
        migrations.RemoveField(
            model_name='gruppofacebook',
            name='come_pagina',
        ),
        migrations.RemoveField(
            model_name='gruppofacebook',
            name='comune',
        ),
        migrations.RemoveField(
            model_name='gruppofacebook',
            name='parole_chiave',
        ),
        migrations.RemoveField(
            model_name='gruppofacebook',
            name='slug',
        ),
        migrations.AlterField(
            model_name='gruppofacebook',
            name='attivo',
            field=models.BooleanField(default=True, help_text='Se spento, il gruppo non compare tra i pulsanti'),
        ),
    ]
