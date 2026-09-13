import json
from collections import defaultdict

from .models import CreditCard, Transaction


def build_cartoes_json(user):
    """Builds the {card_id: {due_day, closing_day, closed_months}} memory shared by
    every "+ Despesa" form (navbar modal and the full Nova Despesa page).

    closed_months is derived from past Transactions marked force_next_invoice=True,
    grouped by "YYYY-MM" of purchase_date. That's the memory that lets a variable
    -closing card (closing_day=None, e.g. Santander) remember, for a given month,
    that the invoice had already closed by the time a purchase was made - fixed
    -closing cards (e.g. Nubank) don't need it since the backend can calculate the
    cutoff from closing_day alone (see CreditCard.get_actual_due_date).
    """
    cards = list(CreditCard.objects.for_user(user))

    closed_months_by_card = defaultdict(set)
    marked_txns = Transaction.objects.filter(
        owner=user, force_next_invoice=True, credit_card_id__in=[c.id for c in cards]
    ).values_list('credit_card_id', 'purchase_date')
    for card_id, purchase_date in marked_txns:
        closed_months_by_card[card_id].add(f"{purchase_date.year}-{purchase_date.month:02d}")

    return json.dumps({
        card.id: {
            'due_day': card.due_day,
            'closing_day': card.closing_day,
            'closed_months': sorted(closed_months_by_card[card.id]),
        }
        for card in cards
    })
