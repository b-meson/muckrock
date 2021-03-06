"""
Models for the Task application
"""

# Django
from django.conf import settings
from django.contrib.auth.models import User
from django.contrib.postgres.fields import JSONField
from django.core.mail import EmailMessage
from django.core.urlresolvers import reverse
from django.db import models, transaction
from django.db.models import Case, Count, Max, Prefetch, When
from django.db.models.functions import Cast, Now
from django.template.loader import render_to_string
from django.utils import timezone

# Standard Library
import logging
from datetime import date
from itertools import groupby

# MuckRock
from muckrock.agency.utils import initial_communication_template
from muckrock.communication.models import (
    EmailAddress,
    EmailError,
    FaxError,
    PhoneNumber,
)
from muckrock.core.models import ExtractDay
from muckrock.foia.models import STATUS, FOIANote, FOIARequest
from muckrock.jurisdiction.models import Jurisdiction
from muckrock.message.email import TemplateEmail
from muckrock.message.tasks import support
from muckrock.task.querysets import (
    CrowdfundTaskQuerySet,
    FlaggedTaskQuerySet,
    MultiRequestTaskQuerySet,
    NewAgencyTaskQuerySet,
    OrphanTaskQuerySet,
    PortalTaskQuerySet,
    ProjectReviewTaskQuerySet,
    ResponseTaskQuerySet,
    ReviewAgencyTaskQuerySet,
    SnailMailTaskQuerySet,
    StatusChangeTaskQuerySet,
    TaskQuerySet,
)

# pylint: disable=missing-docstring

SNAIL_MAIL_CATEGORIES = [
    ('a', 'Appeal'),
    ('n', 'New'),
    ('u', 'Update'),
    ('f', 'Followup'),
    ('p', 'Payment'),
]
PORTAL_CATEGORIES = [('i', 'Incoming')] + SNAIL_MAIL_CATEGORIES
PUBLIC_FLAG_CATEGORIES = [
    (
        'move communication',
        'A communication ended up on this request inappropriately.',
    ),
    (
        'no response',
        'This agency hasn\'t responded after multiple submissions.',
    ),
    (
        'wrong agency',
        'The agency has indicated that this request should be directed to '
        'another agency.',
    ),
    (
        'missing documents',
        'I should have received documents for this request.',
    ),
    (
        'form',
        'The agency has asked that you use a form.',
    ),
    (
        'follow-up complaints',
        'Agency is complaining about follow-up messages.',
    ),
    (
        'appeal',
        'Should I appeal this response?',
    ),
    (
        'proxy',
        'The agency denied the request due to an in-state citzenship law.',
    ),
]
PRIVATE_FLAG_CATEGORIES = [
    (
        'contact info changed',
        'User supplied contact info.',
    ),
    (
        'no proxy',
        'No proxy was available.',
    ),
    (
        'agency update',
        'An agency logged in to the site and updated a request.',
    ),
    (
        'agency new email',
        'An agency with no primary email set replied via email.',
    ),
]
FLAG_CATEGORIES = PUBLIC_FLAG_CATEGORIES + PRIVATE_FLAG_CATEGORIES


class Task(models.Model):
    """A base task model for fields common to all tasks"""
    date_created = models.DateTimeField(auto_now_add=True)
    date_done = models.DateTimeField(blank=True, null=True)
    date_deferred = models.DateField(blank=True, null=True)
    resolved = models.BooleanField(default=False, db_index=True)
    assigned = models.ForeignKey(
        User, blank=True, null=True, related_name="assigned_tasks"
    )
    resolved_by = models.ForeignKey(
        User, blank=True, null=True, related_name="resolved_tasks"
    )
    form_data = JSONField(blank=True, null=True)

    objects = TaskQuerySet.as_manager()

    class Meta:
        ordering = ['date_created']

    def __unicode__(self):
        return u'Task'

    def resolve(self, user=None, form_data=None):
        """Resolve the task"""
        self.resolved = True
        self.resolved_by = user
        self.date_done = timezone.now()
        if form_data is not None:
            self.form_data = form_data
        self.save()
        logging.info('User %s resolved task %s', user, self.pk)

    def defer(self, date_deferred):
        """Defer the task to the given date"""
        self.date_deferred = date_deferred
        self.save()


