# trades/forms.py

from django import forms
from django.utils import timezone
from .models import (
    Transaction, Alias, Item, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist
)

class TransactionManualItemForm(forms.Form):
    """
    Lets the user type an item name or short name to add a new transaction.
    """
    item_name = forms.CharField(label="Item Name", max_length=200)
    trans_type = forms.ChoiceField(choices=Transaction.TYPE_CHOICES, initial=Transaction.BUY)
    price = forms.FloatField()
    quantity = forms.FloatField()
    date_of_holding = forms.DateField(initial=timezone.now)

    def save(self):
        """
        Interpret price & quantity as 'millions'. E.g. if user enters 52.6,
        we store 52,600,000 in the DB.
        """
        name_input = self.cleaned_data['item_name'].strip()
        trans_type = self.cleaned_data['trans_type']
        # Convert to millions
        price = self.cleaned_data['price'] * 1_000_000
        quantity = self.cleaned_data['quantity'] * 1_000_000
        date_of_holding = self.cleaned_data['date_of_holding']

        alias = Alias.objects.filter(short_name__iexact=name_input).first()
        if not alias:
            alias = Alias.objects.filter(full_name__iexact=name_input).first()

        if alias:
            item_obj = Item.objects.filter(name__iexact=alias.full_name).first()
            if not item_obj:
                item_obj = Item.objects.create(name=alias.full_name)
        else:
            item_obj = Item.objects.filter(name__iexact=name_input).first()
            if not item_obj:
                item_obj = Item.objects.create(name=name_input)

        new_trans = Transaction.objects.create(
            item=item_obj,
            trans_type=trans_type,
            price=price,
            quantity=quantity,
            date_of_holding=date_of_holding
        )
        return new_trans


class TransactionEditForm(forms.Form):
    """
    A form for editing an existing Transaction, allowing the user to change
    item name, type, price, quantity, and date. We also treat user-entered
    price/quantity in "millions" for consistency with TransactionManualItemForm.
    """
    transaction_id = forms.IntegerField(widget=forms.HiddenInput())
    item_name = forms.CharField(label="Item Name", max_length=200)
    trans_type = forms.ChoiceField(choices=Transaction.TYPE_CHOICES)
    price = forms.FloatField()
    quantity = forms.FloatField()
    date_of_holding = forms.DateField()

    def load_initial(self, transaction):
        """Populate initial values from the given Transaction object, dividing by 1,000,000 to show 'millions'."""
        self.fields['transaction_id'].initial = transaction.id
        self.fields['item_name'].initial = transaction.item.name
        self.fields['trans_type'].initial = transaction.trans_type
        # Convert DB-stored price/qty into 'millions'
        self.fields['price'].initial = transaction.price / 1_000_000.0
        self.fields['quantity'].initial = transaction.quantity / 1_000_000.0
        self.fields['date_of_holding'].initial = transaction.date_of_holding

    def update_transaction(self):
        """
        Updates the existing Transaction with new data, again converting
        user-entered millions back to the full integer (e.g. 52.6 -> 52,600,000).
        """
        from .models import Transaction, Alias, Item

        trans_id = self.cleaned_data['transaction_id']
        transaction = Transaction.objects.get(id=trans_id)

        name_input = self.cleaned_data['item_name'].strip()
        trans_type = self.cleaned_data['trans_type']
        price = self.cleaned_data['price'] * 1_000_000
        quantity = self.cleaned_data['quantity'] * 1_000_000
        date_of_holding = self.cleaned_data['date_of_holding']

        # Same alias logic:
        alias = Alias.objects.filter(short_name__iexact=name_input).first()
        if not alias:
            alias = Alias.objects.filter(full_name__iexact=name_input).first()

        if alias:
            item_obj = Item.objects.filter(name__iexact=alias.full_name).first()
            if not item_obj:
                item_obj = Item.objects.create(name=alias.full_name)
        else:
            item_obj = Item.objects.filter(name__iexact=name_input).first()
            if not item_obj:
                item_obj = Item.objects.create(name=name_input)

        transaction.item = item_obj
        transaction.trans_type = trans_type
        transaction.price = price
        transaction.quantity = quantity
        transaction.date_of_holding = date_of_holding
        transaction.save()
        return transaction


class AliasForm(forms.ModelForm):
    class Meta:
        model = Alias
        fields = ['full_name', 'short_name', 'image_file']


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
