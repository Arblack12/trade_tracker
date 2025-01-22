# trades/views.py

import io
import pandas as pd
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Sum, Avg
from django.utils import timezone
from django.urls import reverse
from django.utils.http import urlencode
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.models import User

from matplotlib import pyplot as plt
from matplotlib.ticker import StrMethodFormatter

from .models import (
    Transaction, Item, Alias, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist
)
from .forms import (
    TransactionManualItemForm, TransactionEditForm, AliasForm, AccumulationPriceForm,
    TargetSellPriceForm, MembershipForm, WealthDataForm, WatchlistForm
)


def index(request):
    """
    Unified homepage.
    Only shows the transactions belonging to the logged-in user (if authenticated).
    """
    if not request.user.is_authenticated:
        # Force user to sign in before viewing the site:
        return redirect('trades:login_view')

    timeframe = request.GET.get('timeframe', 'Daily')
    edit_form = None

    if 'edit_trans' in request.GET:
        try:
            t_id = int(request.GET['edit_trans'])
            t_obj = Transaction.objects.get(id=t_id, user=request.user)
            form = TransactionEditForm()
            form.load_initial(t_obj)
            edit_form = form
        except Transaction.DoesNotExist:
            pass

    if request.method == 'POST':
        # ADD a new transaction
        if 'add_transaction' in request.POST:
            tform = TransactionManualItemForm(request.POST)
            if tform.is_valid():
                new_trans = tform.save(user=request.user)  # attach user
                messages.success(request, f"Transaction for {new_trans.item.name} added successfully!")
                calculate_fifo_profits()
                # Redirect with ?search=<item_name> so that item info is shown
                url = reverse('trades:index')
                qs = urlencode({'search': new_trans.item.name})
                return redirect(f"{url}?{qs}")
            else:
                messages.error(request, "Error in the Add Transaction form.")

        # UPDATE accumulation price
        elif 'update_accumulation' in request.POST:
            item_id = request.POST.get('acc_item_id')
            acc_price = request.POST.get('accumulation_price')
            if item_id and acc_price:
                try:
                    item_obj = Item.objects.get(id=item_id)
                    ap, _ = AccumulationPrice.objects.get_or_create(item=item_obj)
                    ap.accumulation_price = float(acc_price)
                    ap.save()
                    messages.success(request, f"Accumulation price updated for {item_obj.name}.")
                except Item.DoesNotExist:
                    messages.error(request, "Item not found for accumulation update.")
            return redirect('trades:index')

        # UPDATE target sell price
        elif 'update_target_sell' in request.POST:
            item_id = request.POST.get('ts_item_id')
            ts_price = request.POST.get('target_sell_price')
            if item_id and ts_price:
                try:
                    item_obj = Item.objects.get(id=item_id)
                    tsp, _ = TargetSellPrice.objects.get_or_create(item=item_obj)
                    tsp.target_sell_price = float(ts_price)
                    tsp.save()
                    messages.success(request, f"Target sell price updated for {item_obj.name}.")
                except Item.DoesNotExist:
                    messages.error(request, "Item not found for target sell update.")
            return redirect('trades:index')

        # DELETE a transaction
        elif 'delete_transaction' in request.POST:
            t_id = request.POST.get('transaction_id')
            if t_id:
                try:
                    t_obj = Transaction.objects.get(id=t_id, user=request.user)
                    item_name = t_obj.item.name
                    t_obj.delete()
                    messages.success(request, "Transaction deleted.")
                    calculate_fifo_profits()
                    # Redirect with ?search=the item name
                    url = reverse('trades:index')
                    qs = urlencode({'search': item_name})
                    return redirect(f"{url}?{qs}")
                except Transaction.DoesNotExist:
                    messages.error(request, "Transaction not found or not owned by you.")
            return redirect('trades:index')

        # UPDATE (EDIT) a transaction
        elif 'update_transaction' in request.POST:
            ef = TransactionEditForm(request.POST)
            if ef.is_valid():
                updated_trans = ef.update_transaction(user=request.user)
                messages.success(request, "Transaction updated.")
                calculate_fifo_profits()
                # Redirect with ?search=the updated item name
                url = reverse('trades:index')
                qs = urlencode({'search': updated_trans.item.name})
                return redirect(f"{url}?{qs}")
            else:
                messages.error(request, "Error updating transaction.")
                edit_form = ef

    # If GET or we have form errors, proceed:
    transaction_form = TransactionManualItemForm()

    # Perform an optional item search
    search_query = request.GET.get('search', '').strip()
    item_obj = None
    item_alias = None
    accumulation_obj = None
    target_obj = None
    item_transactions = []
    total_sold = 0
    remaining_qty = 0
    avg_sold_price = 0
    item_profit = 0
    global_realised_profit = 0
    item_image_url = ""

    if search_query:
        # Look up alias by short_name or full_name
        alias_match = Alias.objects.filter(short_name__iexact=search_query).first()
        if not alias_match:
            alias_match = Alias.objects.filter(full_name__iexact=search_query).first()

        if alias_match:
            item_obj = Item.objects.filter(name__iexact=alias_match.full_name).first()
            item_alias = alias_match
        else:
            item_obj = Item.objects.filter(name__iexact=search_query).first()

        if item_obj:
            # If we found an item, get the alias if not already found
            if item_alias is None:
                item_alias = Alias.objects.filter(full_name__iexact=item_obj.name).first()

            accumulation_obj = AccumulationPrice.objects.filter(item=item_obj).first()
            target_obj = TargetSellPrice.objects.filter(item=item_obj).first()

            # Show only this user's transactions for the item
            item_transactions = Transaction.objects.filter(item=item_obj, user=request.user).order_by('-date_of_holding')

            sells = item_transactions.filter(trans_type='Sell')
            total_sold = sells.aggregate(sold_sum=Sum('quantity'))['sold_sum'] or 0

            buys_qty = item_transactions.filter(trans_type='Buy').aggregate(buy_sum=Sum('quantity'))['buy_sum'] or 0
            remaining_qty = buys_qty - total_sold

            if total_sold > 0:
                avg_sold_price = sells.aggregate(avg_price=Avg('price'))['avg_price'] or 0

            item_profit = item_transactions.aggregate(item_profit_sum=Sum('realised_profit'))['item_profit_sum'] or 0

            # Global profit for *this user* only
            global_realised_profit = Transaction.objects.filter(user=request.user).aggregate(
                total=Sum('realised_profit')
            )['total'] or 0

            if item_alias and item_alias.image_file:
                item_image_url = item_alias.image_file.url
        else:
            messages.warning(request, f"No item or alias found matching '{search_query}'.")

    # Show *this user's* transactions in the bottom table
    all_transactions = Transaction.objects.filter(user=request.user).order_by('-date_of_holding')

    context = {
        'transaction_form': transaction_form,
        'edit_form': edit_form,
        'timeframe': timeframe,
        'search_query': search_query,

        # item details
        'item_obj': item_obj,
        'item_alias': item_alias,
        'accumulation_obj': accumulation_obj,
        'target_obj': target_obj,
        'item_transactions': item_transactions,

        'total_sold': total_sold,
        'remaining_qty': remaining_qty,
        'avg_sold_price': avg_sold_price,
        'item_profit': item_profit,
        'global_realised_profit': global_realised_profit,
        'item_image_url': item_image_url,

        # user-specific transactions
        'all_transactions': all_transactions,
    }
    return render(request, 'trades/index.html', context)