class OrphanTask(Task):
    """A communication that needs to be approved before showing it on the site"""
    type = 'OrphanTask'
    reasons = (('bs', 'Bad Sender'), ('ib', 'Incoming Blocked'),
               ('ia', 'Invalid Address'))
    reason = models.CharField(max_length=2, choices=reasons)
    communication = models.ForeignKey('foia.FOIACommunication')
    address = models.CharField(max_length=255)

    objects = OrphanTaskQuerySet.as_manager()
    template_name = 'task/orphan.html'

    def __unicode__(self):
        return u'Orphan Task'

    def display(self):
        """Display something useful and identifing"""
        return u'{}: {}'.format(
            self.get_reason_display(),
            self.address,
        )

    def get_absolute_url(self):
        return reverse('orphan-task', kwargs={'pk': self.pk})

    def move(self, foia_pks, user):
        """Moves the comm and creates a ResponseTask for it"""
        moved_comms = self.communication.move(foia_pks, user)
        for moved_comm in moved_comms:
            ResponseTask.objects.create(
                communication=moved_comm, created_from_orphan=True
            )
            moved_comm.make_sender_primary_contact()

    def reject(self, blacklist=False):
        """If blacklist is true, should blacklist the sender's domain."""
        if blacklist:
            self.blacklist()

    def get_sender_domain(self):
        """Gets the domain of the sender's email address."""
        try:
            return self.communication.emails.all()[0].from_email.domain
        except IndexError:
            return None

    def blacklist(self):
        """Adds the communication's sender's domain to the email blacklist."""
        domain = self.get_sender_domain()
        if domain is None:
            return
        try:
            blacklist, _ = BlacklistDomain.objects.get_or_create(domain=domain)
        except BlacklistDomain.MultipleObjectsReturned:
            blacklist = BlacklistDomain.objects.filter(domain=domain).first()
        blacklist.resolve_matches()


class SnailMailTask(Task):
    """A communication that needs to be snail mailed"""
    type = 'SnailMailTask'
    category = models.CharField(max_length=1, choices=SNAIL_MAIL_CATEGORIES)
    communication = models.ForeignKey('foia.FOIACommunication')
    user = models.ForeignKey(User, blank=True, null=True)
    amount = models.DecimalField(default=0.00, max_digits=8, decimal_places=2)
    switch = models.BooleanField(
        default=False,
        help_text='Designates we have switched to sending to this address '
        'from another formof communication due to some sort of error.  A '
        'note should be included in the communication with an explanation.',
    )

    objects = SnailMailTaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Snail Mail Task'

    def display(self):
        """Display something useful and identifing"""
        return u'{}: {}'.format(
            self.get_category_display(),
            self.communication.foia.title,
        )

    def get_absolute_url(self):
        return reverse('snail-mail-task', kwargs={'pk': self.pk})

    def set_status(self, status):
        """Set the status of the comm and FOIA affiliated with this task"""
        comm = self.communication
        comm.status = status
        comm.save()
        comm.foia.status = status
        comm.foia.save(comment='snail mail task')
        comm.foia.update()

    def update_text(self, new_text):
        """Sets the body text of the communication"""
        comm = self.communication
        comm.communication = new_text
        comm.save()

    def record_check(self, number, user):
        """Records the check to a note on the request"""
        foia = self.communication.foia
        text = "A check (#%(number)d) of $%(amount).2f was mailed to the agency." % {
            'number': number,
            'amount': self.amount
        }
        note = FOIANote.objects.create(foia=foia, note=text, author=user)
        if foia.agency.payable_to:
            payable_to = foia.agency.payable_to
        else:
            payable_to = foia.agency
        if foia.user.is_staff:
            type_ = 'Staff'
        else:
            type_ = 'User'
        context = {
            'number': number,
            'payable_to': payable_to,
            'amount': self.amount,
            'signed_by': user.get_full_name(),
            'foia_pk': foia.pk,
            'comm_pk': self.communication.pk,
            'type': type_,
            'today': date.today(),
        }
        body = render_to_string(
            'text/task/check.txt',
            context,
        )
        msg = EmailMessage(
            subject='[CHECK MAILED] Check #{}'.format(number),
            body=body,
            from_email='info@muckrock.com',
            to=[settings.CHECK_EMAIL],
            cc=['info@muckrock.com'],
            bcc=['diagnostics@muckrock.com'],
        )
        msg.send(fail_silently=False)
        return note


