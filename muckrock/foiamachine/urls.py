"""
FOIA Machine urls
"""

from django.conf.urls import patterns, include, url
from django.contrib.auth import views as auth_views

import debug_toolbar

from muckrock.foiamachine import views
from muckrock.forms import PasswordResetForm

urlpatterns = patterns(
    '',
    url(r'^$', views.Homepage.as_view(), name='index'),
    url(r'^accounts/signup/$', views.Signup.as_view(), name='signup'),
    url(r'^accounts/login/$',
        auth_views.login,
        {'template_name': 'foiamachine/registration/login.html'},
        name='login'),
    url(r'^accounts/logout/$',
        auth_views.logout,
        {'next_page': 'index'},
        name='logout'),
    url(r'^accounts/profile/$',
        views.Profile.as_view(),
        name='profile'),
    url(r'^accounts/password_change/$',
        auth_views.password_change,
        {'template_name': 'foiamachine/registration/password_change.html',
         'post_change_redirect': 'password-change-done'},
        name='password-change'),
    url(r'^accounts/password_change/done/$',
        auth_views.password_change_done,
        {'template_name': 'foiamachine/registration/password_change_done.html'},
        name='password-change-done'),
    url(r'^accounts/password_reset/$',
        auth_views.password_reset,
        {'template_name': 'foiamachine/registration/password_reset.html',
         'email_template_name': 'foiamachine/email/password_reset_email.html',
         'post_reset_redirect': 'password-reset-done',
         'password_reset_form': PasswordResetForm},
        name='password-reset'),
    url(r'^accounts/password_reset/(?P<uidb64>[0-9A-Za-z]+)-(?P<token>.+)/$',
        auth_views.password_reset_confirm,
        {'template_name': 'foiamachine/registration/password_reset_confirm.html',
         'post_reset_redirect': 'password-reset-complete'},
        name='password-reset-confirm'),
    url(r'^accounts/password_reset/done/$',
        auth_views.password_reset_done,
        {'template_name': 'foiamachine/registration/password_reset_done.html'},
        name='password-reset-done'),
    url(r'^accounts/password_reset/complete/$',
        auth_views.password_reset_complete,
        {'template_name': 'foiamachine/registration/password_reset_complete.html'},
        name='password-reset-complete'),
    url(r'^__debug__/', include(debug_toolbar.urls)),
)