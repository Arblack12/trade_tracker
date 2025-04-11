# trades/views.py

#!/usr/bin/env python
"""Django views for the trades app."""
import io
import numpy as np  # <-- ADDED for NaN replacements
import pandas as pd
from datetime import datetime
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Sum, Avg, Max
from django.utils import timezone
from django.urls import reverse
from django.utils.http import urlencode
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, logout
from django.contrib.auth.models import User
from django.db import transaction  # For atomic transactions
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter
import matplotlib
matplotlib.use("Agg")
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger

# Force matplotlib to use a non-interactive backend so that no GUI is started.
import matplotlib
matplotlib.use("Agg")

from .models import WealthData, UserBan
from .forms import WealthDataForm
from django.db.models import Q

from .models import (
    Transaction, Item, Alias, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist, User
)
from .forms import (
    TransactionManualItemForm, TransactionEditForm, AliasForm, AccumulationPriceForm,
    TargetSellPriceForm, MembershipForm, WealthDataForm, WatchlistForm, PlacingOrderForm
)


def index(request):
    """
    Unified homepage. Shows user's transactions for a searched item.
    Includes forms for 'Add Transaction' and 'Placing Order'.
    Displays a list of all current 'Placing Orders'.
    """
    if not request.user.is_authenticated:
        return redirect('trades:login_view')

    timeframe = request.GET.get('timeframe', 'Daily')
    edit_form = None
    add_transaction_form = TransactionManualItemForm() # Instantiate Add form
    placing_order_form = PlacingOrderForm() # Instantiate Place Order form
    active_form_name = 'add_transaction' # Default active form

    # --- Handle Edit Request (GET) ---
    if 'edit_trans' in request.GET:
        try:
            t_id = int(request.GET['edit_trans'])
            t_obj = get_object_or_404(Transaction, id=t_id, user=request.user)
            form = TransactionEditForm()
            form.load_initial(t_obj)
            edit_form = form
            # If editing, maybe default to showing the 'Add Transaction' form area
            active_form_name = 'add_transaction'
        except Transaction.DoesNotExist:
            messages.error(request, "Transaction to edit not found or not owned by you.")
            # Redirect to avoid broken state, remove edit_trans param
            query_params = request.GET.copy()
            query_params.pop('edit_trans', None)
            return redirect(f"{reverse('trades:index')}?{urlencode(query_params)}")

    # --- Handle Form Submissions (POST) ---
    if request.method == 'POST':
        item_name_for_redirect = request.POST.get('item_name') # Get item name for redirect

        # Determine which form was submitted
        if 'add_transaction_submit' in request.POST:
            active_form_name = 'add_transaction'
            tform = TransactionManualItemForm(request.POST)
            if tform.is_valid():
                new_trans = tform.save(user=request.user)
                messages.success(request, f"Transaction for {new_trans.item.name} added successfully!")
                calculate_fifo_for_user(request.user)
                url = reverse('trades:index')
                qs = urlencode({'search': new_trans.item.name}) # Redirect to the item searched
                return redirect(f"{url}?{qs}")
            else:
                messages.error(request, "Error in the Add Transaction form.")
                add_transaction_form = tform # Show form with errors

        elif 'placing_order_submit' in request.POST:
            active_form_name = 'placing_order'
            pform = PlacingOrderForm(request.POST)
            if pform.is_valid():
                new_order = pform.save(user=request.user)
                messages.success(request, f"Order for {new_order.item.name} placed successfully!")
                # No FIFO calculation needed for placing orders (presumably)
                url = reverse('trades:index')
                # Redirect showing placing orders filtered by the item just placed
                qs = urlencode({'search': new_order.item.name})
                return redirect(f"{url}?{qs}")
            else:
                messages.error(request, "Error in the Placing Order form.")
                placing_order_form = pform # Show form with errors

        elif 'update_transaction' in request.POST: # Handle EDIT submission
            active_form_name = 'add_transaction' # Keep add form area visible
            ef = TransactionEditForm(request.POST)
            if ef.is_valid():
                try:
                    updated_trans = ef.update_transaction(user=request.user) # Pass user for validation
                    messages.success(request, "Transaction updated.")
                    calculate_fifo_for_user(request.user)
                    url = reverse('trades:index')
                    qs = urlencode({'search': updated_trans.item.name})
                    return redirect(f"{url}?{qs}")
                except Http404: # Or whatever error get_object_or_404 raises
                     messages.error(request, "Transaction not found or permission denied.")
                     return redirect(reverse('trades:index'))

            else:
                messages.error(request, "Error updating transaction.")
                edit_form = ef # Show edit form with errors

        elif 'delete_transaction' in request.POST:
            active_form_name = 'add_transaction' # Keep add form area visible
            t_id = request.POST.get('transaction_id')
            if t_id:
                try:
                    t_obj = get_object_or_404(Transaction, id=t_id, user=request.user)
                    item_name = t_obj.item.name
                    t_obj.delete()
                    messages.success(request, "Transaction deleted.")
                    calculate_fifo_for_user(request.user)
                    url = reverse('trades:index')
                    qs = urlencode({'search': item_name}) # Go back to the item's page
                    return redirect(f"{url}?{qs}")
                except Transaction.DoesNotExist:
                    messages.error(request, "Transaction not found or not owned by you.")
                    # Redirect to avoid broken state
                    query_params = request.GET.copy()
                    query_params.pop('delete_transaction', None) # Remove if it was a GET param somehow
                    return redirect(f"{reverse('trades:index')}?{urlencode(query_params)}")

        elif 'update_accumulation' in request.POST or 'update_target_sell' in request.POST:
             # Handle Accumulation/Target Sell Price Updates (Keep existing logic)
             item_id = request.POST.get('acc_item_id') or request.POST.get('ts_item_id')
             item_name_for_redirect = None # Will be set below if successful

             if item_id:
                 try:
                     item_obj = Item.objects.get(id=item_id)
                     item_name_for_redirect = item_obj.name # Get name for redirect
                     if 'update_accumulation' in request.POST:
                         acc_price = request.POST.get('accumulation_price')
                         if acc_price is not None:
                            ap, _ = AccumulationPrice.objects.get_or_create(item=item_obj)
                            ap.accumulation_price = float(acc_price) * 1_000_000 # Convert from millions
                            ap.save()
                            messages.success(request, f"Accumulation price updated for {item_obj.name}.")
                         else:
                            messages.error(request, "Accumulation price value missing.")

                     elif 'update_target_sell' in request.POST:
                         ts_price = request.POST.get('target_sell_price')
                         if ts_price is not None:
                            tsp, _ = TargetSellPrice.objects.get_or_create(item=item_obj)
                            tsp.target_sell_price = float(ts_price) * 1_000_000 # Convert from millions
                            tsp.save()
                            messages.success(request, f"Target sell price updated for {item_obj.name}.")
                         else:
                             messages.error(request, "Target sell price value missing.")

                 except Item.DoesNotExist:
                     messages.error(request, "Item not found for price update.")
                 except (ValueError, TypeError):
                     messages.error(request, "Invalid price format entered.")

             else:
                 messages.error(request, "Item ID missing for price update.")

             # Redirect back to the item page after update
             url = reverse('trades:index')
             if item_name_for_redirect:
                 qs = urlencode({'search': item_name_for_redirect})
                 return redirect(f"{url}?{qs}")
             else:
                 # If item lookup failed, just redirect to index without search
                 return redirect(url)

        else:
            # If no known form action, perhaps redirect or show a generic error
            messages.warning(request, "Unknown form action.")
            return redirect('trades:index')

    # --- Item Search and Data Fetching (GET requests and after POST redirects) ---
    search_query = request.GET.get('search', '').strip()
    item_obj = None
    item_alias = None
    accumulation_obj = None
    target_obj = None
    item_transactions_qs = Transaction.objects.none()
    user_page_obj = None # Paginated user transactions
    placing_orders_qs = Transaction.objects.none()
    placing_orders_page_obj = None # Paginated placing orders
    total_sold = 0
    remaining_qty = 0
    avg_sold_price = 0
    item_profit = 0
    item_image_url = ""

    global_realised_profit = Transaction.objects.filter(user=request.user).aggregate(total=Max('cumulative_profit'))['total'] or 0

    # --- Find Item based on search query ---
    if search_query:
        alias_match = Alias.objects.filter(short_name__iexact=search_query).first()
        if not alias_match:
            alias_match = Alias.objects.filter(full_name__iexact=search_query).first()
        if alias_match:
            item_obj = Item.objects.filter(name__iexact=alias_match.full_name).first()
            item_alias = alias_match
        else:
            item_obj = Item.objects.filter(name__iexact=search_query).first()

        if item_obj:
            if item_alias is None:
                item_alias = Alias.objects.filter(full_name__iexact=item_obj.name).first()
            accumulation_obj = AccumulationPrice.objects.filter(item=item_obj).first()
            target_obj = TargetSellPrice.objects.filter(item=item_obj).first()

            if item_alias and item_alias.image_file:
                item_image_url = item_alias.image_file.url

            # *** Get User's transactions for this item (Paginated) ***
            item_transactions_qs = Transaction.objects.filter(
                item=item_obj, user=request.user
            ).exclude( # Exclude placing orders from user's main history
                trans_type__in=[Transaction.PLACING_BUY, Transaction.PLACING_SELL]
            ).order_by('-date_of_holding', '-id')

            # Calculate stats based on user's non-placing transactions for this item
            sells = item_transactions_qs.filter(trans_type='Sell')
            total_sold = sells.aggregate(sold_sum=Sum('quantity'))['sold_sum'] or 0
            buys_qty = item_transactions_qs.filter(trans_type='Buy').aggregate(buy_sum=Sum('quantity'))['buy_sum'] or 0
            # Include instant buys/sells in remaining qty calculation if appropriate
            # Assuming Instant Buy increases holdings, Instant Sell decreases
            instant_buys_qty = item_transactions_qs.filter(trans_type=Transaction.INSTANT_BUY).aggregate(buy_sum=Sum('quantity'))['buy_sum'] or 0
            instant_sells_qty = item_transactions_qs.filter(trans_type=Transaction.INSTANT_SELL).aggregate(sell_sum=Sum('quantity'))['sell_sum'] or 0

            remaining_qty = (buys_qty + instant_buys_qty) - (total_sold + instant_sells_qty)

            if total_sold > 0 or instant_sells_qty > 0: # Consider both sell types for avg price
                 all_sells_qs = Transaction.objects.filter(
                     item=item_obj, user=request.user,
                     trans_type__in=[Transaction.SELL, Transaction.INSTANT_SELL]
                 )
                 # Calculate weighted average sell price if needed, or simple average
                 # For simple average:
                 avg_sold_price = all_sells_qs.aggregate(avg_price=Avg('price'))['avg_price'] or 0

            item_profit = item_transactions_qs.aggregate(item_profit_sum=Sum('realised_profit'))['item_profit_sum'] or 0

            # Paginate User's Transactions
            user_items_per_page = 25
            user_paginator = Paginator(item_transactions_qs, user_items_per_page)
            user_page_number = request.GET.get('user_page') # Use different param name
            user_page_obj = user_paginator.get_page(user_page_number)

        else:
            messages.warning(request, f"No item or alias found matching '{search_query}'.")

    # --- Fetch Placing Orders (All Users, potentially filtered by item) ---
    placing_orders_qs = Transaction.objects.filter(
        trans_type__in=[Transaction.PLACING_BUY, Transaction.PLACING_SELL]
    ).select_related('item', 'user').order_by('-date_of_holding', '-id')

    # If an item was successfully searched, filter placing orders for that item too
    if item_obj:
        placing_orders_qs = placing_orders_qs.filter(item=item_obj)
        placing_orders_title = f"Placing Orders for {item_obj.name}"
    else:
         placing_orders_title = "All Current Placing Orders" # Default title


    # Paginate Placing Orders
    placing_orders_per_page = 15 # Different number per page maybe
    placing_orders_paginator = Paginator(placing_orders_qs, placing_orders_per_page)
    placing_orders_page_number = request.GET.get('placing_page') # Different param name
    placing_orders_page_obj = placing_orders_paginator.get_page(placing_orders_page_number)


    # --- Prepare Context ---
    context = {
        'add_transaction_form': add_transaction_form,
        'placing_order_form': placing_order_form,
        'edit_form': edit_form,
        'active_form_name': active_form_name, # To know which form area to show initially

        'search_query': search_query,
        'item': item_obj,
        'alias': item_alias,
        'accumulation': accumulation_obj,
        'target_sell': target_obj,

        # User's Transaction History for the item (Paginated)
        'item_transactions': user_page_obj, # Use the paginated object
        'user_page_obj': user_page_obj, # Pass explicitly for pagination controls

        # Item Stats (based on user's history)
        'total_sold': total_sold,
        'remaining_quantity': remaining_qty,
        'average_sold_price': avg_sold_price,
        'item_profit': item_profit,
        'item_image_url': item_image_url,
        'global_realised_profit': global_realised_profit,
        'timeframe': timeframe,

        # Placing Orders (Paginated) - All users, maybe filtered by item
        'placing_orders': placing_orders_page_obj, # Use the paginated object
        'placing_orders_page_obj': placing_orders_page_obj, # Pass explicitly for pagination controls
        'placing_orders_title': placing_orders_title,
    }

    return render(request, 'trades/index.html', context)


