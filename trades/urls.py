# trades/urls.py
from django.urls import path
from . import views

app_name = 'trades'

urlpatterns = [
    path('', views.index, name='index'),

    # Optional separate transaction pages:
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transaction/add/', views.transaction_add, name='transaction_add'),

    # ALIAS (now unified on alias_list; alias_add simply redirects)
    path('alias/', views.alias_list, name='alias_list'),
    path('alias/add/', views.alias_add, name='alias_add'),

    # MEMBERSHIP
    path('membership/', views.membership_list, name='membership_list'),

    # WEALTH
    path('wealth/', views.wealth_list, name='wealth_list'),

    # WATCHLIST
    path('watchlist/', views.watchlist_list, name='watchlist_list'),

    # CHART
    path('charts/global-profit/', views.global_profit_chart, name='global_profit_chart'),

    # ACCOUNT + PASSWORD RESET
    path('account/', views.account_page, name='account_page'),
    path('account/password-reset/', views.password_reset_request, name='password_reset_request'),
]
