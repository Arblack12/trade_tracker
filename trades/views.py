# trades/views.py

import io
import pandas as pd
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Sum, Avg
from matplotlib import pyplot as plt
from matplotlib.ticker import StrMethodFormatter
from django.utils import timezone

from .models import (
    Transaction, Item, Alias, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist
)
from .forms import (
    TransactionManualItemForm, AliasForm, AccumulationPriceForm,
    TargetSellPriceForm, MembershipForm, WealthDataForm, WatchlistForm
)


def index(request):
    """
    Unified homepage:
      - Search bar & timeframe dropdown
      - Item details panel (with image, stats, etc.) if a search is provided
      - Forms to update accumulation/target-sell price for the found item
      - A manual transaction form (lets you type short or full item name)
      - Master transaction list at the bottom
    """

    # For the timeframe dropdown (just a dummy example for now)
    timeframe = request.GET.get('timeframe', 'Daily')

    # Handle POST actions from the forms on this page
    if request.method == 'POST':
        if 'add_transaction' in request.POST:
            # Add transaction form
            tform = TransactionManualItemForm(request.POST)
            if tform.is_valid():
                new_trans = tform.save()
                messages.success(request, f"Transaction for {new_trans.item.name} added successfully!")
                calculate_fifo_profits()
                return redirect('trades:index')
            else:
                messages.error(request, "Error in the Add Transaction form.")

        elif 'update_accumulation' in request.POST:
            # Update accumulation price
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

        elif 'update_target_sell' in request.POST:
            # Update target sell price
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

    # If GET or if a POST didn't cause a redirect, set up our default transaction form:
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
        # First, check if there's an alias with short_name or full_name matching search_query (case-insensitive)
        alias_match = Alias.objects.filter(short_name__iexact=search_query).first()
        if not alias_match:
            alias_match = Alias.objects.filter(full_name__iexact=search_query).first()

        if alias_match:
            # Then see if there's an actual Item with that alias's full_name
            item_obj = Item.objects.filter(name__iexact=alias_match.full_name).first()
            item_alias = alias_match
        else:
            # Or the user might've typed the full item name directly
            item_obj = Item.objects.filter(name__iexact=search_query).first()

        if item_obj:
            # If we found an Item, gather details
            if item_alias is None:
                # If no alias was matched, see if one exists by matching the item name
                item_alias = Alias.objects.filter(full_name__iexact=item_obj.name).first()

            accumulation_obj = AccumulationPrice.objects.filter(item=item_obj).first()
            target_obj = TargetSellPrice.objects.filter(item=item_obj).first()

            # All transactions for that item
            item_transactions = Transaction.objects.filter(item=item_obj).order_by('-date_of_holding')

            # Sum of SELL for that item
            sells = item_transactions.filter(trans_type='Sell')
            total_sold = sells.aggregate(sold_sum=Sum('quantity'))['sold_sum'] or 0

            # remaining qty = sum(BUY) - sum(SELL)
            buys_qty = item_transactions.filter(trans_type='Buy').aggregate(buy_sum=Sum('quantity'))['buy_sum'] or 0
            remaining_qty = buys_qty - total_sold

            # average sold price (simple approach)
            if total_sold > 0:
                avg_sold_price = sells.aggregate(avg_price=Avg('price'))['avg_price'] or 0

            # item profit = sum of realised_profit for that item
            item_profit = item_transactions.aggregate(item_profit_sum=Sum('realised_profit'))['item_profit_sum'] or 0

            # global realised profit across all items
            global_realised_profit = Transaction.objects.aggregate(total=Sum('realised_profit'))['total'] or 0

            # if alias has an uploaded image, get its URL
            if item_alias and item_alias.image_file:
                item_image_url = item_alias.image_file.url
        else:
            messages.warning(request, f"No item or alias found matching '{search_query}'.")

    # Show all transactions in the bottom table
    all_transactions = Transaction.objects.all().order_by('-date_of_holding')

    context = {
        'transaction_form': transaction_form,
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

        # all transactions
        'all_transactions': all_transactions,
    }
    return render(request, 'trades/index.html', context)


def alias_list(request):
    """Show all aliases."""
    aliases = Alias.objects.all().order_by('full_name')
    return render(request, 'trades/alias_list.html', {'aliases': aliases})


def alias_add(request):
    """Add or edit an alias, including uploading an image."""
    if request.method == 'POST':
        form = AliasForm(request.POST, request.FILES)
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
    """
    (Optional) If you still want a separate page showing all transactions.
    Otherwise, you can rely solely on the unified homepage.
    """
    transactions = Transaction.objects.all().order_by('-date_of_holding')
    return render(request, 'trades/transaction_list.html', {'transactions': transactions})


def transaction_add(request):
    """
    (Optional) If you still want a separate page for adding transactions.
    Otherwise, just use the unified homepage's form.
    """
    if request.method == 'POST':
        # If you're still using the original TransactionForm, do so here.
        # Or adapt the new manual form approach if you prefer.
        form = TransactionManualItemForm(request.POST)
        if form.is_valid():
            new_trans = form.save()
            messages.success(request, f"Transaction for {new_trans.item.name} added.")
            calculate_fifo_profits()
            return redirect('trades:transaction_list')
    else:
        form = TransactionManualItemForm()

    return render(request, 'trades/transaction_add.html', {'form': form})


def calculate_fifo_profits():
    """
    A rough FIFO logic that overwrites each Transaction's realized_profit
    & cumulative_profit. Adjust as needed for your logic/taxes/etc.
    """
    # Reset realized/cumulative profit
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
        else:
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