class ReviewAgencyTask(Task):
    """An agency has had one of its forms of communication have an error
    and new contact information is required"""
    type = 'ReviewAgencyTask'
    agency = models.ForeignKey('agency.Agency')

    objects = ReviewAgencyTaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Review Agency Task'

    def get_absolute_url(self):
        return reverse('review-agency-task', kwargs={'pk': self.pk})

    def get_review_data(self):
        """Get all the data on all open requests for the agency"""
        review_data = []

        def get_data(email_or_fax):
            """Helper function to get email or fax data"""
            if email_or_fax == 'email':
                address_model = EmailAddress
                error_model = EmailError
                confirm_rel = 'to_emails'
            elif email_or_fax == 'fax':
                address_model = PhoneNumber
                error_model = FaxError
                confirm_rel = 'faxes'

            open_requests = (
                self.agency.foiarequest_set.get_open().order_by(
                    '%s__status' % email_or_fax, email_or_fax
                ).exclude(**{
                    email_or_fax: None
                }).select_related(
                    'agency__jurisdiction',
                    'composer',
                    'email',
                    'fax',
                    'portal',
                ).annotate(
                    latest_response=ExtractDay(
                        Cast(
                            Now() - Max(
                                Case(
                                    When(
                                        communications__response=True,
                                        then='communications__datetime'
                                    )
                                )
                            ),
                            models.DurationField(),
                        )
                    )
                )
            )
            grouped_requests = [
                (k, list(v)) for k, v in
                groupby(open_requests, lambda f: getattr(f, email_or_fax))
            ]
            # do a seperate query for per email addr/fax number stats
            addresses = (
                address_model.objects.annotate(
                    error_count=Count('errors', distinct=True),
                    last_error=Max('errors__datetime'),
                    last_confirm=Max('%s__confirmed_datetime' % confirm_rel),
                ).prefetch_related(
                    Prefetch(
                        'errors',
                        error_model.objects.select_related(
                            '%s__communication__foia__agency__jurisdiction' %
                            email_or_fax
                        ).order_by('-datetime')
                    )
                )
            )
            if email_or_fax == 'email':
                addresses = addresses.annotate(
                    last_open=Max('opens__datetime'),
                )
            addresses = addresses.in_bulk(g[0].pk for g in grouped_requests)

            review_data = []
            for addr, foias in grouped_requests:
                # fetch the address with the annotated stats
                addr = addresses[addr.pk]
                review_data.append({
                    'address':
                        addr,
                    'error':
                        addr.status == 'error',
                    'errors':
                        addr.errors.all()[:5],
                    'foias':
                        foias,
                    'total_errors':
                        addr.error_count,
                    'last_error':
                        addr.last_error,
                    'last_confirm':
                        addr.last_confirm,
                    'last_open':
                        addr.last_open if email_or_fax == 'email' else None,
                    'checkbox_name':
                        'foias-%d-%s-%d' % (self.pk, email_or_fax, addr.pk),
                    'email_or_fax':
                        email_or_fax,
                })
            return review_data

        review_data.extend(get_data('email'))
        review_data.extend(get_data('fax'))
        # snail mail
        foias = list(
            self.agency.foiarequest_set.get_open().filter(
                email=None, fax=None
            ).select_related(
                'agency__jurisdiction',
                'composer',
                'email',
                'fax',
                'portal',
            ).annotate(
                latest_response=ExtractDay(
                    Cast(
                        Now() - Max(
                            Case(
                                When(
                                    communications__response=True,
                                    then='communications__datetime'
                                )
                            )
                        ),
                        models.DurationField(),
                    )
                )
            )
        )
        if foias:
            review_data.append({
                'address': 'Snail Mail',
                'foias': foias,
                'checkbox_name': '%d-snail' % self.pk,
            })

        return review_data

    def update_contact(self, email_or_fax, foia_list, update_info, snail):
        """Updates the contact info on the agency and the provided requests."""
        # pylint: disable=too-many-branches
        from muckrock.agency.models import AgencyEmail, AgencyPhone
        is_email = isinstance(email_or_fax, EmailAddress) and not snail
        is_fax = isinstance(email_or_fax, PhoneNumber) and not snail

        if update_info:
            # clear primary emails if we are updating with any new info
            agency_emails = (
                self.agency.agencyemail_set.filter(
                    request_type='primary', email_type='to'
                )
            )
            for agency_email in agency_emails:
                agency_email.request_type = 'none'
                agency_email.email_type = 'none'
                agency_email.save()

            # clear primary faxes if updating with a fax or snail mail address
            if is_fax or snail:
                agency_faxes = (
                    self.agency.agencyphone_set.filter(
                        request_type='primary', phone__type='fax'
                    )
                )
                for agency_fax in agency_faxes:
                    agency_fax.request_type = 'none'
                    agency_fax.save()

        if is_email:
            if update_info:
                AgencyEmail.objects.create(
                    email=email_or_fax,
                    agency=self.agency,
                    request_type='primary',
                    email_type='to',
                )
            for foia in foia_list:
                foia.email = email_or_fax
                if foia.fax and foia.fax.status != 'good':
                    foia.fax = None
                foia.save()

        elif is_fax:
            if update_info:
                AgencyPhone.objects.create(
                    phone=email_or_fax,
                    agency=self.agency,
                    request_type='primary',
                )
            for foia in foia_list:
                foia.email = None
                foia.fax = email_or_fax
                foia.save()

        elif snail:
            for foia in foia_list:
                foia.email = None
                foia.fax = None
                foia.address = self.agency.get_addresses().first()
                foia.save()

    def latest_response(self):
        """Returns the latest response from the agency"""
        return (
            self.agency.foiarequest_set.aggregate(
                max_date=Max('communications__datetime')
            )['max_date']
        )


