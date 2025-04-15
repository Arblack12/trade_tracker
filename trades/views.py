# trades/views.py
# Standard library imports
from django.contrib.auth import get_user_model
import io
from datetime import datetime

# Django imports
from django.shortcuts import render, redirect, get_object_or_404, Http404
from django.contrib import messages
from django.http import HttpResponse
from django.db.models import Sum, Avg, Max, F, ExpressionWrapper, fields
from django.utils import timezone # Already imported
from django.urls import reverse
from django.utils.http import urlencode
from django.contrib.auth.decorators import login_required
from django.contrib.auth import login, authenticate, logout
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction as db_transaction

# Third-party imports
import matplotlib
matplotlib.use("Agg") # Set backend before importing pyplot
import matplotlib.pyplot as plt
from matplotlib.ticker import StrMethodFormatter, MaxNLocator
import pandas as pd
import numpy as np
import pytz

# Local application imports
from .models import (
    Transaction, Item, Alias, AccumulationPrice, TargetSellPrice,
    Membership, Watchlist, UserProfile, UserBan, WealthData
)
from .forms import (
    TransactionManualItemForm, TransactionEditForm, AliasForm, AccumulationPriceForm,
    TargetSellPriceForm, MembershipForm, WatchlistForm, PlacingOrderForm,
    UserProfileForm, WealthDataForm
)
# Import middleware if needed (usually not needed in views)
# from .middleware import TimezoneMiddleware

ADMIN_USERNAME = "Arblack"
User = get_user_model()

