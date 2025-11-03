"""
Helper per tracciare l'utilizzo e i costi delle API esterne
"""
from decimal import Decimal
import logging

logger = logging.getLogger(__name__)


class APIUsageTracker:
    """Traccia automaticamente l'utilizzo delle API e calcola i costi in EUR"""

    # Tasso di cambio USD -> EUR (approssimativo, aggiornare periodicamente)
    USD_TO_EUR = 0.92

    # Prezzi Anthropic (USD per million tokens, convertiti in EUR)
    # https://www.anthropic.com/pricing#anthropic-api
    ANTHROPIC_PRICING_USD = {
        'claude-sonnet-4-20250514': {
            'input': 3.00,   # $3 per MTok
            'output': 15.00  # $15 per MTok
        },
        'claude-3-5-sonnet-20241022': {
            'input': 3.00,
            'output': 15.00
        },
        'claude-3-5-sonnet-20240620': {
            'input': 3.00,
            'output': 15.00
        },
        'claude-3-5-haiku-20241022': {
            'input': 1.00,   # $1 per MTok
            'output': 5.00   # $5 per MTok
        },
        'claude-3-opus-20240229': {
            'input': 15.00,
            'output': 75.00
        },
        'claude-3-sonnet-20240229': {
            'input': 3.00,
            'output': 15.00
        },
        'claude-3-haiku-20240307': {
            'input': 0.25,
            'output': 1.25
        },
    }

    # Converti prezzi in EUR
    ANTHROPIC_PRICING = {
        model: {
            'input': price['input'] * USD_TO_EUR,
            'output': price['output'] * USD_TO_EUR
        }
        for model, price in ANTHROPIC_PRICING_USD.items()
    }

    # Prezzo Google Custom Search API
    # https://developers.google.com/custom-search/v1/overview
    # 100 query gratuite al giorno, poi $5 per 1000 queries (€4.60 per 1000)
    GOOGLE_SEARCH_PRICING = {
        'free_daily_queries': 100,
        'per_query': 0.005 * USD_TO_EUR  # €0.0046 per query dopo le 100 gratuite
    }

    @classmethod
    def track_anthropic(cls, operation, model, input_tokens, output_tokens,
                       related_article=None, success=True, error_message=''):
        """
        Traccia una chiamata API Anthropic e calcola i costi

        Args:
            operation: Nome dell'operazione (es. 'generate_article', 'polish_content')
            model: Modello Claude utilizzato
            input_tokens: Numero di token di input
            output_tokens: Numero di token di output
            related_article: Istanza di Articolo correlato (opzionale)
            success: Se la chiamata è riuscita
            error_message: Messaggio di errore se fallita

        Returns:
            Istanza APIUsage creata
        """
        try:
            from home.models import APIUsage

            # Calcola i costi
            pricing = cls.ANTHROPIC_PRICING.get(model, cls.ANTHROPIC_PRICING['claude-3-5-sonnet-20241022'])

            # Costo = (tokens / 1,000,000) * prezzo_per_MTok
            input_cost = Decimal(str((input_tokens / 1_000_000) * pricing['input']))
            output_cost = Decimal(str((output_tokens / 1_000_000) * pricing['output']))

            # Arrotonda a 6 decimali
            input_cost = input_cost.quantize(Decimal('0.000001'))
            output_cost = output_cost.quantize(Decimal('0.000001'))

            # Crea il record
            usage = APIUsage.objects.create(
                api_type='anthropic',
                operation=operation,
                model=model,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                input_cost=input_cost,
                output_cost=output_cost,
                cost_total=input_cost + output_cost,
                related_article=related_article,
                success=success,
                error_message=error_message
            )

            logger.info(f"API Anthropic tracciata: {operation} - {model} - "
                       f"Input: {input_tokens} tok (€{input_cost}) - "
                       f"Output: {output_tokens} tok (€{output_cost}) - "
                       f"Totale: €{usage.cost_total}")

            return usage

        except Exception as e:
            logger.error(f"Errore nel tracciare utilizzo API Anthropic: {e}", exc_info=True)
            return None

    @classmethod
    def track_google_search(cls, operation, num_queries, related_article=None,
                           success=True, error_message=''):
        """
        Traccia una chiamata Google Custom Search API e calcola i costi

        Args:
            operation: Nome dell'operazione (es. 'web_search')
            num_queries: Numero di query eseguite
            related_article: Istanza di Articolo correlato (opzionale)
            success: Se la chiamata è riuscita
            error_message: Messaggio di errore se fallita

        Returns:
            Istanza APIUsage creata
        """
        try:
            from home.models import APIUsage

            # Calcola il costo
            cost_per_query = Decimal(str(cls.GOOGLE_SEARCH_PRICING['per_query']))
            total_cost = cost_per_query * num_queries

            # Arrotonda a 6 decimali
            total_cost = total_cost.quantize(Decimal('0.000001'))

            # Crea il record
            usage = APIUsage.objects.create(
                api_type='google_search',
                operation=operation,
                search_queries=num_queries,
                cost_total=total_cost,
                related_article=related_article,
                success=success,
                error_message=error_message
            )

            logger.info(f"API Google Search tracciata: {operation} - "
                       f"{num_queries} queries - €{total_cost}")

            return usage

        except Exception as e:
            logger.error(f"Errore nel tracciare utilizzo Google Search: {e}", exc_info=True)
            return None

    @classmethod
    def get_daily_stats(cls, date=None):
        """
        Ottieni statistiche di utilizzo per un giorno specifico

        Args:
            date: Data da analizzare (default: oggi)

        Returns:
            Dict con statistiche per tipo di API
        """
        try:
            from home.models import APIUsage
            from django.db.models import Sum, Count
            from django.utils import timezone
            from datetime import datetime, timedelta

            if date is None:
                date = timezone.now().date()
            elif isinstance(date, str):
                date = datetime.strptime(date, '%Y-%m-%d').date()

            # Query per il giorno specifico
            start_datetime = timezone.make_aware(datetime.combine(date, datetime.min.time()))
            end_datetime = start_datetime + timedelta(days=1)

            stats = {}

            # Stats Anthropic
            anthropic_stats = APIUsage.objects.filter(
                api_type='anthropic',
                timestamp__gte=start_datetime,
                timestamp__lt=end_datetime
            ).aggregate(
                total_calls=Count('id'),
                total_input_tokens=Sum('input_tokens'),
                total_output_tokens=Sum('output_tokens'),
                total_cost=Sum('cost_total')
            )

            stats['anthropic'] = {
                'calls': anthropic_stats['total_calls'] or 0,
                'input_tokens': anthropic_stats['total_input_tokens'] or 0,
                'output_tokens': anthropic_stats['total_output_tokens'] or 0,
                'cost': float(anthropic_stats['total_cost'] or 0)
            }

            # Stats Google Search
            google_stats = APIUsage.objects.filter(
                api_type='google_search',
                timestamp__gte=start_datetime,
                timestamp__lt=end_datetime
            ).aggregate(
                total_calls=Count('id'),
                total_queries=Sum('search_queries'),
                total_cost=Sum('cost_total')
            )

            stats['google_search'] = {
                'calls': google_stats['total_calls'] or 0,
                'queries': google_stats['total_queries'] or 0,
                'cost': float(google_stats['total_cost'] or 0)
            }

            # Totale
            stats['total'] = {
                'cost': stats['anthropic']['cost'] + stats['google_search']['cost']
            }

            return stats

        except Exception as e:
            logger.error(f"Errore nel calcolare statistiche giornaliere: {e}", exc_info=True)
            return None