class FlaggedTask(Task):
    """A user has flagged a request, agency or jurisdiction"""
    type = 'FlaggedTask'
    text = models.TextField()
    user = models.ForeignKey(User, blank=True, null=True)
    foia = models.ForeignKey('foia.FOIARequest', blank=True, null=True)
    agency = models.ForeignKey('agency.Agency', blank=True, null=True)
    jurisdiction = models.ForeignKey(Jurisdiction, blank=True, null=True)
    category = models.TextField(
        choices=FLAG_CATEGORIES,
        blank=True,
    )

    objects = FlaggedTaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Flagged Task'

    def display(self):
        """Display something useful and identifing"""
        if self.foia:
            return self.foia.title
        elif self.agency:
            return self.agency.name
        elif self.jurisdiction:
            return self.jurisdiction.name
        else:
            return 'None'

    def get_absolute_url(self):
        return reverse('flagged-task', kwargs={'pk': self.pk})

    def flagged_object(self):
        """Return the object that was flagged (should only ever be one, and never none)"""
        if self.foia:
            return self.foia
        elif self.agency:
            return self.agency
        elif self.jurisdiction:
            return self.jurisdiction
        else:
            raise AttributeError('No flagged object.')

    def reply(self, text):
        """Send an email reply to the user that raised the flag."""
        support.delay(self.user, text, self)


