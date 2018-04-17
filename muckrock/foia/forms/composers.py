"""
FOIA forms for composing requests
"""

# Django
from django import forms
from django.contrib.auth.models import User

# Third Party
from autocomplete_light import shortcuts as autocomplete_light
from autocomplete_light.contrib.taggit_field import TaggitField

# MuckRock
from muckrock.accounts.forms import BuyRequestForm
from muckrock.agency.models import Agency
from muckrock.foia.fields import ComposerAgencyField
from muckrock.foia.forms.comms import ContactInfoForm
from muckrock.foia.models import FOIAComposer, FOIAMultiRequest
from muckrock.forms import TaggitWidget


class BaseComposerForm(forms.ModelForm):
    """This form creates and updates FOIA composers"""

    title = forms.CharField(
        widget=forms.TextInput(
            attrs={
                'placeholder': 'Add a title',
                'class': 'submit-required',
            }
        ),
        max_length=255,
        required=False,
    )
    requested_docs = forms.CharField(
        widget=forms.Textarea(
            attrs={
                'placeholder':
                    'Write a short description of the documents you are '
                    'looking for. The more specific you can be, the better.',
                'class': 'submit-required',
            }
        ),
        required=False,
    )
    agencies = ComposerAgencyField(
        queryset=Agency.objects.get_approved(),
        widget=autocomplete_light.
        MultipleChoiceWidget('AgencyComposerAutocomplete'),
        required=False,
        help_text='i.e., Police Department, Austin, TX or Office of the '
        'Governor, Arkansas'
    )
    edited_boilerplate = forms.BooleanField(
        required=False,
        label='Edit Template Language',
    )
    embargo = forms.BooleanField(
        required=False,
        help_text='Embargoing a request keeps it completely private from '
        'other users until the embargo date you set. '
        'You may change this whenever you want.'
    )
    tags = TaggitField(
        widget=TaggitWidget(
            'TagAutocomplete',
            attrs={
                'placeholder': 'Search tags',
                'data-autocomplete-minimum-characters': 1
            }
        ),
        help_text='Separate tags with commas.',
        required=False,
    )
    parent = forms.ModelChoiceField(
        queryset=FOIAComposer.objects.none(),
        required=False,
        widget=forms.HiddenInput(),
    )
    action = forms.ChoiceField(
        choices=[
            ('save', 'Save'),
            ('submit', 'Submit'),
            ('delete', 'Delete'),
        ],
        widget=forms.HiddenInput(),
    )

    # XXX this should be a sub form?
    register_full_name = forms.CharField(label='Full Name or Handle (Public)')
    register_email = forms.EmailField(max_length=75)
    register_newsletter = forms.BooleanField(
        initial=True,
        required=False,
        label='Get MuckRock\'s weekly newsletter with '
        'FOIA news, tips, and more',
    )

    class Meta:
        model = FOIAComposer
        fields = [
            'title',
            'agencies',
            'requested_docs',
            'edited_boilerplate',
            'embargo',
            'tags',
            'parent',
            'register_full_name',
            'register_email',
            'register_newsletter',
        ]

    def __init__(self, *args, **kwargs):
        if not hasattr(self, 'user'):
            self.user = kwargs.pop('user')
        super(BaseComposerForm, self).__init__(*args, **kwargs)
        if self.user.is_authenticated:
            del self.fields['register_full_name']
            del self.fields['register_email']
            del self.fields['register_newsletter']
        if not self.user.has_perm('foia.embargo_foiarequest'):
            del self.fields['embargo']
        self.fields['parent'
                    ].queryset = (FOIAComposer.objects.get_viewable(self.user))
        self.fields['agencies'].user = self.user
        self.fields['agencies'].queryset = (
            Agency.objects.get_approved_and_pending(self.user)
        )

    def clean_register_email(self):
        """Do a case insensitive uniqueness check"""
        email = self.cleaned_data['register_email']
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                'User with this email already exists. Please login first.'
            )
        return email

    def clean_title(self):
        """Make sure we have a non-blank(ish) title"""
        title = self.cleaned_data['title'].strip()
        if title:
            return title
        else:
            return 'Untitled'

    def clean_agencies(self):
        """Remove exempt agencies"""
        return [a for a in self.cleaned_data['agencies'] if not a.exempt]

    def clean_tags(self):
        """Parse tags correctly"""
        # XXX
        return self.cleaned_data['tags']

    def clean(self):
        """Check cross field dependencies"""
        cleaned_data = super(BaseComposerForm, self).clean()
        if cleaned_data.get('action') == 'submit':
            for field in ['title', 'requested_docs', 'agencies']:
                if not self.cleaned_data.get(field):
                    self.add_error(
                        field,
                        'This field is required when submitting',
                    )
        return cleaned_data


