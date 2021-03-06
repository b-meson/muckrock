"""
View mixins
"""

# Django
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.models import User

# Standard Library
import logging
import sys
from datetime import date

# Third Party
import stripe

# MuckRock
from muckrock.accounts.models import Profile
from muckrock.accounts.utils import (
    mailchimp_subscribe,
    mixpanel_event,
    unique_username,
)
from muckrock.core.utils import generate_key
from muckrock.message.tasks import gift, welcome_miniregister

logger = logging.getLogger(__name__)


def split_name(name):
    """Splits a full name into a first and last name."""
    # infer first and last names from the full name
    # limit first and last names to 30 characters each
    if ' ' in name:
        first_name, last_name = name.rsplit(' ', 1)
        first_name = first_name[:30]
        last_name = last_name[:30]
    else:
        first_name = name[:30]
        last_name = ''
    return first_name, last_name


class MiniregMixin(object):
    """A mixin to expose miniregister functionality to a view"""
    minireg_source = 'Default'

    def miniregister(self, full_name, email, newsletter=False):
        """Create a new user from their full name and email and login"""
        password = generate_key(12)
        full_name = full_name.strip()
        username = unique_username(full_name)
        first_name, last_name = split_name(full_name)
        # create a new User
        user = User.objects.create_user(
            username,
            email,
            password,
            first_name=first_name,
            last_name=last_name
        )
        # create a new Profile
        Profile.objects.create(
            user=user,
            acct_type='basic',
            monthly_requests=settings.MONTHLY_REQUESTS.get('basic', 0),
            date_update=date.today()
        )
        # send the new user a welcome email
        welcome_miniregister.delay(user)
        user = authenticate(
            username=user.username,
            password=password,
        )
        login(self.request, user)
        if newsletter:
            mailchimp_subscribe(
                self.request,
                user.email,
                source='Mini-Register: {}'.format(self.minireg_source),
                url='https://{}{}'.format(
                    settings.MUCKROCK_URL, self.request.path
                ),
            )

        mixpanel_event(
            self.request,
            'Sign Up',
            {
                'Source': 'Mini-Register: {}'.format(self.minireg_source),
                'Newsletter': newsletter,
            },
            signup=True,
        )
        return user


class BuyRequestsMixin(object):
    """Buy requests functionality"""

    def buy_requests(self, form, recipient=None):
        """Buy requests"""
        if recipient is None:
            recipient = self.request.user
        try:
            form.buy_requests(recipient)
        except stripe.StripeError as exc:
            messages.error(self.request, 'Payment Error')
            logger.warn('Payment error: %s', exc, exc_info=sys.exc_info())
            return

        num_requests = form.cleaned_data['num_requests']
        price = form.get_price(num_requests)
        self.request.session['ga'] = 'request_purchase'
        mixpanel_event(
            self.request,
            'Requests Purchased',
            {
                'Number': num_requests,
                'Recipient': recipient.username,
                'Price': price / 100,
            },
            charge=price / 100,
        )
        if recipient == self.request.user:
            msg = (
                'Purchase successful.  {} requests have been added to your'
                'account.'.format(num_requests)
            )
        else:
            msg = (
                'Purchase successful.  {} requests have been gifted to'
                '{}.'.format(num_requests, recipient.first_name)
            )
            gift.delay(
                recipient,
                self.request.user,
                '{} requests'.format(num_requests),
            )
        messages.success(self.request, msg)