def alias_list(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')

    edit_alias = None
    if 'edit_id' in request.GET:
        edit_id = request.GET['edit_id']
        edit_alias = get_object_or_404(Alias, id=edit_id)

    if request.method == 'POST':
        alias_id = request.POST.get('alias_id', '')
        if alias_id:
            alias_obj = get_object_or_404(Alias, id=alias_id)
            form = AliasForm(request.POST, request.FILES, instance=alias_obj)
        else:
            form = AliasForm(request.POST, request.FILES)

        if form.is_valid():
            form.save()
            messages.success(request, "Alias saved!")
            return redirect('trades:alias_list')
        else:
            messages.error(request, "Error saving alias.")
    else:
        if edit_alias:
            form = AliasForm(instance=edit_alias)
        else:
            form = AliasForm()

    letter = request.GET.get('letter', '')
    if letter:
        aliases = Alias.objects.filter(short_name__istartswith=letter).order_by('short_name')
    else:
        aliases = Alias.objects.all().order_by('short_name')

    letters = [chr(i) for i in range(ord('A'), ord('Z') + 1)]

    return render(request, 'trades/alias_list.html', {
        'form': form,
        'aliases': aliases,
        'edit_alias': edit_alias,
        'letters': letters,
    })


def alias_add(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')
    return redirect('trades:alias_list')


def membership_list(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')

    memberships = Membership.objects.all().order_by('account_name')
    return render(request, 'trades/membership_list.html', {
        'memberships': memberships,
    })


def watchlist_list(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')

    watchlist_items = Watchlist.objects.all().order_by('-date_added')
    return render(request, 'trades/watchlist_list.html', {
        'watchlist_items': watchlist_items,
    })


def wealth_list(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')

    wealth_records = WealthData.objects.all().order_by('year', 'account_name')
    return render(request, 'trades/wealth_list.html', {
        'wealth_records': wealth_records,
    })


def global_profit_chart(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')

    calculate_fifo_profits()
    qs = Transaction.objects.filter(user=request.user).order_by('date_of_holding', 'id')
    if not qs.exists():
        return HttpResponse("No transactions to chart.")

    data = []
    for tr in qs:
        data.append({
            'date': tr.date_of_holding,
            'cumulative_profit': tr.cumulative_profit
        })
    df = pd.DataFrame(data)
    df = df.groupby('date', as_index=False)['cumulative_profit'].last()

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(df['date'], df['cumulative_profit'], color='blue')
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative Profit")
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    ax.set_title("Global Cumulative Realized Profit Over Time (You)")
    fig.autofmt_xdate()

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
def account_page(request):
    return render(request, 'trades/account.html')


def password_reset_request(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')

    if request.method == 'POST':
        email = request.POST.get('email')
        messages.success(request, f'Password reset instructions have been sent to {email}.')
        return redirect('trades:account_page')
    return render(request, 'trades/password_reset_request.html')


@login_required
def transaction_list(request):
    transactions = Transaction.objects.filter(user=request.user).order_by('-date_of_holding')
    return render(request, 'trades/transaction_list.html', {'transactions': transactions})


@login_required
def transaction_add(request):
    if request.method == 'POST':
        form = TransactionManualItemForm(request.POST)
        if form.is_valid():
            new_trans = form.save(user=request.user)
            messages.success(request, f"Transaction for {new_trans.item.name} added.")
            calculate_fifo_profits()
            return redirect('trades:transaction_list')
    else:
        form = TransactionManualItemForm()
    return render(request, 'trades/transaction_add.html', {'form': form})


def calculate_fifo_profits():
    """
    A rough FIFO logic that updates each Transaction's realized_profit & cumulative_profit,
    on a per-user basis.
    """
    # Reset all
    Transaction.objects.all().update(realised_profit=0.0, cumulative_profit=0.0)

    # We'll group by user
    all_users = Transaction.objects.values_list('user', flat=True).distinct()
    for uid in all_users:
        purchase_lots = {}  # { item_id: [ {qty, price}, ... ] }
        cumulative_sum = 0.0

        user_trans = Transaction.objects.filter(user_id=uid).order_by('date_of_holding', 'trans_type', 'id')
        for trans in user_trans:
            item_id = trans.item_id
            if item_id not in purchase_lots:
                purchase_lots[item_id] = []

            if trans.trans_type == 'Buy':
                purchase_lots[item_id].append({'qty': trans.quantity, 'price': trans.price})
                trans.realised_profit = 0.0
            else:
                qty_to_sell = trans.quantity
                sell_price = trans.price
                profit = 0.0
                # example: 2% fee subtracted from the sell side
                while qty_to_sell > 0 and purchase_lots[item_id]:
                    lot = purchase_lots[item_id][0]
                    used = min(qty_to_sell, lot['qty'])

                    partial_profit = (sell_price * used * 0.98) - (lot['price'] * used)
                    profit += partial_profit

                    lot['qty'] -= used
                    qty_to_sell -= used
                    if lot['qty'] <= 0:
                        purchase_lots[item_id].pop(0)

                trans.realised_profit = profit

            cumulative_sum += trans.realised_profit
            trans.cumulative_profit = cumulative_sum
            trans.save()


def login_view(request):
    """Simple login form using Django's built-in authentication."""
    if request.user.is_authenticated:
        return redirect('trades:index')

    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            login(request, user)
            return redirect('trades:index')
        else:
            messages.error(request, "Invalid username/password")
    return render(request, 'trades/login.html')


def signup_view(request):
    """Simple sign-up form to create a new user."""
    if request.user.is_authenticated:
        return redirect('trades:index')

    if request.method == 'POST':
        username = request.POST.get('username').strip()
        password = request.POST.get('password').strip()
        if not username or not password:
            messages.error(request, "Username/Password cannot be empty.")
        else:
            if User.objects.filter(username=username).exists():
                messages.error(request, "Username already taken.")
            else:
                user = User.objects.create_user(username=username, password=password)
                login(request, user)
                return redirect('trades:index')

    return render(request, 'trades/signup.html')


# trades/views.py

import io
import pandas as pd
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Sum, Avg
from django.utils import timezone
from django.urls import reverse
from django.utils.http import urlencode
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.models import User

from matplotlib import pyplot as plt
from matplotlib.ticker import StrMethodFormatter

from .models import (
    Transaction, Item, Alias, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist
)
from .forms import (
    TransactionManualItemForm, TransactionEditForm, AliasForm, AccumulationPriceForm,
    TargetSellPriceForm, MembershipForm, WealthDataForm, WatchlistForm
)

# ... [other views remain unchanged above] ...

def recent_trades(request):
    """
    Shows recent transactions from all users (public).
    The first item image on the left (if any), item name, price, if SELL then show profit,
    then account name on far right.

    We do NOT use t.item.alias_set, because there's no ForeignKey from Alias -> Item.
    Instead, we find possible aliases by matching Alias.full_name == t.item.name.
    """
    transactions = Transaction.objects.select_related('item', 'user').order_by('-date_of_holding')[:50]

    # For each transaction, find an Alias whose full_name matches the Item name,
    # and that has a non-null image_file. Then store that image file URL as first_image_url.
    for t in transactions:
        first_alias_with_image = Alias.objects.filter(
            full_name__iexact=t.item.name,
            image_file__isnull=False
        ).first()
        if first_alias_with_image and first_alias_with_image.image_file:
            t.first_image_url = first_alias_with_image.image_file.url
        else:
            t.first_image_url = None

    context = {
        'transactions': transactions,
    }
    return render(request, 'trades/recent_trades.html', context)



def logout_view(request):
    """
    Custom logout view that handles a GET request
    and then redirects to the login page.
    """
    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect('trades:login_view')