class ProjectReviewTask(Task):
    """Created when a project is published and needs approval."""
    type = 'ProjectReviewTask'
    project = models.ForeignKey('project.Project')
    notes = models.TextField(blank=True)

    objects = ProjectReviewTaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Project Review Task'

    def get_absolute_url(self):
        return reverse('projectreview-task', kwargs={'pk': self.pk})

    def reply(self, text, action='reply'):
        """Send an email reply to the user that raised the flag."""
        send_to = [
            contributor.email for contributor in self.project.contributors.all()
        ]
        project_email = TemplateEmail(
            to=send_to,
            extra_context={'action': action,
                           'message': text,
                           'task': self},
            subject=u'%s %s' % (self.project, action),
            text_template='message/project/%s.txt' % action,
            html_template='message/project/%s.html' % action
        )
        project_email.send(fail_silently=False)
        return project_email

    def approve(self, text):
        """Mark the project approved and notify the user."""
        self.project.approved = True
        self.project.date_approved = date.today()
        self.project.save()
        return self.reply(text, 'approved')

    def reject(self, text):
        """Mark the project private and notify the user."""
        self.project.private = True
        self.project.save()
        return self.reply(text, 'rejected')


class NewAgencyTask(Task):
    """A new agency has been created and needs approval"""
    type = 'NewAgencyTask'
    user = models.ForeignKey(User, blank=True, null=True)
    agency = models.ForeignKey('agency.Agency')

    objects = NewAgencyTaskQuerySet.as_manager()

    def __unicode__(self):
        return u'New Agency Task'

    def display(self):
        """Display something useful and identifing"""
        return self.agency.name

    def get_absolute_url(self):
        return reverse('new-agency-task', kwargs={'pk': self.pk})

    def approve(self):
        """Approves agency, resends pending requests to it"""
        self._resolve_agency()

    def reject(self, replacement_agency=None):
        """Reject agency, resend to replacement if one is specified"""
        if replacement_agency is not None:
            self._resolve_agency(replacement_agency)
        else:
            self.agency.status = 'rejected'
            self.agency.save()
            foias = (
                self.agency.foiarequest_set.select_related('composer')
                .annotate(count=Count('composer__foias'))
            )
            if foias:
                # only send an email if they submitted a request with it
                subject = u'We need your help with your request, "{}"'.format(
                    foias[0].title
                )
                if len(foias) > 1:
                    subject += u', and others'
                TemplateEmail(
                    subject=subject,
                    from_email='info@muckrock.com',
                    user=self.user,
                    text_template='task/email/agency_rejected.txt',
                    html_template='task/email/agency_rejected.html',
                    extra_context={
                        'agency': self.agency,
                        'foias': foias,
                        'url': settings.MUCKROCK_URL,
                    },
                ).send(fail_silently=False)
            for foia in foias:
                foia.composer.return_requests(1)
                foia.delete()
            for composer in self.agency.composers.all():
                composer.agencies.remove(self.agency)
                if composer.foias.count() == 0:
                    if composer.revokable():
                        composer.revoke()
                    composer.status = 'started'
                    composer.save()

    def _resolve_agency(self, replacement_agency=None):
        """Approves or rejects an agency and re-submits the pending requests"""
        if replacement_agency:
            self.agency.status = 'rejected'
            proxy_info = replacement_agency.get_proxy_info()
        else:
            self.agency.status = 'approved'
            proxy_info = self.agency.get_proxy_info()
        self.agency.save()
        for foia in self.agency.foiarequest_set.all():
            # first switch foia to use replacement agency
            if replacement_agency:
                foia.agency = replacement_agency
                foia.save(comment='new agency task')
            if foia.communications.exists():
                # regenerate communication text in case jurisdiction changed
                comm = foia.communications.first()
                comm.communication = initial_communication_template(
                    [foia.agency],
                    comm.from_user.get_full_name(),
                    foia.composer.requested_docs,
                    edited_boilerplate=foia.composer.edited_boilerplate,
                    proxy=proxy_info['proxy'],
                )
                comm.save()
                foia.submit(clear=True)

    def spam(self):
        """Reject the agency and block the user"""
        self.agency.status = 'rejected'
        self.agency.save()
        if self.user.is_authenticated:
            self.user.is_active = False
            self.user.save()
        self.agency.foiarequest_set.all().delete()