from django.db.models import Case, When, F, CharField

def alias_list(request):
    if not request.user.is_authenticated:
        return redirect('trades:login_view')

    edit_alias = None
    if 'edit_id' in request.GET:
        edit_id = request.GET['edit_id']
        edit_alias = get_object_or_404(Alias, id=edit_id)

    if request.method == 'POST':
        # Handle deletion
        if 'delete_alias' in request.POST:
            alias_id = request.POST.get('alias_id', '')
            if alias_id:
                try:
                    alias_obj = Alias.objects.get(id=alias_id)
                    alias_obj.delete()
                    messages.success(request, "Alias deleted.")
                except Alias.DoesNotExist:
                    messages.error(request, "Alias not found.")
            return redirect('trades:alias_list')
        else:
            # Handle add/update
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
        form = AliasForm()

    letter = request.GET.get('letter', '')
    if letter:
        qs = Alias.objects.filter(full_name__istartswith=letter)
    else:
        qs = Alias.objects.all()
    aliases = qs.order_by('full_name')

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
    # Simply redirect to alias_list, where the alias form is processed.
    return redirect('trades:alias_list')


@login_required
def membership_list(request):
    """
    Show only the membership record for the logged-in user.
    """
    # Assuming Membership.account_name corresponds to the user's username.
    memberships = Membership.objects.filter(account_name=request.user.username)
    return render(request, 'trades/membership_list.html', {
        'memberships': memberships,
    })


