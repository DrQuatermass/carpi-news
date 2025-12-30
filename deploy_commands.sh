#!/bin/bash
# Deploy script per aggiornamento pubbliredazionali in produzione

echo "=== DEPLOY PUBBLIREDAZIONALI - APPROVAZIONE ADMIN ==="
echo ""

# 1. Pull modifiche
echo "1. Pull modifiche da Git..."
cd /var/www/carpi-news
git pull origin banners

# 2. Attiva virtual environment
echo "2. Attivazione virtual environment..."
source venv/bin/activate

# 3. Verifica dipendenze (opzionale)
echo "3. Verifica dipendenze..."
cd carpi_news
pip install -r requirements.txt --quiet

# 4. NO MIGRATION NEEDED - usiamo campi esistenti (approved_by, approved_at)

# 5. Collect static files (se necessario)
echo "4. Collect static files..."
python manage.py collectstatic --noinput

# 6. Restart Django
echo "5. Restart servizio Django..."
sudo systemctl restart carpi_news

# 7. Setup cron job per processing pubbliredazionali
echo "6. Setup cron job..."
echo "NOTA: Il cron job deve essere configurato manualmente!"
echo "Esegui: crontab -e"
echo "Aggiungi la seguente riga:"
echo "*/15 * * * * cd /var/www/carpi-news/carpi_news && /var/www/carpi-news/venv/bin/python manage.py process_pending_pubbliredazionali >> /var/www/carpi-news/logs/pubbliredazionali_processor.log 2>&1"

echo ""
echo "=== DEPLOY COMPLETATO ==="
echo ""
echo "Verifiche da fare:"
echo "1. Controlla servizio: sudo systemctl status carpi_news"
echo "2. Controlla logs: tail -50 /var/www/carpi-news/logs/django.log"
echo "3. Configura cron job (vedi sopra)"
echo "4. Test workflow: crea pubbliredazionale → attendi generazione → approva admin → verifica email"
