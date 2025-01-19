# trades/views.py

import io
import math
import pandas as pd
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.http import HttpResponse, HttpResponseRedirect
from django.contrib import messages
from django.db.models import Sum, F
from matplotlib import pyplot as plt
from matplotlib.ticker import StrMethodFormatter

from .models import (
    Transaction, Item, Alias, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist
)
from .forms import (
    TransactionForm, AliasForm, ItemForm, AccumulationPriceForm,
    TargetSellPriceForm, MembershipForm, WealthDataForm, WatchlistForm
)

# =========== SIMPLE HOME PAGE ===========
def index(request):
    return render(request, 'trades/index.html')

# =========== TRANSACTIONS ===========
def transaction_list(request):
    """ Show all transactions. """
    transactions = Transaction.objects.all().select_related('item').order_by('-date_of_holding')
    return render(request, 'trades/transaction_list.html', {
        'transactions': transactions,
    })

def transaction_add(request):
    """ Add a new transaction. """
    if request.method == 'POST':
        form = TransactionForm(request.POST)
        if form.is_valid():
            trans = form.save(commit=False)
            # Optionally multiply price by 1_000_000 if that’s your convention
            # trans.price = trans.price * 1_000_000
            trans.save()
            messages.success(request, f"Transaction for {trans.item.name} added.")
            # After adding, recalc FIFO profits globally
            calculate_fifo_profits()
            return redirect('trades:transaction_list')
    else:
        form = TransactionForm()
    return render(request, 'trades/transaction_add.html', {'form': form})

def calculate_fifo_profits():
    """
    A rough example to mimic your FIFO logic across all items.
    Overwrites each Transaction's realized_profit & cumulative_profit columns.
    """

    # Reset everything first
    Transaction.objects.all().update(realised_profit=0.0, cumulative_profit=0.0)

    # Sort by date, then by type Buy first
    all_trans = Transaction.objects.all().order_by('date_of_holding', 'trans_type', 'id')

    purchase_lots = {}  # { item_id: [ {qty,price}, ... ] }
    cumulative_sum = 0.0

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
                qty_available = lot['qty']
                used = min(qty_to_sell, qty_available)

                # your formula: (sell_price * used * 0.98) - (lot['price'] * used)
                # or whichever approach you want
                partial_profit = (sell_price * used * 0.98) - (lot['price'] * used)
                profit += partial_profit

                lot['qty'] -= used
                qty_to_sell -= used

                if lot['qty'] <= 0:
                    purchase_lots[item_id].pop(0)

            # If still qty_to_sell > 0, no more lots => purely profit from ??? (You can decide how to handle)
            if qty_to_sell > 0:
                # some logic, e.g. profit += (sell_price * qty_to_sell * 0.98)
                pass

            trans.realised_profit = profit

        cumulative_sum += trans.realised_profit
        trans.cumulative_profit = cumulative_sum
        trans.save()


# =========== ALIASES ===========
def alias_list(request):
    """Show all aliases."""
    aliases = Alias.objects.all().order_by('full_name')
    return render(request, 'trades/alias_list.html', {
        'aliases': aliases,
    })

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


# =========== WEALTH DATA ===========
def wealth_list(request):
    """Display or handle wealth data. For now, just a list + form example."""
    # If you want to filter by year, do so, or just show everything
    wealth_records = WealthData.objects.all().order_by('year','account_name')
    return render(request, 'trades/wealth_list.html', {
        'wealth_records': wealth_records,
    })


# =========== MEMBERSHIP ===========
def membership_list(request):
    memberships = Membership.objects.all().order_by('account_name')
    return render(request, 'trades/membership_list.html', {
        'memberships': memberships,
    })


# =========== WATCHLIST ===========
def watchlist_list(request):
    watchlist_items = Watchlist.objects.all().order_by('-date_added')
    return render(request, 'trades/watchlist_list.html', {
        'watchlist_items': watchlist_items,
    })


# =========== GLOBAL PROFIT CHART (example) ===========
def global_profit_chart(request):
    """
    Example of rendering your global cumulative profit in a chart using matplotlib.
    We'll collect all transactions, sorted by date. Then plot the cumulative_profit.
    Return as a PNG image via HttpResponse.
    """
    # Make sure FIFO is up-to-date
    calculate_fifo_profits()

    qs = Transaction.objects.all().order_by('date_of_holding', 'id')
    if not qs.exists():
        return HttpResponse("No transactions to chart.")

    # Build a small dataframe
    data = []
    cum_val = 0.0
    for tr in qs:
        data.append({
            'date': tr.date_of_holding,
            'cumulative_profit': tr.cumulative_profit
        })
    df = pd.DataFrame(data)
    df = df.groupby('date', as_index=False)['cumulative_profit'].last()

    fig, ax = plt.subplots(figsize=(8,4))
    ax.plot(df['date'], df['cumulative_profit'], color='blue')
    ax.set_xlabel("Date")
    ax.set_ylabel("Cumulative Profit")
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    ax.set_title("Global Cumulative Realized Profit Over Time")
    fig.autofmt_xdate()

    buf = io.BytesIO()
    plt.tight_layout()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)

    return HttpResponse(buf.getvalue(), content_type='image/png')