@login_required
def watchlist_list(request):
    """
    Show watchlist items only for the logged-in user.
    """
    # Assuming Watchlist.account_name corresponds to the user's username.
    watchlist_items = Watchlist.objects.filter(account_name=request.user.username).order_by('-date_added')
    return render(request, 'trades/watchlist_list.html', {
        'watchlist_items': watchlist_items,
    })


from django.contrib.auth.decorators import login_required


@login_required
def wealth_list(request):
    """
    Display all wealth data records for the logged-in user,
    either for a selected year or for all years (?year=all).
    Then compute combined wealth totals for the filtered records.
    """
    current_year = datetime.now().year

    # Only this user’s data
    all_records = WealthData.objects.filter(account_name=request.user.username).order_by('year', 'account_name')
    years_for_user = (WealthData.objects
                      .filter(account_name=request.user.username)
                      .values_list('year', flat=True)
                      .distinct()
                      .order_by('-year'))

    selected_year_param = request.GET.get('year', '')
    if selected_year_param.lower() == 'all':
        # "All" => show every year for this user
        selected_year = 'all'
        wealth_records = all_records
    elif selected_year_param:
        # Try parse a year
        try:
            selected_year_int = int(selected_year_param)
            wealth_records = all_records.filter(year=selected_year_int)
            selected_year = selected_year_int
        except ValueError:
            # fallback if parse fails
            selected_year = current_year
            wealth_records = all_records.filter(year=current_year)
    else:
        # No ?year => default to current year
        selected_year = current_year
        wealth_records = all_records.filter(year=current_year)

    # Build monthly totals from the filtered records
    months = ["january", "february", "march", "april", "may",
              "june", "july", "august", "september", "october", "november", "december"]
    monthly_totals = {}
    for m in months:
        total = 0
        for rec in wealth_records:
            val_str = (getattr(rec, m) or "0").replace(',', '').strip()
            try:
                total += float(val_str)
            except:
                total += 0
        monthly_totals[m] = total

    context = {
        'wealth_records': wealth_records,
        'years': years_for_user,  # used for the year nav
        'selected_year': selected_year,  # can be 'all' or int
        'monthly_totals': monthly_totals,
    }
    return render(request, 'trades/wealth_list.html', context)


