# trades/urls.py

from django.urls import path
from . import views

app_name = 'trades'

urlpatterns = [
    path('', views.index, name='index'),
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transaction/add/', views.transaction_add, name='transaction_add'),
    path('alias/', views.alias_list, name='alias_list'),
    path('alias/add/', views.alias_add, name='alias_add'),
    path('wealth/', views.wealth_list, name='wealth_list'),
    path('membership/', views.membership_list, name='membership_list'),
    path('watchlist/', views.watchlist_list, name='watchlist_list'),
    path('charts/global-profit/', views.global_profit_chart, name='global_profit_chart'),
    # ... and so on, for your other logic
]
