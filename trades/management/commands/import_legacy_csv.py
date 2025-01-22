# trades/management/commands/import_legacy_csv.py

import os
import csv
from datetime import datetime
from django.core.management.base import BaseCommand
from django.conf import settings
from django.contrib.auth.models import User
from django.db import transaction as db_transaction

# If you used the built-in datetime only, that’s fine. 
# If you want friendlier date parsing, you could use dateutil:
# from dateutil import parser

from trades.models import (
    Alias, Item, AccumulationPrice, TargetSellPrice,
    Membership, WealthData, Watchlist, Transaction
)
# We reuse your existing FIFO profit function so that 
# realized/cumulative profits are recalculated after importing:
from trades.views import calculate_fifo_profits


class Command(BaseCommand):
    help = "Import CSV data from old scripts into the new Django models."

    def add_arguments(self, parser):
        parser.add_argument(
            "--csvdir",
            type=str,
            default=".",
            help="Directory containing the CSV files (default current directory).",
        )

    @db_transaction.atomic
    def handle(self, *args, **options):
        csv_dir = options["csvdir"]

        self.stdout.write(self.style.SUCCESS(f"Starting CSV import from directory: {csv_dir}"))

        # 1) Import item_aliases.csv
        aliases_csv = os.path.join(csv_dir, "item_aliases.csv")
        if os.path.exists(aliases_csv):
            self.import_aliases(aliases_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {aliases_csv} (skipping)"))

        # 2) Import accumulation_prices.csv
        accum_csv = os.path.join(csv_dir, "accumulation_prices.csv")
        if os.path.exists(accum_csv):
            self.import_accumulation_prices(accum_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {accum_csv} (skipping)"))

        # 3) Import membership_data.csv
        membership_csv = os.path.join(csv_dir, "membership_data.csv")
        if os.path.exists(membership_csv):
            self.import_memberships(membership_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {membership_csv} (skipping)"))

        # 4) Import target_sell_prices.csv
        target_csv = os.path.join(csv_dir, "target_sell_prices.csv")
        if os.path.exists(target_csv):
            self.import_target_sell_prices(target_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {target_csv} (skipping)"))

        # 5) Import transactions.csv
        transactions_csv = os.path.join(csv_dir, "transactions.csv")
        if os.path.exists(transactions_csv):
            self.import_transactions(transactions_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {transactions_csv} (skipping)"))

        # 6) Import watchlist.csv
        watchlist_csv = os.path.join(csv_dir, "watchlist.csv")
        if os.path.exists(watchlist_csv):
            self.import_watchlist(watchlist_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {watchlist_csv} (skipping)"))

        # 7) Import wealth_data.csv
        wealth_csv = os.path.join(csv_dir, "wealth_data.csv")
        if os.path.exists(wealth_csv):
            self.import_wealth_data(wealth_csv)
        else:
            self.stdout.write(self.style.WARNING(f"File not found: {wealth_csv} (skipping)"))

        # Finally, recalc FIFO profits after all transaction data is loaded:
        self.stdout.write(self.style.SUCCESS("Recalculating FIFO profits..."))
        calculate_fifo_profits()

        self.stdout.write(self.style.SUCCESS("All CSV imports completed successfully!"))

    def import_aliases(self, filepath):
        """
        item_aliases.csv has columns:
        FullName,ShortName,ImagePath
        """
        self.stdout.write(f"Importing aliases from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                full_name = row["FullName"].strip()
                short_name = row["ShortName"].strip()
                image_path = row["ImagePath"].strip()

                # Create or update the Alias object
                alias, _ = Alias.objects.get_or_create(
                    full_name=full_name,
                    short_name=short_name
                )
                # We'll store image_path in the model's 'image_path' field:
                alias.image_path = image_path
                alias.save()

        self.stdout.write(self.style.SUCCESS("Aliases imported."))

    def import_accumulation_prices(self, filepath):
        """
        accumulation_prices.csv:
        Name,Accumulation Price
        """
        self.stdout.write(f"Importing accumulation prices from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item_name = row["Name"].strip()
                acc_price = float(row["Accumulation Price"] or 0)

                # Find or create the Item
                item_obj, _ = Item.objects.get_or_create(name=item_name)

                # Set accumulation price
                ap, _ = AccumulationPrice.objects.get_or_create(item=item_obj)
                ap.accumulation_price = acc_price
                ap.save()

        self.stdout.write(self.style.SUCCESS("Accumulation Prices imported."))

    def import_memberships(self, filepath):
        """
        membership_data.csv:
        Account Name,Membership Status,Membership End Date
        Example:
          Lord Fifty,Yes,2025-12-27
        """
        self.stdout.write(f"Importing memberships from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                acct_name = row["Account Name"].strip()
                mem_stat = row["Membership Status"].strip()
                end_date_str = row["Membership End Date"].strip()

                # Parse end date if not blank
                if end_date_str:
                    # Using built-in strptime:
                    end_date = datetime.strptime(end_date_str, "%Y-%m-%d").date()
                else:
                    end_date = None

                m, _ = Membership.objects.get_or_create(account_name=acct_name)
                m.membership_status = mem_stat if mem_stat else "No"
                m.membership_end_date = end_date
                m.save()

        self.stdout.write(self.style.SUCCESS("Membership data imported."))

    def import_target_sell_prices(self, filepath):
        """
        target_sell_prices.csv:
        Name,Target Sell Price
        """
        self.stdout.write(f"Importing target sell prices from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item_name = row["Name"].strip()
                target_price = float(row["Target Sell Price"] or 0)

                item_obj, _ = Item.objects.get_or_create(name=item_name)
                tsp, _ = TargetSellPrice.objects.get_or_create(item=item_obj)
                tsp.target_sell_price = target_price
                tsp.save()

        self.stdout.write(self.style.SUCCESS("Target Sell Prices imported."))

    def import_transactions(self, filepath):
        """
        transactions.csv:
        Name,Type,Price,Quantity,Date of Holding,Realised Profit,Cumulative Profit
        Example:
          Scripture of Wen,Buy,35005000.0,2.0,2024-09-05,0.0,352462880.0
        """
        self.stdout.write(f"Importing transactions from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                item_name = row["Name"].strip()
                trans_type = row["Type"].strip()   # "Buy" or "Sell"
                price = float(row["Price"] or 0)
                qty = float(row["Quantity"] or 0)
                date_str = row["Date of Holding"].strip()
                realized = float(row.get("Realised Profit", 0) or 0)
                cumulative = float(row.get("Cumulative Profit", 0) or 0)

                if date_str:
                    date_of_holding = datetime.strptime(date_str, "%Y-%m-%d").date()
                else:
                    date_of_holding = datetime.today().date()

                # Find or create the item
                item_obj, _ = Item.objects.get_or_create(name=item_name)

                # Create the transaction
                t = Transaction.objects.create(
                    user = User.objects.get(username="Arblack"),  # or set user=User.objects.get(username='someuser') if needed
                    item=item_obj,
                    trans_type=trans_type,
                    price=price,
                    quantity=qty,
                    date_of_holding=date_of_holding,
                    realised_profit=realized,
                    cumulative_profit=cumulative,
                )

        self.stdout.write(self.style.SUCCESS("Transactions imported."))

    def import_watchlist(self, filepath):
        """
        watchlist.csv:
        Name,Desired Price,Date Added,Buy or Sell,Account Name,Wished Quantity,
        Current Holding,Total Value,Membership Status,Membership End Date
        """
        self.stdout.write(f"Importing watchlist from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                name = row["Name"].strip()
                desired_price = float(row["Desired Price"] or 0)
                date_added_str = row["Date Added"].strip()
                buy_or_sell = row["Buy or Sell"].strip()
                account_name = row["Account Name"].strip()
                wished_qty = float(row["Wished Quantity"] or 0)
                current_holding = float(row["Current Holding"] or 0)
                total_value = float(row["Total Value"] or 0)
                membership_status = row["Membership Status"].strip()
                membership_end_str = row["Membership End Date"].strip()

                # Parse date_added if valid, else use today's date
                try:
                    date_added = datetime.strptime(date_added_str, "%Y-%m-%d").date()
                except ValueError:
                    date_added = datetime.today().date()

                # Parse membership_end if valid, else None
                membership_end = None
                if membership_end_str:
                    try:
                        membership_end = datetime.strptime(membership_end_str, "%Y-%m-%d").date()
                    except ValueError:
                        membership_end = None

                # Create watchlist
                w = Watchlist.objects.create(
                    name=name,
                    desired_price=desired_price,
                    date_added=date_added,
                    buy_or_sell=buy_or_sell if buy_or_sell in ["Buy","Sell"] else "Buy",
                    account_name=account_name,
                    wished_quantity=wished_qty,
                    total_value=total_value,
                    current_holding=current_holding,
                    membership_status=membership_status,
                    membership_end_date=membership_end,
                )

        self.stdout.write(self.style.SUCCESS("Watchlist imported."))

    def import_wealth_data(self, filepath):
        """
        wealth_data.csv:
        Year,Account Name,January,February,March,April,May,June,July,August,September,October,November,December
        """
        self.stdout.write(f"Importing wealth data from {filepath}...")
        with open(filepath, "r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            for row in reader:
                year = int(row["Year"].strip())
                acct_name = row["Account Name"].strip()

                # Create the wealth record
                wd = WealthData.objects.create(
                    account_name=acct_name,
                    year=year,
                    january=row["January"].strip(),
                    february=row["February"].strip(),
                    march=row["March"].strip(),
                    april=row["April"].strip(),
                    may=row["May"].strip(),
                    june=row["June"].strip(),
                    july=row["July"].strip(),
                    august=row["August"].strip(),
                    september=row["September"].strip(),
                    october=row["October"].strip(),
                    november=row["November"].strip(),
                    december=row["December"].strip(),
                )

        self.stdout.write(self.style.SUCCESS("Wealth data imported."))