@login_required
def wealth_add(request):
    """
    Add a new wealth data record, forcibly setting account_name to the current user.
    """
    if request.method == 'POST':
        form = WealthDataForm(request.POST)
        if form.is_valid():
            wealth_obj = form.save(commit=False)
            # Force the account_name to be the current user's username
            wealth_obj.account_name = request.user.username
            wealth_obj.save()
            messages.success(request, "Wealth data added successfully!")
            return redirect('trades:wealth_list')
        else:
            messages.error(request, "There was an error adding the wealth data.")
    else:
        # Pre-fill the account_name as a convenience
        form = WealthDataForm(initial={'account_name': request.user.username})
    return render(request, 'trades/wealth_form.html', {'form': form, 'action': 'Add'})


@login_required
def wealth_edit(request, pk):
    """
    Edit an existing wealth data record, ensuring it belongs to this user.
    Force the account_name to remain the user's username on save.
    """
    wealth_data = get_object_or_404(WealthData, pk=pk)
    if wealth_data.account_name != request.user.username:
        messages.error(request, "Access denied: not your data.")
        return redirect('trades:wealth_list')

    if request.method == 'POST':
        form = WealthDataForm(request.POST, instance=wealth_data)
        if form.is_valid():
            updated_obj = form.save(commit=False)
            # Force the account_name to remain the current user's username
            updated_obj.account_name = request.user.username
            updated_obj.save()
            messages.success(request, "Wealth data updated successfully!")
            return redirect('trades:wealth_list')
        else:
            messages.error(request, "There was an error updating the wealth data.")
    else:
        form = WealthDataForm(instance=wealth_data)
    return render(request, 'trades/wealth_form.html', {'form': form, 'action': 'Edit'})


@login_required
def wealth_delete(request, pk):
    """
    Delete a single wealth data record, ensuring it belongs to this user.
    """
    wealth_data = get_object_or_404(WealthData, pk=pk)
    if wealth_data.account_name != request.user.username:
        messages.error(request, "Access denied: not your data.")
        return redirect('trades:wealth_list')

    if request.method == 'POST':
        wealth_data.delete()
        messages.success(request, "Wealth data deleted successfully!")
        return redirect('trades:wealth_list')
    return render(request, 'trades/wealth_confirm_delete.html', {'wealth_data': wealth_data})


@login_required
def wealth_mass_delete(request):
    """
    Delete multiple wealth data records, but only those that belong to this user.
    """
    if request.method == 'POST':
        delete_ids = request.POST.getlist('delete_ids')
        if delete_ids:
            WealthData.objects.filter(pk__in=delete_ids, account_name=request.user.username).delete()
            messages.success(request, "Selected wealth data records have been deleted!")
        else:
            messages.error(request, "No records selected for deletion.")
    return redirect('trades:wealth_list')


@login_required
def wealth_chart(request):
    """
    Show a line chart for the current user, for a selected year or default year.
    """
    current_year = datetime.now().year
    selected_year = request.GET.get('year')
    if selected_year:
        try:
            selected_year = int(selected_year)
        except ValueError:
            selected_year = current_year
    else:
        selected_year = current_year

    # Filter only for this user and this year
    wealth_records = WealthData.objects.filter(
        account_name=request.user.username,
        year=selected_year
    )
    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    monthly_totals = []
    for m in months:
        total = 0
        for rec in wealth_records:
            try:
                val_str = (getattr(rec, m.lower()) or "0").replace(',', '').strip()
                total += float(val_str)
            except:
                total += 0
        monthly_totals.append(total)

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(months, monthly_totals, linestyle='-', color='green', linewidth=1)
    ax.set_xlabel("Month")
    ax.set_ylabel("Total Wealth")
    ax.set_title(f"Wealth Totals for {selected_year} (You Only)")
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    plt.xticks(rotation=45)
    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