class ResponseTask(Task):
    """A response has been received and needs its status set"""
    type = 'ResponseTask'
    communication = models.ForeignKey('foia.FOIACommunication')
    created_from_orphan = models.BooleanField(default=False)
    # for predicting statuses
    predicted_status = models.CharField(
        max_length=10, choices=STATUS, blank=True, null=True
    )
    status_probability = models.IntegerField(blank=True, null=True)

    objects = ResponseTaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Response Task'

    def get_absolute_url(self):
        return reverse('response-task', kwargs={'pk': self.pk})

    def set_status(self, status):
        """Forward to form logic, for use in classify_status task"""
        from muckrock.task.forms import ResponseTaskForm
        form = ResponseTaskForm()
        form.set_status(status, set_foia=True, comms=[self.communication])


class StatusChangeTask(Task):
    """A user has changed the status on a request"""
    type = 'StatusChangeTask'
    user = models.ForeignKey(User)
    old_status = models.CharField(max_length=255)
    foia = models.ForeignKey('foia.FOIARequest')

    objects = StatusChangeTaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Status Change Task'

    def get_absolute_url(self):
        return reverse('status-change-task', kwargs={'pk': self.pk})


class CrowdfundTask(Task):
    """Created when a crowdfund is finished"""
    type = 'CrowdfundTask'
    crowdfund = models.ForeignKey('crowdfund.Crowdfund')

    objects = CrowdfundTaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Crowdfund Task'

    def get_absolute_url(self):
        return reverse('crowdfund-task', kwargs={'pk': self.pk})


class MultiRequestTask(Task):
    """Created when a composer with multiple agencies is created and needs
    approval.
    """
    type = 'MultiRequestTask'
    composer = models.ForeignKey('foia.FOIAComposer')

    objects = MultiRequestTaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Multi-Request Task'

    def get_absolute_url(self):
        return reverse('multirequest-task', kwargs={'pk': self.pk})

    def submit(self, agency_list):
        """Submit the composer"""
        # pylint: disable=not-callable
        from muckrock.foia.tasks import submit_composer
        return_requests = 0
        with transaction.atomic():
            for agency in self.composer.agencies.all():
                if str(agency.pk) not in agency_list:
                    self.composer.agencies.remove(agency)
                    self.composer.foias.filter(agency=agency).delete()
                    return_requests += 1
            self.composer.return_requests(return_requests)
            transaction.on_commit(
                lambda: submit_composer.
                apply_async(args=(self.composer.pk, True, None))
            )

    def reject(self):
        """Reject the composer and return the user their requests"""
        self.composer.return_requests()
        self.composer.status = 'started'
        self.composer.save()


class PortalTask(Task):
    """An admin needs to interact with a portal"""
    type = 'PortalTask'
    communication = models.ForeignKey('foia.FOIACommunication')
    category = models.CharField(
        max_length=1,
        choices=PORTAL_CATEGORIES,
    )
    reason = models.TextField(blank=True)

    objects = PortalTaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Portal Task'

    def display(self):
        """Display something useful and identifing"""
        return self.communication.foia.title

    def get_absolute_url(self):
        return reverse('portal-task', kwargs={'pk': self.pk})

    def set_status(self, status):
        """Set the status of the comm and FOIA affiliated with this task"""
        comm = self.communication
        comm.status = status
        comm.save()
        comm.foia.status = status
        comm.foia.save(comment='portal task')
        comm.foia.update()


# Retired Tasks


