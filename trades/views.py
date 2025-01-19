# trades/views.py

import io
import pandas as pd
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Sum
from matplotlib import pyplot as plt
from matplotlib.ticker import StrMethodFormatter

from .models import (
    Transaction, Item, Alias, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist
)
from .forms import TransactionForm, AliasForm, ItemForm, AccumulationPriceForm, \
                   TargetSellPriceForm, MembershipForm, WealthDataForm, WatchlistForm
from django.utils import timezone

def index(request):
    """
    UNIFIED HOMEPAGE:
      - Transaction Form (Buy/Sell) right on the page
      - Optional Search to see item-specific transactions
      - Full transaction list below
    """
    # The form to add a transaction
    transaction_form = TransactionForm()

    # If this is a POST, user is adding a transaction
    if request.method == 'POST':
        transaction_form = TransactionForm(request.POST)
        if transaction_form.is_valid():
            new_trans = transaction_form.save()
            messages.success(request, f"Transaction for {new_trans.item.name} added successfully!")
            calculate_fifo_profits()
            return redirect('trades:index')

    # Optional search logic:
    search_query = request.GET.get('search_item', '').strip()
    item_details = None
    item_transactions = []

    if search_query:
        # Try to find an Item directly
        item = Item.objects.filter(name__icontains=search_query).first()
        if not item:
            # Or see if there's an Alias match
            alias = Alias.objects.filter(short_name__icontains=search_query)\
                                 .union(Alias.objects.filter(full_name__icontains=search_query))\
                                 .first()
            if alias:
                item = Item.objects.filter(name=alias.full_name).first()

        if item:
            item_details = {'name': item.name}
            item_transactions = Transaction.objects.filter(item=item).order_by('-date_of_holding')
        else:
            messages.warning(request, f"No item or alias found matching '{search_query}'.")

    # Always fetch all transactions (for the big table at the bottom)
    all_transactions = Transaction.objects.all().order_by('-date_of_holding')

    context = {
        'transaction_form': transaction_form,
        'search_query': search_query,
        'item_details': item_details,
        'item_transactions': item_transactions,
        'all_transactions': all_transactions,
    }
    return render(request, 'trades/index.html', context)


def alias_list(request):
    """Show all aliases."""
    aliases = Alias.objects.all().order_by('full_name')
    return render(request, 'trades/alias_list.html', {'aliases': aliases})


def alias_add(request):
    """Add or edit an alias."""
    if request.method == 'POST':
        form = AliasForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Alias saved!")
            return redirect('trades:alias_list')
    else:
        form = AliasForm()
    return render(request, 'trades/alias_add.html', {'form': form})


def membership_list(request):
    """Show all memberships."""
    memberships = Membership.objects.all().order_by('account_name')
    return render(request, 'trades/membership_list.html', {
        'memberships': memberships,
    })


def watchlist_list(request):
    """Show watchlist items."""
    watchlist_items = Watchlist.objects.all().order_by('-date_added')
    return render(request, 'trades/watchlist_list.html', {
        'watchlist_items': watchlist_items,
    })


def wealth_list(request):
    """Show wealth data."""
    wealth_records = WealthData.objects.all().order_by('year', 'account_name')
    return render(request, 'trades/wealth_list.html', {
        'wealth_records': wealth_records,
    })


def global_profit_chart(request):
    """Generates a PNG chart of global cumulative profit over time."""
    calculate_fifo_profits()
    qs = Transaction.objects.all().order_by('date_of_holding', 'id')
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
    ax.set_title("Global Cumulative Realized Profit Over Time")
    fig.autofmt_xdate()

    import io
    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


def account_page(request):
    """Placeholder for an account page."""
    return render(request, 'trades/account.html')


def password_reset_request(request):
    """Placeholder for a password reset form."""
    if request.method == 'POST':
        email = request.POST.get('email')
        messages.success(request, f'Password reset instructions have been sent to {email}.')
        return redirect('trades:account_page')
    return render(request, 'trades/password_reset_request.html')


def transaction_list(request):
    """(Optional) If you still want a separate page showing all transactions."""
    transactions = Transaction.objects.all().order_by('-date_of_holding')
    return render(request, 'trades/transaction_list.html', {'transactions': transactions})


def transaction_add(request):
    """(Optional) If you still want a separate page for adding transactions."""
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            new_trans = form.save()
            messages.success(request, f"Transaction for {new_trans.item.name} added.")
            calculate_fifo_profits()
            return redirect('trades:transaction_list')
    else:
        form = TransactionForm()
    return render(request, 'trades/transaction_add.html', {'form': form})


def calculate_fifo_profits():
    """
    A rough FIFO logic that overwrites each Transaction's realized_profit
    & cumulative_profit. Adjust as needed for your business rules/taxes/etc.
    """
    # Reset
    Transaction.objects.all().update(realised_profit=0.0, cumulative_profit=0.0)
    purchase_lots = {}  # { item_id: [ {qty, price}, ... ] }
    cumulative_sum = 0.0

    all_trans = Transaction.objects.all().order_by('date_of_holding', 'trans_type', 'id')
    for trans in all_trans:
        item_id = trans.item_id
        if item_id not in purchase_lots:
            purchase_lots[item_id] = []

        if trans.trans_type == 'Buy':
            purchase_lots[item_id].append({'qty': trans.quantity, 'price': trans.price})
            trans.realised_profit = 0.0
        else:  # Sell
            qty_to_sell = trans.quantity
            sell_price = trans.price
            profit = 0.0

            while qty_to_sell > 0 and purchase_lots[item_id]:
                lot = purchase_lots[item_id][0]
                used = min(qty_to_sell, lot['qty'])

                # Example fee of 2%
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