# ==========================
# index View Modifications
# ==========================
@login_required # Ensure user is logged in
def index(request):
    """
    Unified homepage. Shows user's transactions for a searched item.
    Includes forms for 'Add Transaction' and 'Placing Order'.
    Displays a list of all current 'Placing Orders'.
    Allows ADMIN_USERNAME to update prices and edit/delete any transaction.
    """
    # Ensure authenticated check remains (already done by decorator)
    # if not request.user.is_authenticated:
    #     return redirect('trades:login_view')

    timeframe = request.GET.get('timeframe', 'Daily')
    edit_form = None
    add_transaction_form = TransactionManualItemForm() # Instantiate Add form
    placing_order_form = PlacingOrderForm() # Instantiate Place Order form
    active_form_name = 'add_transaction' # Default active form
    # --- Handle GET parameters for filtering ---
    placing_filter = request.GET.get('placing_filter', 'all') # Default to 'all'
    history_filter = request.GET.get('history_filter', 'my') # Default to 'my'

    # --- Handle Edit Request (GET) ---
    if 'edit_trans' in request.GET:
        try:
            t_id = int(request.GET['edit_trans'])
            # **** ADMIN CHECK FOR EDIT FETCH ****
            if request.user.username == ADMIN_USERNAME:
                t_obj = get_object_or_404(Transaction, id=t_id) # Admin gets any transaction
            else:
                # Regular user can only get their own
                t_obj = get_object_or_404(Transaction, id=t_id, user=request.user)

            form = TransactionEditForm()
            form.load_initial(t_obj) # Pass the fetched transaction object
            edit_form = form
            # If editing, maybe default to showing the 'Add Transaction' form area
            active_form_name = 'add_transaction' # Or set a specific 'edit' active state?
        except (Transaction.DoesNotExist, ValueError): # Catch potential errors
            messages.error(request, "Transaction to edit not found or permission denied.")
            # Redirect to avoid broken state, remove edit_trans param
            query_params = request.GET.copy()
            query_params.pop('edit_trans', None)
            return redirect(f"{reverse('trades:index')}?{urlencode(query_params)}")

    # --- Handle Form Submissions (POST) ---
    if request.method == 'POST':
        item_name_for_redirect = request.POST.get('item_name') # Get item name for redirect if needed

        # Determine which form was submitted
        if 'add_transaction_submit' in request.POST:
            active_form_name = 'add_transaction'
            tform = TransactionManualItemForm(request.POST)
            if tform.is_valid():
                new_trans = tform.save(user=request.user)
                messages.success(request, f"Transaction for {new_trans.item.name} added successfully!")
                calculate_fifo_for_user(request.user) # Use db_transaction alias if needed
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
            active_form_name = 'add_transaction' # Keep add form area visible? Or make 'edit' active?
            ef = TransactionEditForm(request.POST)
            if ef.is_valid():
                try:
                    # Pass user to form's update method for permission check there
                    updated_trans = ef.update_transaction(user=request.user)
                    messages.success(request, "Transaction updated.")
                    # Recalculate FIFO for the owner of the transaction
                    # We need the user object from the transaction itself now
                    if updated_trans.user:
                         calculate_fifo_for_user(updated_trans.user)
                    url = reverse('trades:index')
                    qs = urlencode({'search': updated_trans.item.name})
                    return redirect(f"{url}?{qs}")
                except Http404: # Catch permission errors from the form's save method
                     messages.error(request, "Transaction not found or permission denied.")
                     return redirect(reverse('trades:index'))
                # Catch any other potential errors during update
                except Exception as e:
                     messages.error(request, f"An unexpected error occurred during update: {e}")
                     edit_form = ef # Show edit form with errors


            else:
                messages.error(request, "Error updating transaction.")
                edit_form = ef # Show edit form with errors

        elif 'delete_transaction' in request.POST:
            # No specific active form needed, it redirects anyway
            t_id = request.POST.get('transaction_id')
            if t_id:
                try:
                    # **** ADMIN CHECK FOR DELETE FETCH ****
                    if request.user.username == ADMIN_USERNAME:
                        t_obj = get_object_or_404(Transaction, id=t_id) # Admin deletes any
                    else:
                        t_obj = get_object_or_404(Transaction, id=t_id, user=request.user) # User deletes own

                    item_name = t_obj.item.name
                    owner_user = t_obj.user # Get owner before deleting
                    t_obj.delete()
                    messages.success(request, "Transaction deleted.")

                    # Recalculate FIFO for the user whose transaction was deleted
                    if owner_user:
                        calculate_fifo_for_user(owner_user)

                    url = reverse('trades:index')
                    qs = urlencode({'search': item_name}) # Go back to the item's page
                    return redirect(f"{url}?{qs}")
                except (Transaction.DoesNotExist, ValueError):
                    messages.error(request, "Transaction not found or permission denied.")
                    # Redirect to avoid broken state
                    query_params = request.GET.copy()
                    # Ensure delete_transaction isn't a GET param causing loops
                    query_params.pop('delete_transaction', None)
                    return redirect(f"{reverse('trades:index')}?{urlencode(query_params)}")
            else:
                 messages.error(request, "Transaction ID missing for deletion.")
                 return redirect(reverse('trades:index'))


        elif 'update_accumulation' in request.POST or 'update_target_sell' in request.POST:
            # **** ADMIN CHECK FOR PRICE UPDATES ****
            if request.user.username != ADMIN_USERNAME:
                messages.error(request, "Permission denied: Only administrators can update prices.")
                # Redirect back, preserving search query if possible
                search_query_val = request.POST.get('search', '') # Get search from POST if possible
                url = reverse('trades:index')
                if search_query_val:
                     qs = urlencode({'search': search_query_val})
                     return redirect(f"{url}?{qs}")
                else:
                     return redirect(url)
            # ---- END ADMIN CHECK ----

            # Handle Accumulation/Target Sell Price Updates (Keep existing logic)
            item_id = request.POST.get('acc_item_id') or request.POST.get('ts_item_id')
            item_name_for_redirect = None # Will be set below if successful

            if item_id:
                try:
                    item_obj = Item.objects.get(id=item_id)
                    item_name_for_redirect = item_obj.name # Get name for redirect
                    if 'update_accumulation' in request.POST:
                        acc_price_str = request.POST.get('accumulation_price')
                        if acc_price_str is not None:
                            ap, _ = AccumulationPrice.objects.get_or_create(item=item_obj)
                            ap.accumulation_price = float(acc_price_str) * 1_000_000 # Convert from millions
                            ap.save()
                            messages.success(request, f"Accumulation price updated for {item_obj.name}.")
                        else:
                            messages.error(request, "Accumulation price value missing.")

                    elif 'update_target_sell' in request.POST:
                        ts_price_str = request.POST.get('target_sell_price')
                        if ts_price_str is not None:
                            tsp, _ = TargetSellPrice.objects.get_or_create(item=item_obj)
                            tsp.target_sell_price = float(ts_price_str) * 1_000_000 # Convert from millions
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
    # ... (initialize variables: item_obj, stats=0, last_hit_times=None etc.) ...
    item_obj = None
    item_alias = None
    accumulation_obj = None
    target_obj = None
    item_transactions_qs = Transaction.objects.none() # Start with empty queryset
    user_page_obj = None
    placing_orders_qs = Transaction.objects.none() # Start with empty queryset
    placing_orders_page_obj = None

    # **** INITIALIZE VARIABLES WITH DEFAULTS ****
    user_items_per_page = 10   # <--- ADD INITIALIZATION HERE
    placing_orders_per_page = 10 # <-- Also ensure this is defined before use if needed elsewhere
    total_sold_qty = 0
    remaining_qty = 0
    avg_sold_price = 0
    item_profit = 0
    item_image_url = ""
    last_acc_hit_time = None
    last_target_hit_time = None
    history_title = ""

    # This calculation can stay here as it doesn't depend on search_query
    global_realised_profit = Transaction.objects.filter(user=request.user).aggregate(total=Max('cumulative_profit'))['total'] or 0
    potential_profit = None # Initialize variable

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

            # **** Query for Price Hit Timestamps ****
            if accumulation_obj:
                last_acc_hit = Transaction.objects.filter(
                    item=item_obj,
                    trans_type__in=[Transaction.BUY, Transaction.INSTANT_BUY],
                    price__lte=accumulation_obj.accumulation_price # Price less than or equal to accumulation
                ).order_by('-date_of_holding').first() # Get the most recent one
                if last_acc_hit:
                    last_acc_hit_time = last_acc_hit.date_of_holding

            if target_obj:
                last_target_hit = Transaction.objects.filter(
                    item=item_obj,
                    trans_type__in=[Transaction.SELL, Transaction.INSTANT_SELL],
                    price__gte=target_obj.target_sell_price # Price greater than or equal to target
                ).order_by('-date_of_holding').first() # Get the most recent one
                if last_target_hit:
                    last_target_hit_time = last_target_hit.date_of_holding
            # **** END Price Hit Query ****

            # *** Get Transaction History based on filter ***
            base_history_qs = Transaction.objects.filter(
                item=item_obj
            ).exclude( # Exclude placing orders from main history
                trans_type__in=[Transaction.PLACING_BUY, Transaction.PLACING_SELL]
            )

            if history_filter == 'my':
                item_transactions_qs = base_history_qs.filter(user=request.user)
                history_title = f"Your Transaction History for {item_obj.name}"
            else: # history_filter == 'all'
                item_transactions_qs = base_history_qs # No user filter
                history_title = f"All User History for {item_obj.name}"

            item_transactions_qs = item_transactions_qs.order_by('-date_of_holding', '-id')

            # *** Calculate Stats ***
            # Note: Stats like 'remaining_qty', 'item_profit' are currently calculated
            # ONLY based on the logged-in user's history (item_transactions_qs before filtering logic was split).
            # Decide if these stats should reflect "All User History" when that filter is active.
            # For now, let's keep calculating based on the logged-in user's data for simplicity.
            user_history_for_stats = base_history_qs.filter(user=request.user) # Query user's data specifically for stats
            sells = user_history_for_stats.filter(trans_type=Transaction.SELL)
            instant_sells = user_history_for_stats.filter(trans_type=Transaction.INSTANT_SELL)
            total_sold_qty = (sells.aggregate(sold_sum=Sum('quantity'))['sold_sum'] or 0) + \
                             (instant_sells.aggregate(sold_sum=Sum('quantity'))['sold_sum'] or 0)
            buys_qty = user_history_for_stats.filter(trans_type=Transaction.BUY).aggregate(buy_sum=Sum('quantity'))['buy_sum'] or 0
            instant_buys_qty = user_history_for_stats.filter(trans_type=Transaction.INSTANT_BUY).aggregate(buy_sum=Sum('quantity'))['buy_sum'] or 0
            remaining_qty = (buys_qty + instant_buys_qty) - total_sold_qty
            all_sells_qs = user_history_for_stats.filter(trans_type__in=[Transaction.SELL, Transaction.INSTANT_SELL])
            avg_sold_price = all_sells_qs.aggregate(avg_price=Avg('price'))['avg_price'] if all_sells_qs.exists() else 0
            item_profit = user_history_for_stats.aggregate(item_profit_sum=Sum('realised_profit'))['item_profit_sum'] or 0
            # *** End Stat Calculation ***


            # Paginate Transaction History (using the filtered qs)
            user_items_per_page = 25
            user_paginator = Paginator(item_transactions_qs, user_items_per_page)
            user_page_number = request.GET.get('user_page')
            user_page_obj = user_paginator.get_page(user_page_number)

        else:
            messages.warning(request, f"No item or alias found matching '{search_query}'.")
            history_title = "Transaction History" # Default title if no item

    else: # No search query
        history_title = "Your Recent Transaction History" # Or "All Recent..."? Defaulting to user's.
        # Optionally fetch recent transactions for the user even without search
        if history_filter == 'my':
             item_transactions_qs = Transaction.objects.filter(user=request.user).exclude(
                trans_type__in=[Transaction.PLACING_BUY, Transaction.PLACING_SELL]
             ).order_by('-date_of_holding', '-id')[:user_items_per_page] # Show first page directly
             user_paginator = Paginator(item_transactions_qs, user_items_per_page) # Still needed for page obj
             user_page_obj = user_paginator.get_page(1) # Get page 1 object
        # Add logic here if you want to show "All User" recent history by default when no search


    # --- Fetch Placing Orders based on filter ---
    base_placing_qs = Transaction.objects.filter(
        trans_type__in=[Transaction.PLACING_BUY, Transaction.PLACING_SELL]
    )
    # Filter by item if searched
    if item_obj:
        base_placing_qs = base_placing_qs.filter(item=item_obj)

    # Apply user filter
    if placing_filter == 'my':
        placing_orders_qs = base_placing_qs.filter(user=request.user)
        placing_orders_title = f"My Placing Orders"
        if item_obj: placing_orders_title += f" for {item_obj.name}"
    else: # placing_filter == 'all'
        placing_orders_qs = base_placing_qs # No user filter
        placing_orders_title = f"All Placing Orders"
        if item_obj: placing_orders_title += f" for {item_obj.name}"

    placing_orders_qs = placing_orders_qs.select_related('item', 'user').order_by('-date_of_holding', '-id')


    # Paginate Placing Orders
    placing_orders_per_page = 15
    placing_orders_paginator = Paginator(placing_orders_qs, placing_orders_per_page)
    placing_orders_page_number = request.GET.get('placing_page')
    placing_orders_page_obj = placing_orders_paginator.get_page(placing_orders_page_number)


    # --- Prepare Context ---
    context = {
        # ... forms, item info, stats ...
        'placing_filter': placing_filter,          # Pass filter states
        'history_filter': history_filter,          # Pass filter states
        'history_title': history_title,            # Pass dynamic title
        'placing_orders_title': placing_orders_title, # Pass dynamic title
        'item_transactions': user_page_obj,
        'user_page_obj': user_page_obj,
        'placing_orders': placing_orders_page_obj,
        'placing_orders_page_obj': placing_orders_page_obj,
        'search_query': search_query,
        'timeframe': timeframe,
        'ADMIN_USERNAME': ADMIN_USERNAME,
        'item': item_obj,
        'alias': item_alias,
        'accumulation': accumulation_obj,
        'target_sell': target_obj,
        'total_sold': total_sold_qty,
        'remaining_quantity': remaining_qty,
        'average_sold_price': avg_sold_price,
        'item_profit': item_profit,
        'item_image_url': item_image_url,
        'global_realised_profit': global_realised_profit,
        'last_acc_hit_time': last_acc_hit_time,
        'last_target_hit_time': last_target_hit_time,
        'active_form_name': active_form_name,
        'edit_form': edit_form,
        'add_transaction_form': add_transaction_form,
        'placing_order_form': placing_order_form,

    }

    # ---- TEMPORARY DEBUG PRINTING ----
    print(f"DEBUG: Current Django Time (UTC): {timezone.now()}")
    # Fetch the absolute latest transaction to check its timestamp
    latest_trans = Transaction.objects.order_by('-id').first()
    if latest_trans:
        print(f"DEBUG: Latest Tx Timestamp (from DB): {latest_trans.date_of_holding}")
        print(f"DEBUG: Latest Tx Timezone Info: {latest_trans.date_of_holding.tzinfo}")
    else:
        print("DEBUG: No transactions found in DB to check timestamp.")
    # ---- END DEBUG PRINTING ----

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
    # Use get_or_create to handle cases where profile might be missing
    # (though the signal should normally prevent this after user save)
    profile, created = UserProfile.objects.get_or_create(user=request.user)
    if created:
         print(f"Profile created on-the-fly for {request.user.username} in account view.") # Log if this happens

    if request.method == 'POST':
        form = UserProfileForm(request.POST, instance=profile)
        if form.is_valid():
            new_timezone = form.cleaned_data['time_zone']
            try:
                # Validate the timezone exists before saving
                pytz.timezone(new_timezone)
                form.save()
                messages.success(request, 'Timezone updated successfully!')
                # Activate the new timezone for the remainder of this request/response
                # The middleware will handle subsequent requests.
                timezone.activate(new_timezone)
            except pytz.exceptions.UnknownTimeZoneError:
                 messages.error(request, f"Invalid timezone '{new_timezone}' selected.")
            # Redirect back to account page even if error, form will repopulate
            return redirect('trades:account_page')
        else:
             messages.error(request, "Please correct the errors below.")
    else:
        # Populate form with current profile settings
        form = UserProfileForm(instance=profile)

    context = {
        'profile_form': form, # Use a distinct name like 'profile_form'
        # Get the timezone currently active for this request (set by middleware)
        'current_active_timezone': timezone.get_current_timezone_name()
    }
    return render(request, 'trades/account.html', context)


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


