# trades/forms.py

from django import forms
from .models import (
    Transaction, Alias, Item, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist
)

class TransactionForm(forms.ModelForm):
    class Meta:
        model = Transaction
        fields = ['item', 'trans_type', 'price', 'quantity', 'date_of_holding']

class ItemForm(forms.ModelForm):
    class Meta:
        model = Item
        fields = ['name']

class AliasForm(forms.ModelForm):
    class Meta:
        model = Alias
        fields = ['full_name', 'short_name', 'image_path']

class AccumulationPriceForm(forms.ModelForm):
    class Meta:
        model = AccumulationPrice
        fields = ['item', 'accumulation_price']

class TargetSellPriceForm(forms.ModelForm):
    class Meta:
        model = TargetSellPrice
        fields = ['item', 'target_sell_price']

class MembershipForm(forms.ModelForm):
    class Meta:
        model = Membership
        fields = ['account_name', 'membership_status', 'membership_end_date']

class WealthDataForm(forms.ModelForm):
    class Meta:
        model = WealthData
        fields = [
            'account_name', 'year', 'january','february','march','april','may',
            'june','july','august','september','october','november','december'
        ]

class WatchlistForm(forms.ModelForm):
    class Meta:
        model = Watchlist
        fields = [
            'name','desired_price','buy_or_sell','account_name',
            'wished_quantity','total_value','current_holding'
        ]
