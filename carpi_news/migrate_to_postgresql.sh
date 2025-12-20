#!/bin/bash
# Script per migrare da SQLite a PostgreSQL
# Eseguire dopo aver aumentato la RAM del server

set -e  # Exit on error

echo "=== Migrazione da SQLite a PostgreSQL ==="
echo ""

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 1. Verifica prerequisiti
echo -e "${YELLOW}[1/8] Verifica prerequisiti...${NC}"
if ! command -v psql &> /dev/null; then
    echo -e "${RED}PostgreSQL non installato!${NC}"
    echo "Installa con: sudo apt update && sudo apt install postgresql postgresql-contrib"
    exit 1
fi
echo -e "${GREEN}✓ PostgreSQL installato${NC}"

# 2. Backup database SQLite
echo -e "${YELLOW}[2/8] Backup database SQLite...${NC}"
BACKUP_DIR="/var/www/carpi-news/backups"
mkdir -p "$BACKUP_DIR"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
cp /var/www/carpi-news/carpi_news/db.sqlite3 "$BACKUP_DIR/db_sqlite_backup_$TIMESTAMP.sqlite3"
echo -e "${GREEN}✓ Backup salvato in: $BACKUP_DIR/db_sqlite_backup_$TIMESTAMP.sqlite3${NC}"

# 3. Crea database e utente PostgreSQL
echo -e "${YELLOW}[3/8] Creazione database PostgreSQL...${NC}"
DB_NAME="carpi_news_db"
DB_USER="carpi_news_user"
DB_PASSWORD=$(openssl rand -base64 32 | tr -d "=+/" | cut -c1-25)

sudo -u postgres psql <<EOF
-- Crea utente
CREATE USER $DB_USER WITH PASSWORD '$DB_PASSWORD';

-- Crea database
CREATE DATABASE $DB_NAME OWNER $DB_USER;

-- Grant privilegi
GRANT ALL PRIVILEGES ON DATABASE $DB_NAME TO $DB_USER;

-- Connetti al database e grant schema
\c $DB_NAME
GRANT ALL ON SCHEMA public TO $DB_USER;
EOF

echo -e "${GREEN}✓ Database '$DB_NAME' creato${NC}"
echo -e "${GREEN}✓ Utente '$DB_USER' creato${NC}"

# 4. Salva credenziali in file sicuro
echo -e "${YELLOW}[4/8] Salvataggio credenziali...${NC}"
CREDS_FILE="$BACKUP_DIR/postgresql_credentials_$TIMESTAMP.txt"
cat > "$CREDS_FILE" <<EOF
PostgreSQL Credentials
======================
Database: $DB_NAME
User: $DB_USER
Password: $DB_PASSWORD

DATABASE_URL per .env:
DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME
EOF
chmod 600 "$CREDS_FILE"
echo -e "${GREEN}✓ Credenziali salvate in: $CREDS_FILE${NC}"

# 5. Installa dipendenze Python
echo -e "${YELLOW}[5/8] Installazione dipendenze Python...${NC}"
cd /var/www/carpi-news
source venv/bin/activate
pip install psycopg2-binary dj-database-url
echo -e "${GREEN}✓ psycopg2-binary e dj-database-url installati${NC}"

# 6. Ferma monitor e Gunicorn
echo -e "${YELLOW}[6/8] Arresto servizi...${NC}"
cd carpi_news
python manage.py manage_db_monitors stop || true
sudo systemctl stop gunicorn
echo -e "${GREEN}✓ Servizi fermati${NC}"

# 7. Esporta dati da SQLite
echo -e "${YELLOW}[7/8] Esportazione dati da SQLite...${NC}"
EXPORT_FILE="$BACKUP_DIR/data_export_$TIMESTAMP.json"
python manage.py dumpdata --natural-foreign --natural-primary \
    --exclude auth.permission \
    --exclude contenttypes \
    --exclude admin.logentry \
    --exclude sessions.session \
    > "$EXPORT_FILE"
echo -e "${GREEN}✓ Dati esportati in: $EXPORT_FILE${NC}"

# 8. Configura PostgreSQL in .env
echo -e "${YELLOW}[8/8] Configurazione .env...${NC}"
if grep -q "^DATABASE_URL=" .env; then
    sed -i.bak "s|^DATABASE_URL=.*|DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME|" .env
else
    echo "DATABASE_URL=postgresql://$DB_USER:$DB_PASSWORD@localhost:5432/$DB_NAME" >> .env
fi
echo -e "${GREEN}✓ DATABASE_URL aggiunto a .env${NC}"

echo ""
echo -e "${GREEN}=== Preparazione completata! ===${NC}"
echo ""
echo -e "${YELLOW}PROSSIMI PASSI MANUALI:${NC}"
echo ""
echo "1. Esegui migrazioni su PostgreSQL:"
echo "   python manage.py migrate"
echo ""
echo "2. Importa dati da SQLite:"
echo "   python manage.py loaddata $EXPORT_FILE"
echo ""
echo "3. Verifica dati importati:"
echo "   python manage.py shell"
echo "   >>> from home.models import Articolo"
echo "   >>> Articolo.objects.count()"
echo ""
echo "4. Riavvia servizi:"
echo "   sudo systemctl start gunicorn"
echo "   python manage.py start_monitors"
echo ""
echo "5. Testa il sito web"
echo ""
echo -e "${RED}IMPORTANTE:${NC} Credenziali salvate in:"
echo "   $CREDS_FILE"
echo ""
echo -e "${YELLOW}In caso di problemi, ripristina con:${NC}"
echo "   1. Rimuovi DATABASE_URL da .env"
echo "   2. sudo systemctl restart gunicorn"
