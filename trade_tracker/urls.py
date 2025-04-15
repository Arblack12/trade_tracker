# trade_tracker/urls.py

from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from django.conf import settings
from django.conf.urls.static import static
# No need to import 'views' from 'trades' here

urlpatterns = [
    path('admin/', admin.site.urls),

    # Include your trades app URLs using the 'trades' namespace
    # This is where paths like '/login/', '/signup/', '/', '/wealth/', etc.,
    # defined in trades/urls.py will be found.
    path('', include(('trades.urls', 'trades'), namespace='trades')),

    # Global Password Reset URLs using Django's built-in views
    # These use templates from your 'trades' app directory
    path('password_reset/',
         auth_views.PasswordResetView.as_view(template_name='trades/password_reset.html'),
         name='password_reset'),
    path('password_reset/done/',
         auth_views.PasswordResetDoneView.as_view(template_name='trades/password_reset_done.html'),
         name='password_reset_done'),
    path('reset/<uidb64>/<token>/',
         auth_views.PasswordResetConfirmView.as_view(template_name='trades/password_reset_confirm.html'),
         name='password_reset_confirm'),
    path('reset/done/',
         auth_views.PasswordResetCompleteView.as_view(template_name='trades/password_reset_complete.html'),
         name='password_reset_complete'),

    # DO NOT define app-specific URLs like login here.
    # They belong in trades/urls.py and are handled by the include() above.
    # path('login/', views.your_login_view_function, name='login_view'), # <-- REMOVED THIS LINE
]

# Serve media files during development (when DEBUG=True)
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
    # Optional: Serve static files this way too, although runserver usually handles it.
    # Ensure you have 'django.contrib.staticfiles' in INSTALLED_APPS.
    # If you have defined STATIC_ROOT, you could add:
    # urlpatterns += static(settings.STATIC_URL, document_root=settings.STATIC_ROOT)