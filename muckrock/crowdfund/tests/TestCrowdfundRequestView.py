"""
Tests for crowdfund app
"""

from django.test import TestCase, Client

from datetime import datetime, date, timedelta
from decimal import Decimal
import logging
from nose.tools import ok_, eq_
import stripe

from muckrock.crowdfund.forms import CrowdfundRequestForm, CrowdfundRequestPaymentForm
from muckrock.crowdfund.models import CrowdfundRequest, CrowdfundRequestPayment
from muckrock.foia.models import FOIARequest
from muckrock.task.models import CrowdfundTask
from muckrock.settings import STRIPE_SECRET_KEY

# pylint: disable=missing-docstring
# pylint: disable=line-too-long

def get_stripe_token():
    """
    Helper function for creating a dummy Stripe token.
    Normally, the token would be generated by Stripe Checkout on the front end.
    """
    token = stripe.Token.create(
        card={
            "number": '4242424242424242',
            "exp_month": 12,
            "exp_year": 2016,
            "cvc": '123'
    })
    ok_(token)
    return token.id

class TestCrowdfundRequestView(TestCase):
    """Tests the Detail view for CrowdfundRequest objects"""

    fixtures = ['holidays.json', 'jurisdictions.json', 'agency_types.json', 'test_users.json',
                'test_agencies.json', 'test_profiles.json', 'test_foiarequests.json',
                'test_foiacommunications.json']

    def setUp(self):
        """Form submission will only happen after Stripe Checkout verifies the purchase on the front end. Assume the presence of the Stripe token and email address."""
        stripe.api_key = STRIPE_SECRET_KEY
        foia = FOIARequest.objects.get(pk=18)
        due = datetime.today() + timedelta(30)
        self.crowdfund = CrowdfundRequest.objects.create(
            foia=foia,
            name='Test Crowdfund',
            description='Testing contributions to this request',
            payment_required=foia.price,
            date_due=due
        )
        self.url = self.crowdfund.get_absolute_url()
        self.client = Client()
        self.data = {
            'amount': 200,
            'show': '',
            'crowdfund': self.crowdfund.pk,
            'email': 'test@example.com'
        }

    def test_view(self):
        response = self.client.get(self.url)
        eq_(response.status_code, 200,
            'The crowdfund view should resolve and be visible to everyone')

    def post(self, data):
        # need a unique token for each POST
        form = CrowdfundRequestPaymentForm(data)
        ok_(form.is_valid())
        data['token'] = get_stripe_token()
        logging.info(data)
        response = self.client.post(self.url, data=data)
        ok_(response, 'The server should respond to the post request')
        return response

    def test_anonymous_contribution(self):
        """After posting the payment, the email, and the token, the server should process the payment before creating and returning a payment object."""
        self.post(self.data)
        payment = CrowdfundRequestPayment.objects.get(crowdfund=self.crowdfund)
        eq_(payment.user, None,
            ('If the user is logged out, the returned payment'
            ' object should not reference any account.'))

    def test_anonymous_while_logged_in(self):
        """An attributed contribution checks if the user is logged in, but still defaults to anonymity."""
        self.client.login(username='adam', password='abc')
        self.post(self.data)
        payment = CrowdfundRequestPayment.objects.get(crowdfund=self.crowdfund)
        eq_(payment.user, None,
            ('If the user is logged in, the returned payment'
            ' object should not reference their account.'))

    def test_attributed_contribution(self):
        """An attributed contribution is opted-in by the user"""
        self.client.login(username='adam', password='abc')
        self.data['show'] = True
        self.post(self.data)
        payment = CrowdfundRequestPayment.objects.get(crowdfund=self.crowdfund)
        ok_(payment.user,
            ('If the user is logged in and opts into attribution, the returned'
            ' payment object should reference their user account.'))
        eq_(payment.user.username, 'adam',
            'The logged in user should be associated with the payment.')

    def test_correct_amount(self):
        """Amounts come in from stripe in units of .01. The payment object should account for this and transform it into a Decimal object for storage."""
        self.post(self.data)
        payment = CrowdfundRequestPayment.objects.get(crowdfund=self.crowdfund)
        amount = Decimal(float(self.data['amount'])/100)
        eq_(payment.amount, amount,
            'Payment object should clean and transform the amount')

    def test_contributors(self):
        """The crowdfund can get a list of all its contibutors by parsing its list of payments."""
        # anonymous payment
        self.post(self.data)
        # anonymous payment
        self.client.login(username='adam', password='abc')
        self.post(self.data)
        # attributed payment
        self.data['show'] = True
        self.post(self.data)

        new_crowdfund = CrowdfundRequest.objects.get(pk=self.crowdfund.pk)
        contributors = new_crowdfund.contributors()
        logging.info(contributors)
        ok_(contributors, 'Crowdfund should generate a list of contributors')
        eq_(len(contributors), 3, 'All contributions should return some kind of user')
        eq_(sum(contributor.is_anonymous() is True for contributor in contributors), 2,
            'There should only be two anonymous users in this list')

    def test_limit_amount(self):
        """No more than the amount required should be paid."""
        data = self.data
        data['amount'] = 20000
        self.post(data)
        payment = CrowdfundRequestPayment.objects.get(crowdfund=self.crowdfund)
        eq_(payment.amount, self.crowdfund.payment_required,
            'The amount should be capped at the crowdfund\'s required payment.')

    def test_completion(self):
        """The crowdfund should fast-forward its due date and create a task when completed."""
        crowdfund_task_count = CrowdfundTask.objects.count()
        data = self.data
        data['amount'] = int(self.crowdfund.payment_required)*100
        self.post(data)
        updated_crowdfund = CrowdfundRequest.objects.get(pk=self.crowdfund.pk)
        eq_(updated_crowdfund.date_due, date.today(),
            'The due date should be the same as today.')
        eq_(CrowdfundTask.objects.count(), crowdfund_task_count + 1,
            'A new crowdfund task should be created.')
