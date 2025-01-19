# trades/models.py

from django.db import models
from django.utils import timezone

class Alias(models.Model):
    """
    Aliases for items, linking a shorter name to a full name + optional image.
    """
    full_name = models.CharField(max_length=200, unique=False)
    short_name = models.CharField(max_length=100, blank=True)
    image_path = models.CharField(max_length=300, blank=True)

    def __str__(self):
        return f"{self.short_name} -> {self.full_name}"

class Item(models.Model):
    """
    An Item can be uniquely identified by its 'full name'.
    (Alternatively, we can unify to the full_name of an Alias if needed.)
    """
    name = models.CharField(max_length=200, unique=True)

    def __str__(self):
        return self.name

class Transaction(models.Model):
    BUY = 'Buy'
    SELL = 'Sell'
    TYPE_CHOICES = [
        (BUY, 'Buy'),
        (SELL, 'Sell'),
    ]
    item = models.ForeignKey(Item, on_delete=models.CASCADE)
    trans_type = models.CharField(max_length=4, choices=TYPE_CHOICES, default=BUY)
    price = models.FloatField()
    quantity = models.FloatField()
    date_of_holding = models.DateField(default=timezone.now)

    # Realized/cumulative profit columns (optional)
    realised_profit = models.FloatField(default=0.0)
    cumulative_profit = models.FloatField(default=0.0)

    def __str__(self):
        return f"{self.item.name} {self.trans_type} {self.quantity} @ {self.price}"

class AccumulationPrice(models.Model):
    """
    Stores accumulation price per item.
    """
    item = models.OneToOneField(Item, on_delete=models.CASCADE)
    accumulation_price = models.FloatField(default=0.0)

    def __str__(self):
        return f"{self.item.name} Acc. Price = {self.accumulation_price}"

class TargetSellPrice(models.Model):
    """
    Stores target sell price per item.
    """
    item = models.OneToOneField(Item, on_delete=models.CASCADE)
    target_sell_price = models.FloatField(default=0.0)

    def __str__(self):
        return f"{self.item.name} Target Sell = {self.target_sell_price}"

class Membership(models.Model):
    """
    Tracks membership info (like 'Yes'/'No' + end date) per account.
    """
    account_name = models.CharField(max_length=100, unique=True)
    membership_status = models.CharField(max_length=10, default="No")  # "Yes"/"No"
    membership_end_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.account_name} -> {self.membership_status}"

class WealthData(models.Model):
    """
    Yearly-based wealth data, storing monthly columns as decimal or text.
    If you prefer, you can create a separate model for each month, or a row per month.
    For simplicity, we keep a single row per (account, year).
    """
    account_name = models.CharField(max_length=100)
    year = models.IntegerField(default=2024)
    january = models.CharField(max_length=50, blank=True)
    february = models.CharField(max_length=50, blank=True)
    march = models.CharField(max_length=50, blank=True)
    april = models.CharField(max_length=50, blank=True)
    may = models.CharField(max_length=50, blank=True)
    june = models.CharField(max_length=50, blank=True)
    july = models.CharField(max_length=50, blank=True)
    august = models.CharField(max_length=50, blank=True)
    september = models.CharField(max_length=50, blank=True)
    october = models.CharField(max_length=50, blank=True)
    november = models.CharField(max_length=50, blank=True)
    december = models.CharField(max_length=50, blank=True)

    def __str__(self):
        return f"{self.account_name} {self.year}"

class Watchlist(models.Model):
    """
    Tracks items user is watching, for either 'Buy' or 'Sell' goals.
    """
    BUY = 'Buy'
    SELL = 'Sell'
    CHOICES = [
        (BUY, 'Buy'),
        (SELL, 'Sell'),
    ]
    name = models.CharField(max_length=200)
    desired_price = models.FloatField(default=0.0)
    date_added = models.DateField(default=timezone.now)
    buy_or_sell = models.CharField(max_length=4, choices=CHOICES, default=BUY)
    account_name = models.CharField(max_length=100, blank=True)
    wished_quantity = models.FloatField(default=0.0)
    total_value = models.FloatField(default=0.0)
    current_holding = models.FloatField(default=0.0)

    # We do keep membership columns commented out per your code’s style:
    membership_status = models.CharField(max_length=10, default="", blank=True)
    membership_end_date = models.DateField(blank=True, null=True)

    def __str__(self):
        return f"{self.name} -> {self.buy_or_sell} @ {self.desired_price}"
