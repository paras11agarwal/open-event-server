import copy
from datetime import datetime, timedelta

import flask_login
from flask import flash
from flask import request, jsonify
from flask import url_for
from flask_admin import expose
from werkzeug.exceptions import abort
from werkzeug.utils import redirect
from flask.ext import login

from app import forex
from app.helpers.data import save_to_db, delete_from_db
from app.helpers.data_getter import DataGetter
from app.helpers.payment import get_fee
from app.models.user import User
from app.models.system_role import CustomSysRole, UserSystemRole
from app.views.admin.super_admin.super_admin_base import SuperAdminBaseView, SALES
from app.helpers.ticketing import TicketingManager
from app.helpers.invoicing import InvoicingManager

class SuperAdminSalesView(SuperAdminBaseView):
    PANEL_NAME = SALES
    display_currency = 'USD'

    @expose('/')
    def index(self):
        return redirect(url_for('.sales_by_events_view', path='events'))

    @expose('/fees/')
    def fees_by_events_view(self):
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')

        if ('from_date' in request.args and not from_date) or ('to_date' in request.args and not to_date) or \
            ('from_date' in request.args and 'to_date' not in request.args) or \
                ('to_date' in request.args and 'from_date' not in request.args):

            return redirect(url_for('.fees_by_events_view'))

        marketer_role = CustomSysRole.query.filter_by(name='Marketer').first()
        marketer_id = login.current_user.id if login.current_user.is_sys_role(marketer_role.id) else None

        if from_date and to_date:
            orders = TicketingManager.get_orders(
                from_date=datetime.strptime(from_date, '%d/%m/%Y'),
                to_date=datetime.strptime(to_date, '%d/%m/%Y'),
                status='completed',
                marketer_id=marketer_id
            )
        else:
            orders = TicketingManager.get_orders(status='completed', marketer_id=marketer_id)

        events = DataGetter.get_all_events()

        fee_summary = {}
        for event in events:
            fee_summary[str(event.id)] = {
                'name': event.name,
                'payment_currency': event.payment_currency,
                'fee_rate': get_fee(event.payment_currency),
                'fee_amount': 0,
                'tickets_count': 0
            }

        fee_total = 0
        tickets_total = 0

        for order in orders:
            for order_ticket in order.tickets:
                fee_summary[str(order.event.id)]['tickets_count'] += order_ticket.quantity
                tickets_total += order_ticket.quantity
                ticket = TicketingManager.get_ticket(order_ticket.ticket_id)
                if order.paid_via != 'free' and order.amount > 0 and ticket.price > 0:
                    fee = ticket.price * (get_fee(order.event.payment_currency)/100)
                    fee = forex(order.event.payment_currency, self.display_currency, fee)
                    fee_summary[str(order.event.id)]['fee_amount'] += fee
                    fee_total += fee

        return self.render('/gentelella/admin/super_admin/sales/fees.html',
                           fee_summary=fee_summary,
                           display_currency=self.display_currency,
                           from_date=from_date,
                           to_date=to_date,
                           tickets_total=tickets_total,
                           fee_total=fee_total)

    @expose('/fees/status/')
    def fees_status_view(self):
        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')

        if ('from_date' in request.args and not from_date) or ('to_date' in request.args and not to_date) or \
            ('from_date' in request.args and 'to_date' not in request.args) or \
                ('to_date' in request.args and 'from_date' not in request.args):

            return redirect(url_for('.fees_status_view'))

        if from_date and to_date:
            invoices = InvoicingManager.get_invoices(
                from_date=datetime.strptime(from_date, '%d/%m/%Y'),
                to_date=datetime.strptime(to_date, '%d/%m/%Y'),
            )
        else:
            invoices = InvoicingManager.get_invoices()

        return self.render('/gentelella/admin/super_admin/sales/fees_status.html',
                           display_currency=self.display_currency,
                           from_date=from_date,
                           current_date=datetime.now(),
                           overdue_date=datetime.now() + timedelta(days=15),
                           invoices=invoices,
                           to_date=to_date)

    @expose('/<path>/')
    def sales_by_events_view(self, path):

        from_date = request.args.get('from_date')
        to_date = request.args.get('to_date')

        if ('from_date' in request.args and not from_date) or ('to_date' in request.args and not to_date) or \
            ('from_date' in request.args and 'to_date' not in request.args) or \
                ('to_date' in request.args and 'from_date' not in request.args):

            return redirect(url_for('.sales_by_events_view', path=path))

        marketer_role = CustomSysRole.query.filter_by(name='Marketer').first()
        marketer_id = login.current_user.id if login.current_user.is_sys_role(marketer_role.id) else None

        if from_date and to_date:
            orders = TicketingManager.get_orders(
                from_date=datetime.strptime(from_date, '%d/%m/%Y'),
                to_date=datetime.strptime(to_date, '%d/%m/%Y'),
                marketer_id=marketer_id
            )
        else:
            orders = TicketingManager.get_orders(marketer_id=marketer_id)

        events = DataGetter.get_all_events()

        completed_count = 0
        completed_amount = 0
        tickets_count = 0

        orders_summary = {
            'completed': {
                'class': 'success',
                'tickets_count': 0,
                'orders_count': 0,
                'total_sales': 0
            },
            'pending': {
                'class': 'warning',
                'tickets_count': 0,
                'orders_count': 0,
                'total_sales': 0
            },
            'expired': {
                'class': 'danger',
                'tickets_count': 0,
                'orders_count': 0,
                'total_sales': 0
            }
        }

        tickets_summary_event_wise = {}
        tickets_summary_organizer_wise = {}
        tickets_summary_location_wise = {}
        for event in events:
            tickets_summary_event_wise[str(event.id)] = {
                'name': event.name,
                'payment_currency': event.payment_currency,
                'completed': {
                    'tickets_count': 0,
                    'sales': 0
                },
                'pending': {
                    'tickets_count': 0,
                    'sales': 0
                },
                'expired': {
                    'class': 'danger',
                    'tickets_count': 0,
                    'sales': 0
                }
            }
            tickets_summary_organizer_wise[str(event.creator_id)] = \
                copy.deepcopy(tickets_summary_event_wise[str(event.id)])
            if event.creator:
                tickets_summary_organizer_wise[str(event.creator_id)]['name'] = event.creator.email

            tickets_summary_location_wise[unicode(event.searchable_location_name)] = \
                copy.deepcopy(tickets_summary_event_wise[str(event.id)])
            tickets_summary_location_wise[unicode(event.searchable_location_name)]['name'] = \
                event.searchable_location_name

        for order in orders:
            if order.status == 'initialized':
                order.status = 'pending'
            orders_summary[str(order.status)]['orders_count'] += 1
            orders_summary[str(order.status)]['total_sales'] += forex(order.event.payment_currency,
                                                                      self.display_currency, order.amount)
            for order_ticket in order.tickets:
                orders_summary[str(order.status)]['tickets_count'] += order_ticket.quantity
                ticket = TicketingManager.get_ticket(order_ticket.ticket_id)
                tickets_summary_event_wise[str(order.event_id)][str(order.status)]['tickets_count'] \
                    += order_ticket.quantity
                tickets_summary_organizer_wise[str(order.event.creator_id)][str(order.status)]['tickets_count'] \
                    += order_ticket.quantity
                tickets_summary_location_wise[str(order
                                                  .event.searchable_location_name)][str(order
                                                                                        .status)]['tickets_count'] \
                    += order_ticket.quantity

                if order.paid_via != 'free' and order.amount > 0:
                    tickets_summary_event_wise[str(order.event_id)][str(order.status)]['sales'] += \
                        order_ticket.quantity * ticket.price
                    tickets_summary_organizer_wise[str(order.event.creator_id)][str(order.status)]['sales'] += \
                        order_ticket.quantity * ticket.price
                    tickets_summary_location_wise[str(order.event.
                                                      searchable_location_name)][str(order.
                                                                                     status)]['sales'] += \
                        order_ticket.quantity * ticket.price

        if path == 'events':
            return self.render('/gentelella/admin/super_admin/sales/by_events.html',
                               tickets_summary=tickets_summary_event_wise,
                               display_currency=self.display_currency,
                               from_date=from_date,
                               to_date=to_date,
                               orders_summary=orders_summary)
        elif path == 'organizers':
            return self.render('/gentelella/admin/super_admin/sales/by_organizer.html',
                               tickets_summary=tickets_summary_organizer_wise,
                               display_currency=self.display_currency,
                               from_date=from_date,
                               to_date=to_date,
                               orders_summary=orders_summary)
        elif path == 'locations':
            return self.render('/gentelella/admin/super_admin/sales/by_location.html',
                               tickets_summary=tickets_summary_location_wise,
                               display_currency=self.display_currency,
                               from_date=from_date,
                               to_date=to_date,
                               orders_summary=orders_summary)

        else:
            abort(404)

    @expose('/discounts/', methods=('GET',))
    @flask_login.login_required
    def discount_codes_view(self):
        discount_codes = InvoicingManager.get_discount_codes()
        return self.render('/gentelella/admin/super_admin/sales/discount_codes.html')

    @expose('/discounts/create/', methods=('GET', 'POST'))
    @flask_login.login_required
    def discount_codes_create(self, discount_code_id=None):
        if request.method == 'POST':
            InvoicingManager.create_edit_discount_code(request.form)
            flash("The discount code has been added.", "success")
            return redirect(url_for('.discount_codes_view'))
        discount_code = None
        if discount_code_id:
            discount_code = InvoicingManager.get_discount_code(discount_code_id)

        user_roles = UserSystemRole.query.filter(CustomSysRole.name == 'Marketer').all()

        active_users_ids = [x.id for x in user_roles]

        marketers = User.query.filter(User.id.in_(active_users_ids)).all()

        return self.render('/gentelella/admin/super_admin/sales/discount_codes_create.html',
                           discount_code=discount_code, marketers=marketers)

    @expose('/discounts/check/duplicate/', methods=('GET',))
    @flask_login.login_required
    def check_duplicate_discount_code(self):
        code = request.args.get('code')
        current = request.args.get('current')
        if not current:
            current = ''
        discount_code = InvoicingManager.get_discount_code(code)
        if (current == "" and discount_code) or (current != "" and discount_code and discount_code.id != int(current)):
            return jsonify({
                "status": "invalid"
            }), 404

        return jsonify({
            "status": "valid"
        }), 200

    @expose('/discounts/<int:discount_code_id>/edit/', methods=('GET', 'POST'))
    @flask_login.login_required
    def discount_codes_edit(self, discount_code_id=None):
        if not InvoicingManager.get_discount_code(discount_code_id):
            abort(404)
        if request.method == 'POST':
            InvoicingManager.create_edit_discount_code(request.form, discount_code_id)
            flash("The discount code has been edited.", "success")
            return redirect(url_for('.discount_codes_view'))
        return self.discount_codes_create(discount_code_id)

    @expose('/discounts/<int:discount_code_id>/toggle/', methods=('GET',))
    @flask_login.login_required
    def discount_codes_toggle(self, discount_code_id=None):
        discount_code = InvoicingManager.get_discount_code(discount_code_id)
        if not discount_code:
            abort(404)
        discount_code.is_active = not discount_code.is_active
        save_to_db(discount_code)
        message = "Activated." if discount_code.is_active else "Deactivated."
        flash("The discount code has been " + message, "success")
        return redirect(url_for('.discount_codes_view'))

    @expose('/discounts/<int:discount_code_id>/delete/', methods=('GET',))
    @flask_login.login_required
    def discount_codes_delete(self, discount_code_id=None):
        discount_code = InvoicingManager.get_discount_code(discount_code_id)
        if not discount_code:
            abort(404)
        delete_from_db(discount_code, "Discount code deleted")
        flash("The discount code has been deleted.", "warning")
        return redirect(url_for('.discount_codes_view'))