# trades/apps.py
from django.apps import AppConfig

class TradesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'trades'

    def ready(self):
        # This ensures signals are connected when the app loads
        import trades.signals