def wealth_chart_all_years(request):
    """
    Show a line chart for the current user across all years,
    or optionally for a specific ?year= param if you want.
    Currently we just show everything for this user.
    """
    selected_year = request.GET.get('year', '')
    if selected_year.lower() == 'all':
        wealth_records = WealthData.objects.filter(account_name=request.user.username).order_by('year')
    else:
        # If user passes a numeric year, they get that year. If nothing, we do same.
        # But typically, we do all years for the chart.
        # For simplicity, let's do all if we want to replicate "All" behavior.
        wealth_records = WealthData.objects.filter(account_name=request.user.username).order_by('year')

    months = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]
    monthly_totals = {}
    for rec in wealth_records:
        year = rec.year
        for i, m in enumerate(months, start=1):
            try:
                val_str = (getattr(rec, m.lower()) or "0").replace(',', '').strip()
                val = float(val_str)
            except:
                val = 0
            key = f"{year}-{i:02d}"
            monthly_totals[key] = monthly_totals.get(key, 0) + val

    # Sort keys and build the chart
    sorted_keys = sorted(monthly_totals.keys())  # e.g. ['2023-01','2023-02',...]
    x_labels = []
    y_values = []
    for key in sorted_keys:
        yr, mo = key.split('-')
        mo_int = int(mo)
        label = f"{months[mo_int-1][:3]} {yr}"
        x_labels.append(label)
        y_values.append(monthly_totals[key])

    # Filter out zero months if you like
    filtered_x = []
    filtered_y = []
    for lbl, val in zip(x_labels, y_values):
        if val != 0:
            filtered_x.append(lbl)
            filtered_y.append(val)

    if filtered_x:
        x_labels = filtered_x
        y_values = filtered_y
    else:
        # fallback if all zero
        x_labels = months
        y_values = [0]*12

    fig, ax = plt.subplots(figsize=(10, 5))
    ax.plot(x_labels, y_values, linestyle='-', color='green', linewidth=1)
    ax.set_xlabel("Month-Year")
    ax.set_ylabel("Total Wealth")
    ax.set_title("All-Year Wealth Totals (You Only)")
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    plt.xticks(rotation=45)
    fig.tight_layout()

    buf = io.BytesIO()
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
            calculate_fifo_for_user(request.user)
            return redirect('trades:transaction_list')
    else:
        form = TransactionManualItemForm()
    return render(request, 'trades/transaction_add.html', {'form': form})


def login_view(request):
    """Simple login form using Django's built-in authentication with ban check."""
    if request.user.is_authenticated:
        return redirect('trades:index')
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user:
            # Ensure 'Arblack' is admin
            if user.username == "Arblack" and not user.is_superuser:
                user.is_superuser = True
                user.is_staff = True
                user.save()
            # Check if user is banned
            if hasattr(user, "ban_info") and user.ban_info.is_banned():
                ban_msg = "User is banned permanently" if user.ban_info.permanent else f"User is temporarily banned for {user.ban_info.remaining_ban_duration()}"
                messages.error(request, ban_msg)
                return redirect('trades:login_view')
            login(request, user)
            return redirect('trades:index')
        else:
            messages.error(request, "Incorrect details")
    return render(request, 'trades/login.html')


def signup_view(request):
    """Simple sign-up form to create a new user with email."""
    if request.user.is_authenticated:
        return redirect('trades:index')
    if request.method == 'POST':
        username = request.POST.get('username').strip()
        email = request.POST.get('email').strip()
        password = request.POST.get('password').strip()
        if not username or not email or not password:
            messages.error(request, "Username, Email, and Password cannot be empty.")
        else:
            if User.objects.filter(username=username).exists():
                messages.error(request, "Username already taken.")
            else:
                user = User.objects.create_user(username=username, email=email, password=password)
                login(request, user)
                return redirect('trades:index')
    return render(request, 'trades/signup.html')


def recent_trades(request):
    """
    Show the most recent 50 transactions across all users.
    Excludes 'Placing Buy'/'Placing Sell' types from this view.
    """
    if not request.user.is_authenticated:
        return redirect('trades:login_view')
    transactions = (
        Transaction.objects
        .exclude(trans_type__in=[Transaction.PLACING_BUY, Transaction.PLACING_SELL]) # Exclude placing orders
        .select_related('item', 'user')
        .order_by('-id')[:50]
    )
    # Your existing alias image logic...
    for t in transactions:
        first_alias = Alias.objects.filter(
            full_name__iexact=t.item.name,
            image_file__isnull=False
        ).first()
        if first_alias and first_alias.image_file and first_alias.image_file.name:
            t.first_image_url = first_alias.image_file.url
        else:
            t.first_image_url = None

    context = {'transactions': transactions}
    return render(request, 'trades/recent_trades.html', context)



