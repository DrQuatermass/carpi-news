from django.apps import AppConfig


class AdminPanelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'admin_panel'

    def ready(self):
        """Importa i signals quando l'app è pronta"""
        import admin_panel.signals  # noqa
