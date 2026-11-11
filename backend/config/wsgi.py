import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
application = get_wsgi_application()

from apps.core.startup import log_startup  # noqa: E402  (needs the settings loaded above)

log_startup("API")
