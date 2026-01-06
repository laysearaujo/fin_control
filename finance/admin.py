from django.contrib import admin
from .models import Categoria, CartaoCredito, Transacao, Parcela, Receita, GastoFixo

admin.site.register(Receita)
admin.site.register(GastoFixo)
admin.site.register(Categoria)
admin.site.register(CartaoCredito)
admin.site.register(Transacao)
# Parcelas eu geralmente não registro para não poluir, ou uso como readonly