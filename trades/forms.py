# trades/forms.py
import pytz
from django import forms
from django.utils import timezone
from django.shortcuts import get_object_or_404, Http404
# Remove 'User' from this import:
from .models import (
    Transaction, Alias, Item, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist, UserProfile, PRIORITIZED_TIMEZONE_CHOICES
)

TIMEZONE_CHOICES = [(tz, tz) for tz in pytz.common_timezones]

ADMIN_USERNAME = "Arblack"

# ... rest of forms.py ...

# ... rest of the forms.py file ...

class TransactionManualItemForm(forms.Form):
    item_name = forms.CharField(label="Item Name", max_length=200, widget=forms.TextInput(attrs={'placeholder': 'Item Short or Full Name'}))
    trans_type = forms.ChoiceField(choices=[], widget=forms.HiddenInput)
    price = forms.FloatField(label="Price (millions)")
    quantity = forms.FloatField(label="Quantity")
    # --- REMOVE date_of_holding field ---
    # date_of_holding = forms.DateField(initial=timezone.now, widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['trans_type'].choices = [
            (Transaction.BUY, 'Buy'),
            (Transaction.SELL, 'Sell'),
            (Transaction.INSTANT_BUY, 'Instant Buy'),
            (Transaction.INSTANT_SELL, 'Instant Sell'),
        ]
        self.fields['trans_type'].initial = Transaction.BUY

    def save(self, user=None):
        name_input = self.cleaned_data['item_name'].strip()
        trans_type = self.cleaned_data['trans_type']
        price = self.cleaned_data['price'] * 1_000_000
        quantity = self.cleaned_data['quantity']
        # --- REMOVE date_of_holding from cleaned_data ---
        # date_of_holding = self.cleaned_data['date_of_holding']

        # ... (logic to find/create item_obj remains the same) ...
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
            trans_type=trans_type,
            price=price,
            quantity=quantity,
            # --- DO NOT pass date_of_holding here - let model default work ---
            # date_of_holding=date_of_holding
        )
        return new_trans


class PlacingOrderForm(forms.Form):
    item_name = forms.CharField(label="Item Name", max_length=200, widget=forms.TextInput(attrs={'placeholder': 'Item Short or Full Name'}))
    trans_type = forms.ChoiceField(choices=[], widget=forms.HiddenInput)
    price = forms.FloatField(label="Price (millions)")
    quantity = forms.FloatField(label="Quantity")
    # --- REMOVE date_of_holding field ---
    # date_of_holding = forms.DateField(initial=timezone.now, widget=forms.DateInput(attrs={'type': 'date'}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['trans_type'].choices = [
            (Transaction.PLACING_BUY, 'Placing Buy'),
            (Transaction.PLACING_SELL, 'Placing Sell'),
        ]
        self.fields['trans_type'].initial = Transaction.PLACING_BUY

    def save(self, user=None):
        name_input = self.cleaned_data['item_name'].strip()
        trans_type = self.cleaned_data['trans_type']
        price = self.cleaned_data['price'] * 1_000_000
        quantity = self.cleaned_data['quantity']
        # --- REMOVE date_of_holding from cleaned_data ---
        # date_of_holding = self.cleaned_data['date_of_holding']

        # ... (logic to find/create item_obj remains the same) ...
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
            trans_type=trans_type,
            price=price,
            quantity=quantity,
             # --- DO NOT pass date_of_holding here - let model default work ---
            # date_of_holding=date_of_holding
        )
        return new_trans


class TransactionEditForm(forms.Form):
    transaction_id = forms.IntegerField(widget=forms.HiddenInput())
    item_name = forms.CharField(label="Item Name", max_length=200)
    trans_type = forms.ChoiceField(choices=Transaction.TYPE_CHOICES)
    price = forms.FloatField(label="Price (millions)")
    quantity = forms.FloatField(label="Quantity")
    # --- REMOVE date_of_holding field FROM EDIT FORM (unless editing time is required) ---
    # date_of_holding = forms.DateField(widget=forms.DateInput(attrs={'type': 'date'}))

    def load_initial(self, transaction):
        self.fields['transaction_id'].initial = transaction.id
        self.fields['item_name'].initial = transaction.item.name
        self.fields['trans_type'].initial = transaction.trans_type
        db_price = float(transaction.price or 0)
        self.fields['price'].initial = db_price / 1_000_000.0
        self.fields['quantity'].initial = transaction.quantity
        # --- REMOVE loading initial date_of_holding ---
        # self.fields['date_of_holding'].initial = transaction.date_of_holding

    def update_transaction(self, user=None):
        trans_id = self.cleaned_data['transaction_id']
        try:
            if user and user.username == ADMIN_USERNAME:
                 transaction = get_object_or_404(Transaction, id=trans_id)
            elif user:
                 transaction = get_object_or_404(Transaction, id=trans_id, user=user)
            else:
                 raise Http404("Authentication required.")
        except Http404:
             raise Http404("Transaction not found or permission denied.")

        name_input = self.cleaned_data['item_name'].strip()
        trans_type = self.cleaned_data['trans_type']
        price = self.cleaned_data['price'] * 1_000_000
        quantity = self.cleaned_data['quantity']
        # --- REMOVE date_of_holding from cleaned_data ---
        # date_of_holding = self.cleaned_data['date_of_holding']

        # ... (logic to find/create item_obj remains the same) ...
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
        # --- DO NOT update date_of_holding during edit ---
        # transaction.date_of_holding = date_of_holding

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

class UserProfileForm(forms.ModelForm):
    time_zone = forms.ChoiceField(
        # --- Use the imported choices list ---
        choices=PRIORITIZED_TIMEZONE_CHOICES,
        required=True,
        label="Preferred Timezone"
    )

    class Meta:
        model = UserProfile
        fields = ['time_zone']