from .dashboard import dashboard
from .auth import signup
from .savings_boxes import (
    savings_boxes, new_savings_box, edit_savings_box, delete_savings_box,
    savings_box_detail, withdraw_savings_box, new_self_loan,
)
from .annual_analysis import annual_analysis
from .transactions import (
    new_transaction, new_income, statement, edit_transaction, delete_transaction,
)
from .credit_cards import (
    manage_credit_cards, new_credit_card, edit_credit_card, delete_credit_card,
    pay_monthly_invoice,
)
from .categories import (
    manage_categories, delete_category, save_leftover, new_category, edit_category,
    recategorize_pending, category_cards,
)
from .fixed_expenses import (
    manage_fixed_expenses, new_fixed_expense, delete_fixed_expense, pay_fixed_expense,
    edit_fixed_expense, remove_fixed_expense,
)
from .fixed_incomes import (
    manage_fixed_incomes, new_fixed_income, edit_fixed_income, edit_income, delete_fixed_income, delete_income,
)
from .reports import category_report, annual_report, category_expense_detail
from .one_off_bills import (
    add_one_off_bill, pay_one_off_bill, delete_one_off_bill, edit_one_off_bill,
)
