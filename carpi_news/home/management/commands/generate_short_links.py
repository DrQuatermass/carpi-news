from django.core.management.base import BaseCommand

from home.models import SocialPublicationLog
from home.share_links import build_short_share_url, get_or_create_short_link


class Command(BaseCommand):
    help = "Genera short link retroattivi per i SocialPublicationLog senza short_link."

    def handle(self, *args, **options):
        created_or_linked = 0
        logs = SocialPublicationLog.objects.filter(short_link__isnull=True).select_related('articolo')
        for log in logs.iterator():
            platform, medium = self._platform_medium(log.platform)
            short_link = get_or_create_short_link(log.articolo, platform, medium)
            log.short_link = short_link
            log.shared_url = build_short_share_url(log.articolo, platform, medium)
            log.save(update_fields=['short_link', 'shared_url'])
            created_or_linked += 1
        self.stdout.write(self.style.SUCCESS(f"Short link associati: {created_or_linked}"))

    @staticmethod
    def _platform_medium(platform: str) -> tuple[str, str]:
        mapping = {
            'facebook_story': ('facebook', 'reel'),
            'facebook_reel': ('facebook', 'reel'),
            'instagram_story': ('instagram', 'story'),
            'instagram_reel': ('instagram', 'reel'),
            'instagram': ('instagram', 'post'),
            'facebook': ('facebook', 'post'),
            'telegram': ('telegram', 'post'),
        }
        return mapping.get(platform, (platform, 'post'))
