from django.contrib import admin
from .models import Category, CreditCard, Transaction, Installment, Income, FixedExpense

admin.site.register(Income)
admin.site.register(FixedExpense)
admin.site.register(Category)
admin.site.register(CreditCard)
admin.site.register(Transaction)
# Installments (parcelas) usually not registered here to keep the admin clean