class GenericTask(Task):
    """A generic task"""
    subject = models.CharField(max_length=255)
    body = models.TextField(blank=True)
    objects = TaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Generic Task'


class FailedFaxTask(Task):
    """
    Deprecated: keeping this model around to not lose historical data
    A fax for this communication failed"""
    type = 'FailedFaxTask'
    communication = models.ForeignKey('foia.FOIACommunication')
    reason = models.CharField(max_length=255, blank=True, default='')
    objects = TaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Failed Fax Task'

    def get_absolute_url(self):
        return reverse('failed-fax-task', kwargs={'pk': self.pk})


class RejectedEmailTask(Task):
    """
    Deprecated: Keeping this model around to not lose historical data

    A FOIA request has had an outgoing email rejected"""
    type = 'RejectedEmailTask'
    categories = (('b', 'Bounced'), ('d', 'Dropped'))
    category = models.CharField(max_length=1, choices=categories)
    foia = models.ForeignKey('foia.FOIARequest', blank=True, null=True)
    email = models.EmailField(blank=True)
    error = models.TextField(blank=True)
    objects = TaskQuerySet.as_manager()

    def __unicode__(self):
        return u'Rejected Email Task'

    def get_absolute_url(self):
        return reverse('rejected-email-task', kwargs={'pk': self.pk})


class StaleAgencyTask(Task):
    """An agency has gone stale"""
    type = 'StaleAgencyTask'
    agency = models.ForeignKey('agency.Agency')

    def __unicode__(self):
        return u'Stale Agency Task'

    def get_absolute_url(self):
        return reverse('stale-agency-task', kwargs={'pk': self.pk})

    def resolve(self, user=None, form_data=None):
        """Unmark the agency as stale when resolving"""
        self.agency.unmark_stale()
        super(StaleAgencyTask, self).resolve(user, form_data)

    def stale_requests(self):
        """Returns a list of stale requests associated with the task's agency"""
        if hasattr(self.agency, 'stale_requests_cache'):
            return self.agency.stale_requests_cache
        return FOIARequest.objects.get_stale(agency=self.agency)

    def latest_response(self):
        """Returns the latest response from the agency"""
        foias = self.agency.foiarequest_set.all()
        comms = [c for f in foias for c in f.communications.all() if c.response]
        if len(comms) > 0:
            return max(comms, key=lambda x: x.datetime)
        else:
            return None

    def update_email(self, new_email, foia_list):
        """Updates the email on the agency and the provided requests."""
        from muckrock.agency.models import AgencyEmail
        agency_emails = (
            self.agency.agencyemail_set.filter(
                request_type='primary', email_type='to'
            )
        )
        for agency_email in agency_emails:
            agency_email.request_type = 'none'
            agency_email.email_type = 'none'
            agency_email.save()
        AgencyEmail.objects.create(
            email=new_email,
            agency=self.agency,
            request_type='primary',
            email_type='to',
        )
        for foia in foia_list:
            foia.email = new_email
            foia.followup(switch=True)


class NewExemptionTask(Task):
    """Created when a new exemption is submitted for our review."""
    type = 'NewExemptionTask'
    foia = models.ForeignKey('foia.FOIARequest')
    language = models.TextField()
    user = models.ForeignKey(User)

    def __unicode__(self):
        return u'New Exemption Task'

    def display(self):
        """Display something useful and identifing"""
        return self.foia.title

    def get_absolute_url(self):
        return reverse('newexemption-task', kwargs={'pk': self.pk})


# Not a task, but used by tasks
class BlacklistDomain(models.Model):
    """A domain to be blacklisted from sending us emails"""
    domain = models.CharField(max_length=255)

    def __unicode__(self):
        return self.domain

    def resolve_matches(self):
        """Resolves any orphan tasks that match this blacklisted domain."""
        tasks_to_resolve = OrphanTask.objects.get_from_domain(self.domain)
        for task in tasks_to_resolve:
            task.resolve()
