# trades/urls.py

from django.urls import path
from . import views

app_name = 'trades'

urlpatterns = [
    path('', views.index, name='index'),

    # Transactions
    path('transactions/', views.transaction_list, name='transaction_list'),
    path('transaction/add/', views.transaction_add, name='transaction_add'),

    # Aliases
    path('alias/', views.alias_list, name='alias_list'),
    path('alias/add/', views.alias_add, name='alias_add'),

    # Membership
    path('membership/', views.membership_list, name='membership_list'),

    # Wealth
    path('wealth/', views.wealth_list, name='wealth_list'),

    # Watchlist
    path('watchlist/', views.watchlist_list, name='watchlist_list'),

    # Charts
    path('charts/global-profit/', views.global_profit_chart, name='global_profit_chart'),

    # Account & Password Reset
    path('account/', views.account_page, name='account_page'),
    path('account/password-reset/', views.password_reset_request, name='password_reset_request'),

    # Signup, Login
    path('signup/', views.signup_view, name='signup_view'),
    path('login/', views.login_view, name='login_view'),

    # NEW: custom logout (GET allowed)
    path('logout/', views.logout_view, name='logout_view'),

    # Recent trades (all users)
    path('recent-trades/', views.recent_trades, name='recent_trades'),
]
