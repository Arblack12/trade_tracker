from django.contrib import admin
from django.urls import path, include

urlpatterns = [
    path('admin/', admin.site.urls),
    # Include all the URL patterns in `trades/urls.py`
    path('', include('trades.urls')),  
    # Alternatively, you could use:
    # path('trades/', include('trades.urls')),
    # depending on how you want the URLs structured.
]