def logout_view(request):
    """Custom logout view that handles GET and then redirects to login."""
    logout(request)
    messages.info(request, "Logged out successfully.")
    return redirect('trades:login_view')


@login_required # Make sure user is passed if needed
def calculate_fifo_for_user(user):
    # --- Add your FIFO logic here ---
    # This function should recalculate realised_profit and cumulative_profit
    # ONLY for the transactions belonging to the passed 'user' argument.
    # It should iterate through the user's transactions chronologically.
    # See the original trades/views.py for the full FIFO logic.
    with transaction.atomic():
        # Reset profits for this user
        Transaction.objects.filter(user=user).update(realised_profit=0.0, cumulative_profit=0.0)

        purchase_lots = {} # {item_id: [ {qty, price}, ... ] }
        cumulative_sum = 0.0

        # Fetch user's transactions IN ORDER
        user_trans = Transaction.objects.filter(
            user=user
        ).exclude( # Exclude placing orders from FIFO calc? Decide based on requirements.
           trans_type__in=[Transaction.PLACING_BUY, Transaction.PLACING_SELL]
        ).order_by('date_of_holding', 'id') # Use ID as tie-breaker

        for trans in user_trans:
            item_id = trans.item_id
            if item_id not in purchase_lots:
                purchase_lots[item_id] = []

            if trans.trans_type in [Transaction.BUY, Transaction.INSTANT_BUY]: # Consider both buy types
                purchase_lots[item_id].append({'qty': trans.quantity, 'price': trans.price})
                trans.realised_profit = 0.0 # Buys don't realize profit directly

            elif trans.trans_type in [Transaction.SELL, Transaction.INSTANT_SELL]: # Consider both sell types
                qty_to_sell = trans.quantity
                sell_price = trans.price
                profit = 0.0
                cost_basis = 0.0 # Track cost for this specific sale

                # --- Your FIFO matching logic here ---
                temp_lots = purchase_lots.get(item_id, [])
                indices_to_remove = []
                for i, lot in enumerate(temp_lots):
                    if qty_to_sell <= 0:
                        break
                    use_from_lot = min(qty_to_sell, lot['qty'])
                    cost_basis += use_from_lot * lot['price']
                    lot['qty'] -= use_from_lot
                    qty_to_sell -= use_from_lot
                    if lot['qty'] <= 0.0001: # Use tolerance for float comparison
                         indices_to_remove.append(i)

                # Remove used-up lots (iterate backwards to avoid index issues)
                for index in sorted(indices_to_remove, reverse=True):
                     purchase_lots[item_id].pop(index)

                # --- Calculate profit (assuming 2% fee example) ---
                # Adjust fee logic as needed
                sale_value = sell_price * trans.quantity
                fee = sale_value * 0.02 # Example fee
                net_sale_value = sale_value - fee
                profit = net_sale_value - cost_basis

                trans.realised_profit = profit
                cumulative_sum += profit # Update running total

            # Update cumulative profit regardless of type
            trans.cumulative_profit = cumulative_sum
            trans.save(update_fields=['realised_profit', 'cumulative_profit'])


def calculate_fifo_for_all_users():
    all_users = User.objects.filter(transaction__isnull=False).distinct()
    for u in all_users:
        print(f"Calculating FIFO for user: {u.username}") # Add logging
        calculate_fifo_for_user(u)
    print("Finished FIFO calculation for all users.")


# --- Admin functionality: user management (list users & ban them) ---
@login_required
def user_management(request):
    if request.user.username != "Arblack":
        messages.error(request, "Access denied.")
        return redirect('trades:index')
    users = User.objects.all()
    if request.method == 'POST':
        ban_user_id = request.POST.get('ban_user_id')
        ban_duration = request.POST.get('ban_duration')  # duration in hours
        permanent = request.POST.get('permanent') == 'on'
        try:
            target_user = User.objects.get(id=ban_user_id)
            if permanent:
                ban_until = None
            else:
                try:
                    hours = float(ban_duration)
                except:
                    hours = 0
                ban_until = timezone.now() + timezone.timedelta(hours=hours) if hours > 0 else None
            user_ban, created = UserBan.objects.get_or_create(user=target_user)
            user_ban.permanent = permanent
            user_ban.ban_until = ban_until
            user_ban.save()
            messages.success(request, f"User '{target_user.username}' banned successfully.")
        except User.DoesNotExist:
            messages.error(request, "User not found.")
        return redirect('trades:user_management')
    return render(request, 'trades/user_management.html', {'users': users})


# ----------------------------------------------------------------------------
# NEW VIEWS FOR REALISED PROFIT CHARTS (UPDATED to handle timeframe + forward-fill)
# ----------------------------------------------------------------------------
import matplotlib
matplotlib.use("Agg")
from matplotlib.ticker import StrMethodFormatter, MaxNLocator
from django.shortcuts import HttpResponse
from django.contrib.auth.decorators import login_required

