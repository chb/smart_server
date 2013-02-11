"""
SMArt

Indivo Models for Applications that extend Indivo

Ben Adida
Steve Zabak
"""

from django.db import models
from django.conf import settings

from base import Object, Principal, BaseModel, BaseMeta, APP_LABEL

import urllib
import datetime
import json

##
## OAuth Stuff
##


class Nonce(BaseModel):
    """
    Nonces for oauth
    FIXME: clear out the old nonces regularly
    """
    nonce = models.CharField(max_length=100, null=False, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)


##
## problem with hierarchy of abstracts
##
class OAuthApp(Principal):
    """
    An intermediate abstract class for all OAuth applications
    """

    Meta = BaseMeta(False)

    consumer_key = models.CharField(max_length=200)
    secret = models.CharField(max_length=60)
    name = models.CharField(max_length=200)
    
    # manifest and properties extracted from the manifest
    manifest = models.TextField(null=True)
    
    @property
    def index_url(self):
        m = json.loads(self.manifest)
        return m.get('index')
    
    @property
    def icon_url(self):
        m = json.loads(self.manifest)
        return m.get('icon')


##
## PHAs
##

class PHA(OAuthApp):
    """
    User applications
    """

    Meta = BaseMeta()
    # URL templates look like http://host/url/{param1}?foo={param2}

    # we are using a flag called "standalone" now, this field now stores the
    # inverse of that flag. A database migration would be cleaner.
    frameable = models.BooleanField(default=True)
    
    @property
    def standalone(self):
        return not self.frameable

    # short description of the app
    description = models.CharField(max_length=2000, null=True)

    # is app enabled by default on new accounts?
    enabled_by_default = models.BooleanField(default=False)
    supported_environments = models.CharField(
        max_length=30, default="desktop,mobile,tablet")
    optimal_environments = models.CharField(max_length=30, default="desktop")
    mode = models.CharField(max_length=10)


class HelperApp(OAuthApp):
    """
    Helper Applications provide a service to other apps.
    For now, they don't get access to patient record data...
    """

    Meta = BaseMeta()
    
    # short description of the app
    description = models.CharField(max_length=2000, null=True)
    admin_p = models.BooleanField(default=False)

##
## App Tokens are implemented separately, since they require access to record
## and docs (yes, this is confusing, but otherwise it's circular import hell)
##

##
## Applications which communicate directly with Indivo, not user-mediated
## There are two types:
## - admin: can use the admin API
## - chrome: can use any API and sudo as another user (though not as an admin
## app)
##

# inherit first from Principal, second from OAuth Consumer


class MachineApp(OAuthApp):
    APP_TYPES = (
        ('admin', 'Admin'),
        ('chrome', 'Chrome')
    )

    # admin or chrome?
    # all chrome apps are also admin apps, but we use a type field
    # in case we add new types in the future
    app_type = models.CharField(
        max_length=100, choices=APP_TYPES, null=False)

    # token and secret
    # an admin app is an oauth consumer with one token and one secret
    # which are repeated, as if it were an access token.
    #token = models.CharField(max_length=16)
    #secret = models.CharField(max_length=16)

    @classmethod
    def from_consumer(cls, consumer):
        return cls.objects.get(consumer=consumer)



##
## session tokens
##


class SessionRequestToken(Object):
    token = models.CharField(max_length=40)
    secret = models.CharField(max_length=60)

    user = models.ForeignKey('Account', null=True)
    approved_p = models.BooleanField(default=False)


class SessionToken(Object):
    token = models.CharField(max_length=40)
    secret = models.CharField(max_length=60)
    user = models.ForeignKey('Account', null=True)
    expires_at = models.DateTimeField(null=False)

    @property
    def approved_p(self):
        return True

    def save(self, *args, **kwargs):
        if self.expires_at is None:
            self.expires_at = datetime.datetime.utcnow(
            ) + datetime.timedelta(minutes=30)
        super(SessionToken, self).save(*args, **kwargs)

    def __str__(self):
        vars = {
            'oauth_token': self.token,
            'oauth_token_secret': self.secret,
            'account_id': self.user.email
        }
        return urllib.urlencode(vars)