# ============================
# calculate_fifo_for_user - Ensure it exists and is correct
# ============================
# ... imports, User = get_user_model(), ADMIN_USERNAME ...

def calculate_fifo_for_user(user):
    User = get_user_model()
    if not user or not isinstance(user, User):
        print(f"FIFO Calc: Invalid user object received: {user}")
        return

    with db_transaction.atomic():
        Transaction.objects.filter(user=user).update(realised_profit=0.0, cumulative_profit=0.0)
        purchase_lots = {}
        cumulative_sum = 0.0
        user_trans = Transaction.objects.filter(
            user=user
        ).exclude(
            trans_type__in=[Transaction.PLACING_BUY, Transaction.PLACING_SELL]
        ).order_by('date_of_holding', 'id')

        for trans in user_trans:
            item_id = trans.item_id
            if item_id not in purchase_lots:
                purchase_lots[item_id] = []

            if trans.trans_type in [Transaction.BUY, Transaction.INSTANT_BUY]:
                purchase_lots[item_id].append({'qty': trans.quantity, 'price': trans.price})
                trans.realised_profit = 0.0

            elif trans.trans_type in [Transaction.SELL, Transaction.INSTANT_SELL]:
                qty_to_sell = trans.quantity
                sell_price = trans.price # <--- ADD THIS LINE BACK
                profit = 0.0
                cost_basis = 0.0
                temp_lots = purchase_lots.get(item_id, [])
                indices_to_remove = []
                qty_sold_from_lots = 0

                for i, lot in enumerate(temp_lots):
                    if qty_sold_from_lots >= qty_to_sell:
                         break
                    use_from_lot = min(qty_to_sell - qty_sold_from_lots, lot['qty'])
                    if use_from_lot <= 0: continue
                    cost_basis += use_from_lot * lot['price']
                    lot['qty'] -= use_from_lot
                    qty_sold_from_lots += use_from_lot
                    if lot['qty'] <= 0.0001:
                        indices_to_remove.append(i)

                for index in sorted(indices_to_remove, reverse=True):
                    if index < len(purchase_lots[item_id]):
                       purchase_lots[item_id].pop(index)
                    else:
                        print(f"FIFO Warning: Index {index} out of bounds for item {item_id} lots.")

                # --- Calculate profit (Reinstating 2% fee example) ---
                # Now 'sell_price' is defined before being used here
                sale_value = sell_price * trans.quantity
                fee = sale_value * 0.02
                net_sale_value = sale_value - fee

                if abs(qty_sold_from_lots - trans.quantity) > 0.0001:
                    profit = net_sale_value - cost_basis
                    print(f"FIFO Warning: Sold {trans.quantity} but only matched {qty_sold_from_lots} from lots for Tx ID {trans.id}. Calculated profit based on matched lots.")
                else:
                     profit = net_sale_value - cost_basis

                trans.realised_profit = profit
                cumulative_sum += profit

            # Update cumulative profit
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