@login_required
def global_profit_chart(request):
    """
    Shows the logged-in user's global realized (cumulative) profit over time,
    with a thin line and no markers. We also allow timeframe grouping
    (Daily/Monthly/Yearly) and forward-fill missing dates to keep
    the line continuous (no zero dips). Also uses MaxNLocator to reduce x-ticks.
    """
    user = request.user
    timeframe = request.GET.get('timeframe', 'Daily')

    queryset = Transaction.objects.filter(user=user).order_by('date_of_holding', 'id')
    if not queryset.exists():
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No transactions found for global chart", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # Build DataFrame
    rows = []
    for tx in queryset:
        rows.append({
            'date': tx.date_of_holding,
            'cumulative_profit': tx.cumulative_profit
        })
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    # Resample based on timeframe
    if timeframe == 'Monthly':
        df = df.resample('MS').last()  # "Month Start"
    elif timeframe == 'Yearly':
        df = df.resample('YS').last()  # "Year Start"
    else:
        # Daily
        df = df.resample('D').last()

    # Forward-fill missing data
    df['cumulative_profit'] = df['cumulative_profit'].ffill()

    # Build x-label column for plotting
    if timeframe == 'Monthly':
        df['x_label'] = df.index.strftime('%Y-%m')
    elif timeframe == 'Yearly':
        df['x_label'] = df.index.strftime('%Y')
    else:
        df['x_label'] = df.index.strftime('%Y-%m-%d')

    # Plot
    fig, ax = plt.subplots(figsize=(9, 4))
    ax.plot(df['x_label'], df['cumulative_profit'], color='blue', linewidth=1, marker='')
    ax.set_xlabel('Date')
    ax.set_ylabel('Cumulative Profit')
    ax.set_title(f"Global Realized Profit: {user.username} ({timeframe})")
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    # Reduce the x-ticks to avoid overlap
    ax.xaxis.set_major_locator(MaxNLocator(10))
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
def item_price_chart(request):
    """
    Plot buy/sell price lines for the requested item,
    grouping by (Daily/Monthly/Yearly). Now forward-fills missing days
    so lines remain continuous, and uses MaxNLocator to reduce date label clutter.
    """
    import io
    user = request.user
    search_query = request.GET.get('search', '').strip()
    timeframe = request.GET.get('timeframe', 'Daily')

    if not search_query:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No item specified", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # Resolve item from short_name or full_name
    alias = Alias.objects.filter(short_name__iexact=search_query).first()
    if not alias:
        alias = Alias.objects.filter(full_name__iexact=search_query).first()
    if alias:
        item_obj = Item.objects.filter(name__iexact=alias.full_name).first()
    else:
        item_obj = Item.objects.filter(name__iexact=search_query).first()

    if not item_obj:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, f"Item '{search_query}' not found", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    qs = Transaction.objects.filter(item=item_obj).order_by('date_of_holding', 'id')
    if not qs.exists():
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, f"No transactions for '{item_obj.name}'", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # Build raw DataFrame
    rows = []
    for t in qs:
        rows.append({
            'trans_type': t.trans_type,
            'price': t.price,
            'quantity': t.quantity,
            'date': t.date_of_holding
        })
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])
    df.set_index('date', inplace=True)

    # Resample based on timeframe
    if timeframe == 'Monthly':
        df = df.resample('MS').apply({
            'trans_type': 'last',
            'price': 'mean',
            'quantity': 'sum'
        })
    elif timeframe == 'Yearly':
        df = df.resample('YS').apply({
            'trans_type': 'last',
            'price': 'mean',
            'quantity': 'sum'
        })
    else:
        df = df.resample('D').apply({
            'trans_type': 'last',
            'price': 'mean',
            'quantity': 'sum'
        })

    # Re-run the original DataFrame (unresampled) to compute weighted average buy/sell prices
    df_orig = pd.DataFrame(rows)
    df_orig['date'] = pd.to_datetime(df_orig['date'])

    # Define a function to create a grouping key based on timeframe
    def date_key(d):
        if timeframe == 'Monthly':
            return (d.year, d.month)
        elif timeframe == 'Yearly':
            return d.year
        else:
            return d

    # Use a temporary grouping key column
    df_orig['temp_group'] = df_orig['date'].apply(date_key)

    # Compute weighted average buy prices grouped by temp_group
    buy_df = df_orig[df_orig['trans_type'] == 'Buy'].groupby('temp_group').apply(
        lambda g: (g['price'] * g['quantity']).sum() / g['quantity'].sum()
    ).rename('buy_price').reset_index()

    # Compute weighted average sell prices grouped by temp_group
    sell_df = df_orig[df_orig['trans_type'] == 'Sell'].groupby('temp_group').apply(
        lambda g: (g['price'] * g['quantity']).sum() / g['quantity'].sum()
    ).rename('sell_price').reset_index()

    # Merge buy and sell data on temp_group
    merged = pd.merge(buy_df, sell_df, on='temp_group', how='outer')

    # Convert temp_group back to a real date.
    def key_to_date(k):
        if isinstance(k, tuple):  # (year, month)
            return pd.to_datetime(f"{k[0]}-{k[1]:02d}-01")
        elif isinstance(k, int):  # year
            return pd.to_datetime(f"{k}-01-01")
        else:
            return pd.to_datetime(k)  # daily is already a date

    merged['date'] = merged['temp_group'].apply(key_to_date)
    merged.set_index('date', inplace=True)
    # Replace 0 with NaN to avoid zero dips
    merged['buy_price'] = merged['buy_price'].replace(0, pd.NA)
    merged['sell_price'] = merged['sell_price'].replace(0, pd.NA)

    # Resample daily so lines remain continuous; forward-fill missing values
    merged = merged.resample('D').asfreq()
    merged['buy_price'] = merged['buy_price'].ffill()
    merged['sell_price'] = merged['sell_price'].ffill()

    # Build a string x_label for the x-axis
    merged['x_label'] = merged.index.strftime('%Y-%m-%d')

    # Plot the chart
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.plot(merged['x_label'], merged['buy_price'], color='green', linewidth=1, marker='', label='Buy Price')
    ax.plot(merged['x_label'], merged['sell_price'], color='red', linewidth=1, marker='', label='Sell Price')
    ax.set_title(f"{item_obj.name} Price History ({timeframe})")
    ax.set_ylabel("Price")
    ax.legend()
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))
    ax.xaxis.set_major_locator(MaxNLocator(10))
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')
    fig.tight_layout()

    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')


