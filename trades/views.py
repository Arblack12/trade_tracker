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

def index(request):
    """
    Main homepage that:
      - Provides a top nav.
      - Lets you search for an item by name or alias.
      - Shows the item’s image, current price, target sell price, etc.
      - Lets you add a new transaction for that item on the same page.
      - Displays a transaction history (for the searched item) at the bottom.
    """
    # A blank or default transaction form we'll show on the page:
    transaction_form = TransactionForm()
    item_details = None
    transactions = []

    # Handle POST requests for adding a new transaction:
    if request.method == 'POST':
        transaction_form = TransactionForm(request.POST)
        if transaction_form.is_valid():
            new_trans = transaction_form.save()
            messages.success(request, f"Transaction for {new_trans.item.name} added successfully!")
            # Recalculate FIFO profits (from your existing function):
            calculate_fifo_profits()
            return redirect('trades:index')

    # Handle GET search queries:
    search_query = request.GET.get('search_item', '').strip()
    if search_query:
        # First, try to find an Item whose name matches or contains the query:
        item_qs = Item.objects.filter(name__icontains=search_query)
        found_item = item_qs.first()

        # If not found directly in Item, see if there's an Alias that matches the query:
        if not found_item:
            alias_qs = Alias.objects.filter(short_name__icontains=search_query) | \
                       Alias.objects.filter(full_name__icontains=search_query)
            alias = alias_qs.first()
            if alias:
                # Try linking the alias's full_name to the Item
                found_item = Item.objects.filter(name=alias.full_name).first()

        if found_item:
            # Retrieve any associated accumulation price and target sell price
            try:
                acc_obj = AccumulationPrice.objects.get(item=found_item)
                current_price = acc_obj.accumulation_price
            except AccumulationPrice.DoesNotExist:
                current_price = None

            try:
                tgt_obj = TargetSellPrice.objects.get(item=found_item)
                tgt_price = tgt_obj.target_sell_price
            except TargetSellPrice.DoesNotExist:
                tgt_price = None

            # Optionally retrieve alias for an image path:
            # (We look for an alias that exactly matches item’s name.)
            alias_entry = Alias.objects.filter(full_name=found_item.name).first()
            image_path = alias_entry.image_path if alias_entry else None

            # Prepare item details for the template
            item_details = {
                'name': found_item.name,
                'image_path': image_path,
                'current_price': current_price,
                'target_sell_price': tgt_price,
            }

            # Show only this item’s transactions
            transactions = Transaction.objects.filter(item=found_item).order_by('-date_of_holding')
        else:
            messages.warning(request, f"No item or alias found matching '{search_query}'.")

    context = {
        'search_query': search_query,
        'item_details': item_details,
        'transaction_form': transaction_form,
        'transactions': transactions,
    }
    return render(request, 'trades/index.html', context)


def calculate_fifo_profits():
    """
    A rough FIFO logic that overwrites each Transaction's realized_profit
    & cumulative_profit. Adjust as needed for your business rules/taxes/etc.
    """
    # Reset everything
    Transaction.objects.all().update(realised_profit=0.0, cumulative_profit=0.0)

    all_trans = Transaction.objects.all().order_by('date_of_holding', 'trans_type', 'id')
    purchase_lots = {}  # { item_id: [ {qty, price}, ... ] }
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

                # Example fee of 2% on sell side:
                partial_profit = (sell_price * used * 0.98) - (lot['price'] * used)
                profit += partial_profit

                lot['qty'] -= used
                qty_to_sell -= used

                if lot['qty'] <= 0:
                    purchase_lots[item_id].pop(0)

            # If qty_to_sell remains with no more lots, do what you need to handle that scenario.
            trans.realised_profit = profit

        cumulative_sum += trans.realised_profit
        trans.cumulative_profit = cumulative_sum
        trans.save()
