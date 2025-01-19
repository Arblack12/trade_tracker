# trades/forms.py

from django import forms
from django.utils import timezone
from .models import (
    Transaction, Alias, Item, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist
)

class TransactionManualItemForm(forms.Form):
    """
    Lets the user type an item name or short name.
    """
    item_name = forms.CharField(label="Item Name", max_length=200)
    trans_type = forms.ChoiceField(choices=Transaction.TYPE_CHOICES, initial=Transaction.BUY)
    price = forms.FloatField()
    quantity = forms.FloatField()
    date_of_holding = forms.DateField(initial=timezone.now)

    def save(self):
        """
        Look up or create the `Item` by matching either the alias short_name or item name.
        Then create a Transaction object.
        """
        name_input = self.cleaned_data['item_name'].strip()
        trans_type = self.cleaned_data['trans_type']
        price = self.cleaned_data['price']
        quantity = self.cleaned_data['quantity']
        date_of_holding = self.cleaned_data['date_of_holding']

        # First, see if there's an alias short_name or full_name ignoring case
        alias = Alias.objects.filter(short_name__iexact=name_input).first()
        if alias is None:
            alias = Alias.objects.filter(full_name__iexact=name_input).first()

        # If we found an alias, that gives us a full_name.  Then see if there's an Item with that name:
        if alias:
            item_obj = Item.objects.filter(name__iexact=alias.full_name).first()
            # If not found, create it:
            if not item_obj:
                item_obj = Item.objects.create(name=alias.full_name)
        else:
            # No alias matched.  Maybe the user typed the actual item name directly.  
            item_obj = Item.objects.filter(name__iexact=name_input).first()
            if not item_obj:
                # Create a new item:
                item_obj = Item.objects.create(name=name_input)

        # Now create the transaction:
        new_trans = Transaction.objects.create(
            item=item_obj,
            trans_type=trans_type,
            price=price,
            quantity=quantity,
            date_of_holding=date_of_holding
        )
        return new_trans


class AliasForm(forms.ModelForm):
    class Meta:
        model = Alias
        fields = ['full_name', 'short_name', 'image_file']  # or keep image_path if you like


# Keep your other forms as before...
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