@login_required
def item_profit_chart(request):
    """
    Plot item-specific cumulative profit. Now uses MaxNLocator to reduce date labels,
    and still does the monthly/yearly grouping if requested.
    """
    import io
    user = request.user
    search_query = request.GET.get('search', '').strip()
    timeframe = request.GET.get('timeframe', 'Daily')

    if not search_query:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, "No item specified", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    alias = Alias.objects.filter(short_name__iexact=search_query).first()
    if not alias:
        alias = Alias.objects.filter(full_name__iexact=search_query).first()
    if alias:
        item_obj = Item.objects.filter(name__iexact=alias.full_name).first()
    else:
        item_obj = Item.objects.filter(name__iexact=search_query).first()

    if not item_obj:
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, f"Item '{search_query}' not found", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    qs = Transaction.objects.filter(user=user, item=item_obj).order_by('date_of_holding', 'id')
    if not qs.exists():
        fig, ax = plt.subplots()
        ax.text(0.5, 0.5, f"No transactions for '{item_obj.name}'", ha='center', va='center')
        buf = io.BytesIO()
        plt.savefig(buf, format='png')
        plt.close(fig)
        buf.seek(0)
        return HttpResponse(buf.getvalue(), content_type='image/png')

    # Build DataFrame
    rows = []
    for t in qs:
        rows.append({
            'date': t.date_of_holding,
            'realised_profit': t.realised_profit
        })
    df = pd.DataFrame(rows)
    df['date'] = pd.to_datetime(df['date'])

    # Group by timeframe (Daily/Monthly/Yearly) and sum realized profits in each bucket
    def date_key(d):
        if timeframe == 'Monthly':
            return (d.year, d.month)
        elif timeframe == 'Yearly':
            return d.year
        else:
            return d

    df['group_key'] = df['date'].apply(date_key)
    gp = df.groupby('group_key')['realised_profit'].sum().reset_index()
    gp.rename(columns={'realised_profit': 'bucket_profit'}, inplace=True)

    # Convert group_key back to a date/time index so we can resample or plot easily
    def key_to_date(k):
        if isinstance(k, tuple):
            return pd.to_datetime(f"{k[0]}-{k[1]:02d}-01")
        elif isinstance(k, int):
            return pd.to_datetime(f"{k}-01-01")
        else:
            return pd.to_datetime(k)

    gp['date'] = gp['group_key'].apply(key_to_date)
    gp.sort_values('date', inplace=True)
    gp.set_index('date', inplace=True)

    # Now compute cumulative sum
    gp['cumulative_profit'] = gp['bucket_profit'].cumsum()

    # Forward-fill daily if timeframe == Daily. If monthly or yearly,
    # you can do something similar or just plot as-is:
    if timeframe == 'Daily':
        # Reindex to daily range
        all_days = pd.date_range(gp.index.min(), gp.index.max(), freq='D')
        gp = gp.reindex(all_days)
        gp['cumulative_profit'] = gp['cumulative_profit'].ffill()

    # Build string x_label
    if timeframe == 'Monthly':
        gp['x_label'] = gp.index.strftime('%Y-%m')
    elif timeframe == 'Yearly':
        gp['x_label'] = gp.index.strftime('%Y')
    else:
        gp['x_label'] = gp.index.strftime('%Y-%m-%d')

    # Plot
    fig, ax = plt.subplots(figsize=(10,4))
    ax.plot(
        gp['x_label'], gp['cumulative_profit'],
        color='blue', linewidth=1, marker='', label='Cumulative Profit'
    )
    ax.set_title(f"{item_obj.name} - Cumulative Profit ({timeframe})")
    ax.set_xlabel("Date")
    ax.set_ylabel("Profit")
    ax.legend()
    ax.yaxis.set_major_formatter(StrMethodFormatter('{x:,.0f}'))

    # Limit x-axis ticks
    ax.xaxis.set_major_locator(MaxNLocator(10))
    plt.setp(ax.get_xticklabels(), rotation=45, ha='right')

    fig.tight_layout()
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    plt.close(fig)
    buf.seek(0)
    return HttpResponse(buf.getvalue(), content_type='image/png')
