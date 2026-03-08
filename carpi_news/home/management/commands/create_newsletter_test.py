"""
Crea articoli di test per verificare il funzionamento della newsletter.
"""
from django.core.management.base import BaseCommand
from django.utils.timezone import make_aware
from datetime import datetime, date, timedelta, time


class Command(BaseCommand):
    help = 'Crea articoli di test per la newsletter (da rimuovere dopo il test)'

    def handle(self, *args, **options):
        from home.models import Articolo

        oggi = date.today()
        domani = oggi + timedelta(days=1)
        oggi_ore_9 = make_aware(datetime.combine(oggi, time(9, 0)))
        oggi_ore_11 = make_aware(datetime.combine(oggi, time(11, 0)))
        oggi_ore_14 = make_aware(datetime.combine(oggi, time(14, 0)))
        ieri_ore_10 = make_aware(datetime.combine(oggi - timedelta(days=1), time(10, 0)))
        ieri_ore_16 = make_aware(datetime.combine(oggi - timedelta(days=1), time(16, 0)))

        articoli = [
            # --- OGGI ---
            dict(
                titolo="Nuovo piano di sviluppo per il centro storico di Carpi",
                sommario="Il Comune di Carpi ha presentato un ambizioso piano di riqualificazione del centro storico che prevede nuovi spazi verdi, piste ciclabili e aree pedonali. Il progetto, finanziato con fondi europei, coinvolgerà via Tre Febbraio e le vie adiacenti.",
                contenuto="<p>Il Comune di Carpi ha presentato stamattina un ambizioso piano di riqualificazione del centro storico...</p>",
                categoria="Attualità",
                approvato=True,
                data_pubblicazione=oggi_ore_9,
                views=142,
                fonte="https://www.comune.carpi.mo.it/",
            ),
            dict(
                titolo="Carpi FC: tre punti pesanti contro il Ravenna, la squadra vola in classifica",
                sommario="Una vittoria convincente per i biancorossi che si impongono 2-0 al Cabassi grazie alle reti di Saporetti e Cortesi. Con questi tre punti il Carpi consolida il terzo posto in classifica.",
                contenuto="<p>Tre punti d'oro per il Carpi FC nella sfida salvezza contro il Ravenna...</p>",
                categoria="Sport",
                approvato=True,
                data_pubblicazione=oggi_ore_11,
                views=89,
                fonte="https://www.carpicalcio.it/",
            ),
            dict(
                titolo="Scuole di Carpi: al via il progetto 'Lettura ad Alta Voce' nelle classi elementari",
                sommario="Dal prossimo lunedì partirà nelle scuole primarie del territorio il progetto promosso dalla biblioteca Loria: ogni settimana un'ora dedicata alla lettura ad alta voce con autori locali.",
                contenuto="<p>Un progetto innovativo arriva nelle classi elementari di Carpi...</p>",
                categoria="Attualità",
                approvato=True,
                data_pubblicazione=oggi_ore_14,
                views=34,
            ),
            # --- IERI ---
            dict(
                titolo="Aimag: bollette in calo del 12% grazie agli investimenti nelle rinnovabili",
                sommario="La multiutility carpigiana annuncia una riduzione delle tariffe del gas per i clienti domestici a partire dal primo aprile. Una buona notizia per le famiglie del distretto.",
                contenuto="<p>Buone notizie per le famiglie di Carpi e del distretto sul fronte delle bollette energetiche...</p>",
                categoria="Attualità",
                approvato=True,
                data_pubblicazione=ieri_ore_10,
                views=201,
            ),
            dict(
                titolo="Cronaca: incidente stradale in via Peruzzi, un ferito lieve",
                sommario="Scontro tra due auto nella mattinata di ieri in via Peruzzi all'altezza del semaforo. Sul posto carabinieri e 118. Il ferito è stato medicato al pronto soccorso e poi dimesso.",
                contenuto="<p>Incidente stradale nella mattinata di ieri in via Peruzzi...</p>",
                categoria="Cronaca",
                approvato=True,
                data_pubblicazione=ieri_ore_16,
                views=67,
            ),
            # --- CULTURA & EVENTI domani ---
            dict(
                titolo="Jazz al Castello: serata con il trio di Marco Ferretti",
                sommario="Domani sera alle 21:00 nella corte del Palazzo dei Pio il trio guidato dal pianista bolognese Marco Ferretti proporrà un repertorio di standard jazz e composizioni originali. Ingresso gratuito fino a esaurimento posti.",
                contenuto="<p>Un'altra serata di musica dal vivo anima il centro storico di Carpi...</p>",
                categoria="Cultura & Eventi",
                approvato=True,
                data_pubblicazione=oggi_ore_9,
                data_evento=domani,
                views=55,
            ),
            dict(
                titolo="Mostra fotografica 'Carpi ieri e oggi' — apertura straordinaria",
                sommario="Domani la Galleria Samaritani ospita l'apertura straordinaria della mostra fotografica dedicata ai cambiamenti urbani di Carpi dal dopoguerra ad oggi. Orario 10:00 - 19:00. Ingresso libero.",
                contenuto="<p>La mostra fotografica 'Carpi ieri e oggi' apre domani le sue porte...</p>",
                categoria="Cultura & Eventi",
                approvato=True,
                data_pubblicazione=ieri_ore_10,
                data_evento=domani,
                views=38,
            ),
        ]

        creati = 0
        for dati in articoli:
            titolo = dati['titolo']
            if Articolo.objects.filter(titolo=titolo).exists():
                self.stdout.write(f"  Già esistente: {titolo[:60]}")
                continue
            art = Articolo(**dati)
            art.save()
            # Forza data_pubblicazione (save() potrebbe sovrascriverla)
            Articolo.objects.filter(pk=art.pk).update(data_pubblicazione=dati['data_pubblicazione'])
            creati += 1
            self.stdout.write(f"  Creato [{dati['categoria']}]: {titolo[:60]}")

        self.stdout.write(self.style.SUCCESS(f"\nCreati {creati} articoli di test"))
        self.stdout.write("\nOra puoi testare:")
        self.stdout.write("  python manage.py send_newsletter --preview-only")
        self.stdout.write("  python manage.py send_newsletter --dry-run")
        self.stdout.write("  python manage.py send_newsletter")
        self.stdout.write("\nPer rimuoverli dopo il test:")
        self.stdout.write("  python manage.py create_newsletter_test --delete")

    def add_arguments(self, parser):
        parser.add_argument('--delete', action='store_true', help='Elimina gli articoli di test creati da questo comando')

    def handle(self, *args, **options):
        from home.models import Articolo

        titoli_test = [
            "Nuovo piano di sviluppo per il centro storico di Carpi",
            "Carpi FC: tre punti pesanti contro il Ravenna, la squadra vola in classifica",
            "Scuole di Carpi: al via il progetto 'Lettura ad Alta Voce' nelle classi elementari",
            "Aimag: bollette in calo del 12% grazie agli investimenti nelle rinnovabili",
            "Cronaca: incidente stradale in via Peruzzi, un ferito lieve",
            "Jazz al Castello: serata con il trio di Marco Ferretti",
            "Mostra fotografica 'Carpi ieri e oggi' — apertura straordinaria",
        ]

        if options['delete']:
            deleted, _ = Articolo.objects.filter(titolo__in=titoli_test).delete()
            self.stdout.write(self.style.SUCCESS(f"✅ Eliminati {deleted} articoli di test"))
            return

        oggi = date.today()
        domani = oggi + timedelta(days=1)
        oggi_ore_9 = make_aware(datetime.combine(oggi, time(9, 0)))
        oggi_ore_11 = make_aware(datetime.combine(oggi, time(11, 0)))
        oggi_ore_14 = make_aware(datetime.combine(oggi, time(14, 0)))
        ieri_ore_10 = make_aware(datetime.combine(oggi - timedelta(days=1), time(10, 0)))
        ieri_ore_16 = make_aware(datetime.combine(oggi - timedelta(days=1), time(16, 0)))

        articoli = [
            dict(
                titolo="Nuovo piano di sviluppo per il centro storico di Carpi",
                sommario="Il Comune di Carpi ha presentato un ambizioso piano di riqualificazione del centro storico che prevede nuovi spazi verdi, piste ciclabili e aree pedonali. Il progetto, finanziato con fondi europei, coinvolgerà via Tre Febbraio e le vie adiacenti.",
                contenuto="<p>Il Comune di Carpi ha presentato stamattina un ambizioso piano di riqualificazione del centro storico. Il progetto, approvato in consiglio comunale con ampia maggioranza, prevede la pedonalizzazione di alcune vie del centro, la creazione di nuove piste ciclabili e l'ampliamento delle aree verdi.</p><p>I lavori, finanziati con fondi europei del PNRR, inizieranno in primavera e si concluderanno entro la fine dell'anno.</p>",
                categoria="Attualità",
                approvato=True,
                data_pubblicazione=oggi_ore_9,
                views=142,
                fonte="https://www.comune.carpi.mo.it/",
            ),
            dict(
                titolo="Carpi FC: tre punti pesanti contro il Ravenna, la squadra vola in classifica",
                sommario="Una vittoria convincente per i biancorossi che si impongono 2-0 al Cabassi grazie alle reti di Saporetti e Cortesi. Con questi tre punti il Carpi consolida il terzo posto in classifica.",
                contenuto="<p>Tre punti d'oro per il Carpi FC nella sfida salvezza contro il Ravenna. Al Cabassi finisce 2-0 grazie alle reti di Saporetti al 23' e Cortesi al 67'. Una prestazione solida dei biancorossi che consolidano il terzo posto in classifica.</p>",
                categoria="Sport",
                approvato=True,
                data_pubblicazione=oggi_ore_11,
                views=89,
                fonte="https://www.carpicalcio.it/",
            ),
            dict(
                titolo="Scuole di Carpi: al via il progetto 'Lettura ad Alta Voce' nelle classi elementari",
                sommario="Dal prossimo lunedì partirà nelle scuole primarie del territorio il progetto promosso dalla biblioteca Loria: ogni settimana un'ora dedicata alla lettura ad alta voce con autori locali.",
                contenuto="<p>Un progetto innovativo arriva nelle classi elementari di Carpi. La biblioteca Loria, in collaborazione con l'Istituto Comprensivo Carpi 1, avvia il progetto 'Lettura ad Alta Voce' che coinvolgerà ogni settimana le classi del primo ciclo.</p>",
                categoria="Attualità",
                approvato=True,
                data_pubblicazione=oggi_ore_14,
                views=34,
            ),
            dict(
                titolo="Aimag: bollette in calo del 12% grazie agli investimenti nelle rinnovabili",
                sommario="La multiutility carpigiana annuncia una riduzione delle tariffe del gas per i clienti domestici a partire dal primo aprile. Una buona notizia per le famiglie del distretto.",
                contenuto="<p>Buone notizie per le famiglie di Carpi e del distretto sul fronte delle bollette energetiche. Aimag annuncia una riduzione del 12% delle tariffe del gas a partire dal primo aprile, frutto degli investimenti nelle energie rinnovabili degli ultimi due anni.</p>",
                categoria="Attualità",
                approvato=True,
                data_pubblicazione=ieri_ore_10,
                views=201,
            ),
            dict(
                titolo="Cronaca: incidente stradale in via Peruzzi, un ferito lieve",
                sommario="Scontro tra due auto nella mattinata di ieri in via Peruzzi all'altezza del semaforo. Sul posto carabinieri e 118. Il ferito è stato medicato al pronto soccorso e poi dimesso.",
                contenuto="<p>Incidente stradale nella mattinata di ieri in via Peruzzi. Alle ore 10:30 circa si sono scontrate due autovetture all'altezza del semaforo di via Peruzzi. Sul posto sono intervenuti i carabinieri e un'ambulanza del 118.</p><p>Il ferito, un uomo di 45 anni, è stato trasportato al pronto soccorso dell'ospedale Ramazzini con lesioni lievi e successivamente dimesso.</p>",
                categoria="Cronaca",
                approvato=True,
                data_pubblicazione=ieri_ore_16,
                views=67,
            ),
            dict(
                titolo="Jazz al Castello: serata con il trio di Marco Ferretti",
                sommario="Domani sera alle 21:00 nella corte del Palazzo dei Pio il trio guidato dal pianista bolognese Marco Ferretti proporrà un repertorio di standard jazz e composizioni originali. Ingresso gratuito fino a esaurimento posti.",
                contenuto="<p>Un'altra serata di musica dal vivo anima il centro storico di Carpi. Domani sera alle 21:00, nella suggestiva corte del Palazzo dei Pio, il Marco Ferretti Trio porterà un repertorio che spazia dagli standard del Great American Songbook alle composizioni originali del pianista bolognese.</p><p>L'ingresso è gratuito fino a esaurimento posti. In caso di maltempo l'evento si terrà nella sala Loria.</p>",
                categoria="Cultura & Eventi",
                approvato=True,
                data_pubblicazione=oggi_ore_9,
                data_evento=domani,
                views=55,
            ),
            dict(
                titolo="Mostra fotografica 'Carpi ieri e oggi' — apertura straordinaria",
                sommario="Domani la Galleria Samaritani ospita l'apertura straordinaria della mostra fotografica dedicata ai cambiamenti urbani di Carpi dal dopoguerra ad oggi. Orario 10:00 - 19:00. Ingresso libero.",
                contenuto="<p>La mostra fotografica 'Carpi ieri e oggi' apre domani le sue porte con un'apertura straordinaria. La Galleria Samaritani ospita una selezione di 80 fotografie che raccontano l'evoluzione urbana e sociale di Carpi dal dopoguerra ai giorni nostri.</p><p>L'ingresso è libero. Orario: 10:00 - 19:00.</p>",
                categoria="Cultura & Eventi",
                approvato=True,
                data_pubblicazione=ieri_ore_10,
                data_evento=domani,
                views=38,
            ),
        ]

        creati = 0
        for dati in articoli:
            titolo = dati['titolo']
            if Articolo.objects.filter(titolo=titolo).exists():
                self.stdout.write(f"  Già esistente: {titolo[:60]}")
                continue
            pub_date = dati.pop('data_pubblicazione')
            art = Articolo(**dati)
            art.save()
            Articolo.objects.filter(pk=art.pk).update(data_pubblicazione=pub_date, views=art.views)
            creati += 1
            self.stdout.write(f"  [OK] [{art.categoria}] {titolo[:60]}")

        self.stdout.write(self.style.SUCCESS(f"\nCreati {creati} articoli di test"))
        self.stdout.write("\nOra puoi testare con:")
        self.stdout.write("  python manage.py send_newsletter --preview-only")
        self.stdout.write("  python manage.py send_newsletter --dry-run")
        self.stdout.write("  python manage.py send_newsletter")
        self.stdout.write("\nPer rimuoverli dopo il test:")
        self.stdout.write("  python manage.py create_newsletter_test --delete")