class ComposerForm(ContactInfoForm, BuyRequestForm, BaseComposerForm):
    """Composer form, including optional subforms"""

    def __init__(self, *args, **kwargs):
        super(ComposerForm, self).__init__(*args, **kwargs)
        # Make sub-form fields non-required
        self.fields['stripe_token'].required = False
        self.fields['stripe_email'].required = False
        self.fields['num_requests'].required = False

    def clean(self):
        """Buy request fields are only required when buying requests"""
        cleaned_data = super(ComposerForm, self).clean()
        if cleaned_data.get('num_requests', 0) > 0:
            for field in ['stripe_token', 'stripe_email']:
                if not self.cleaned_data.get(field):
                    self.add_error(
                        field,
                        'This field is required when purchasing requests',
                    )


class RequestDraftForm(forms.Form):
    """Presents limited information from created single request for editing"""
    title = forms.CharField(
        widget=forms.TextInput(attrs={
            'placeholder': 'Pick a Title'
        }),
        max_length=255,
    )
    request = forms.CharField(widget=forms.Textarea())
    embargo = forms.BooleanField(
        required=False,
        help_text='Embargoing a request keeps it completely private from '
        'other users until the embargo date you set. '
        'You may change this whenever you want.'
    )


class MultiRequestForm(forms.ModelForm):
    """A form for a multi-request"""

    requested_docs = forms.CharField(label='Request', widget=forms.Textarea())
    agencies = forms.ModelMultipleChoiceField(
        queryset=Agency.objects.get_approved(),
        required=True,
        widget=autocomplete_light.
        MultipleChoiceWidget('AgencyMultiRequestAutocomplete'),
    )
    parent = forms.ModelChoiceField(
        queryset=FOIAMultiRequest.objects.none(),
        required=False,
        widget=forms.HiddenInput(),
    )

    class Meta:
        model = FOIAMultiRequest
        fields = ['title', 'requested_docs', 'agencies', 'parent']
        widgets = {
            'title': forms.TextInput(attrs={
                'placeholder': 'Pick a Title'
            }),
        }

    def __init__(self, *args, **kwargs):
        user = kwargs.pop('user')
        super(MultiRequestForm, self).__init__(*args, **kwargs)
        self.fields['parent'].queryset = FOIAMultiRequest.objects.filter(
            user=user
        )


class MultiRequestDraftForm(forms.ModelForm):
    """Presents info from created multi-request for editing"""
    title = forms.CharField(
        widget=forms.TextInput(attrs={
            'placeholder': 'Pick a Title'
        })
    )
    tags = TaggitField(
        widget=TaggitWidget(
            'TagAutocomplete',
            attrs={
                'placeholder': 'Search tags',
                'data-autocomplete-minimum-characters': 1
            }
        ),
        help_text='Separate tags with commas.',
        required=False,
    )
    requested_docs = forms.CharField(label='Request', widget=forms.Textarea())
    embargo = forms.BooleanField(
        required=False,
        help_text='Embargoing a request keeps it completely private from '
        'other users until the embargo date you set.  '
        'You may change this whenever you want.'
    )

    class Meta:
        model = FOIAMultiRequest
        fields = ['title', 'tags', 'requested_docs', 'embargo']