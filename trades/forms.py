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
    Transaction types limited to Buy, Sell, Instant Buy, Instant Sell.
    """
    item_name = forms.CharField(label="Item Name", max_length=200, widget=forms.TextInput(attrs={'placeholder': 'Item Short or Full Name'}))
    # Keep trans_type, but we'll hide it and set via buttons in template
    trans_type = forms.ChoiceField(choices=[], widget=forms.HiddenInput) # Initially empty, set in __init__
    price = forms.FloatField(label="Price (millions)")
    quantity = forms.FloatField(label="Quantity")  # NO LONGER in millions
    date_of_holding = forms.DateField(initial=timezone.now, widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter choices for this form
        self.fields['trans_type'].choices = [
            (Transaction.BUY, 'Buy'),
            (Transaction.SELL, 'Sell'),
            (Transaction.INSTANT_BUY, 'Instant Buy'),
            (Transaction.INSTANT_SELL, 'Instant Sell'),
        ]
        # Set initial value if needed (e.g., default to Buy)
        self.fields['trans_type'].initial = Transaction.BUY

    def save(self, user=None):
        """
        Price is interpreted in 'millions', i.e. we store price * 1,000,000 in DB.
        Quantity is stored as-is (no multiplication).
        Reads trans_type from the (hidden) form field.
        """
        name_input = self.cleaned_data['item_name'].strip()
        trans_type = self.cleaned_data['trans_type'] # Read from the field
        price = self.cleaned_data['price'] * 1_000_000 # Convert to millions
        quantity = self.cleaned_data['quantity']
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
            user=user,
            item=item_obj,
            trans_type=trans_type, # Use the value from the form field
            price=price,
            quantity=quantity,
            date_of_holding=date_of_holding
        )
        return new_trans


class PlacingOrderForm(forms.Form):
    """
    Form for placing buy/sell orders.
    Transaction types limited to Placing Buy, Placing Sell.
    Inherits structure from TransactionManualItemForm.
    """
    item_name = forms.CharField(label="Item Name", max_length=200, widget=forms.TextInput(attrs={'placeholder': 'Item Short or Full Name'}))
    # Keep trans_type, but we'll hide it and set via buttons in template
    trans_type = forms.ChoiceField(choices=[], widget=forms.HiddenInput) # Initially empty, set in __init__
    price = forms.FloatField(label="Price (millions)")
    quantity = forms.FloatField(label="Quantity")
    date_of_holding = forms.DateField(initial=timezone.now, widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Filter choices for this form
        self.fields['trans_type'].choices = [
            (Transaction.PLACING_BUY, 'Placing Buy'),
            (Transaction.PLACING_SELL, 'Placing Sell'),
        ]
        # Set initial value if needed (e.g., default to Placing Buy)
        self.fields['trans_type'].initial = Transaction.PLACING_BUY

    def save(self, user=None):
        """
        Save logic is identical to TransactionManualItemForm,
        just uses the different trans_type choices set in __init__.
        """
        name_input = self.cleaned_data['item_name'].strip()
        trans_type = self.cleaned_data['trans_type'] # Read from the field
        price = self.cleaned_data['price'] * 1_000_000 # Convert to millions
        quantity = self.cleaned_data['quantity']
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
            user=user,
            item=item_obj,
            trans_type=trans_type, # Use the value from the form field
            price=price,
            quantity=quantity,
            date_of_holding=date_of_holding
        )
        return new_trans


class TransactionEditForm(forms.Form):
    """
    A form for editing an existing Transaction.
    Price is still in 'millions'; quantity is raw.
    Uses the original Buy/Sell dropdown for simplicity unless you want buttons here too.
    """
    transaction_id = forms.IntegerField(widget=forms.HiddenInput())
    item_name = forms.CharField(label="Item Name", max_length=200)
    # Keep dropdown for editing for now, includes ALL types potentially
    trans_type = forms.ChoiceField(choices=Transaction.TYPE_CHOICES)
    price = forms.FloatField(label="Price (millions)")
    quantity = forms.FloatField(label="Quantity")
    date_of_holding = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

    def load_initial(self, transaction):
        """
        Divide DB-stored price by 1,000,000 to show 'millions'.
        Quantity is shown as-is.
        """
        self.fields['transaction_id'].initial = transaction.id
        self.fields['item_name'].initial = transaction.item.name
        self.fields['trans_type'].initial = transaction.trans_type
        self.fields['price'].initial = transaction.price / 1_000_000.0
        self.fields['quantity'].initial = transaction.quantity
        self.fields['date_of_holding'].initial = transaction.date_of_holding

    def update_transaction(self, user=None):
        from .models import Transaction, Alias, Item

        trans_id = self.cleaned_data['transaction_id']
        # Make sure the transaction belongs to the user editing it
        transaction = get_object_or_404(Transaction, id=trans_id, user=user)

        name_input = self.cleaned_data['item_name'].strip()
        trans_type = self.cleaned_data['trans_type']
        price = self.cleaned_data['price'] * 1_000_000  # convert from millions
        quantity = self.cleaned_data['quantity']
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

        transaction.item = item_obj
        transaction.trans_type = trans_type
        transaction.price = price
        transaction.quantity = quantity
        transaction.date_of_holding = date_of_holding

        # Optionally ensure user matches if you want stricter ownership (already filtered above)
        # if user is not None:
        #     transaction.user = user

        transaction.save()
        return transaction


# ... (Rest of the forms: AliasForm, AccumulationPriceForm, etc. remain the same) ...
class AliasForm(forms.ModelForm):
    class Meta:
        model = Alias
        fields = ['full_name', 'short_name', 'image_file']

    def clean(self):
        cleaned_data = super().clean()
        full_name = cleaned_data.get('full_name')
        short_name = cleaned_data.get('short_name')

        qs = Alias.objects.filter(full_name=full_name, short_name=short_name)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError("This alias already exists.")
        return cleaned_data



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
            'account_name',  # now a plain text field
            'year',
            'january', 'february', 'march', 'april', 'may',
            'june', 'july', 'august', 'september', 'october', 'november', 'december'
        ]


class WatchlistForm(forms.ModelForm):
    class Meta:
        model = Watchlist
        fields = [
            'name','desired_price','buy_or_sell','account_name',
            'wished_quantity','total_value','current_holding'
        ]