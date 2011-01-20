"""
OAuth servers for users and admins

Ben Adida
ben.adida@childrens.harvard.edu
"""

import oauth.oauth as oauth

from django.db import transaction
from django.conf import settings
from smart import models

import datetime, logging



class UserDataStore(oauth.OAuthStore):
  """
  Layer between Python OAuth and Django database
  for user applications (PHAs)
  """

  def _get_app(self, consumer_key):
    try:
      return models.PHA.objects.get(consumer_key = consumer_key)
    except models.PHA.DoesNotExist:
      return None

  def _get_token(self, token_str, app=None):
    kwargs = {'token': token_str}
    if app: kwargs['share__with_app'] = app

    try:
      ret = models.AccessToken.objects.get(**kwargs)
      if ret.smart_connect_p == True: oauth.report_error("Not a SMArt Connect Request -- don't treat as one!")
      return ret
    except models.AccessToken.DoesNotExist:
      return None
    
  def verify_request_token_verifier(self, request_token, verifier):
    """
    Verify whether a request token's verifier matches
    The verifier is stored right in the request token itself
    """
    return request_token.verifier == verifier

  def lookup_consumer(self, consumer_key):
    """
    looks up a consumer
    """
    return self._get_app(consumer_key)

  def create_request_token(self,  consumer, 
                           request_token_str, 
                           request_token_secret, 
                           verifier, 
                           oauth_callback, 
                           record_id=None,
                           offline_capable=False):
    """
    take a RequestToken and store it.

    anything after request_token_secret is extra kwargs custom to this server.
    """

    # look for the record that this might be mapped to
    # IMPORTANT: if the user who authorizes this token is not authorized to admin the record, it will be a no-go
    record = None
    if record_id:
      try:
        record = models.Record.objects.get(id = record_id) 
      except models.Record.DoesNotExist:
        pass

    # (BA) added record to the req token now that it can store it
    # (BA 2010-05-06) added offline_capable
    return models.ReqToken.objects.create(app             = consumer, 
                                          token           = request_token_str, 
                                          token_secret    = request_token_secret, 
                                          verifier        = verifier, 
                                          oauth_callback  = oauth_callback, 
                                          record          = record)
#                                         offline         = offline_capable)

  def lookup_request_token(self, consumer, request_token_str):
    """
    token is the token string
    returns a OAuthRequestToken

    consumer may be null.
    """
    try:
      # (BA) fix for consumer being null when we don't know yet who the consumer is
      if consumer:
        return models.ReqToken.objects.get(token = request_token_str, app = consumer)
      else:
        return models.ReqToken.objects.get(token = request_token_str)
    except models.ReqToken.DoesNotExist:
      return None

  def authorize_request_token(self, request_token,record=None, account=None, offline=False):
    """
    Mark a request token as authorized by the given user,
    with the given additional parameters.

    This means the sharing has beeen authorized, so the Share should be added now.
    This way, if the access token process fails, a re-auth will go through automatically.

    The account is whatever data structure was received by the OAuthServer.
    """
    
    if record == None:
      raise Exception("need a record to authorize a share")

    request_token.authorized_at = datetime.datetime.utcnow()
    request_token.authorized_by = account

    # store the share in the request token
    # added use of defaults to reduce code size if creating an object
    share, create_p = models.Share.objects.get_or_create( record        = record, 
                                                            with_app      = request_token.app,
                                                            authorized_by = account,
                                                            defaults = {  'offline':offline, 
                                                                          'authorized_at': request_token.authorized_at, 
                                                                       })
      
    request_token.share = share
    request_token.save()
    

  def mark_request_token_used(self, consumer, request_token):
    """
    Mark that this request token has been used.
    Should fail if it is already used
    """
    new_rt = models.ReqToken.objects.get(app = consumer, token = request_token.token)

    # authorized?
    if not new_rt.authorized:
      raise oauth.OAuthError("Request Token not Authorized")

    new_rt.delete()

  def create_access_token(self, consumer, request_token, access_token_str, access_token_secret):
    """
    Store the newly created access token that is the exchanged version of this
    request token.
    
    IMPORTANT: does not need to check that the request token is still valid, 
    as the library will ensure that this method is never called twice on the same request token,
    as long as mark_request_token_used appropriately throws an error the second time it's called.
    """

    share = request_token.share
    
    # create an access token for this share
    t =  share.new_access_token(access_token_str, 
                                  access_token_secret)
    return t

  def lookup_access_token(self, consumer, access_token_str):
    """
    token is the token string
    returns a OAuthAccessToken
    """
    return self._get_token(token_str = access_token_str, app = consumer)

  def check_and_store_nonce(self, nonce_str):
    """
    store the given nonce in some form to check for later duplicates
    
    IMPORTANT: raises an exception if the nonce has already been stored
    """
    nonce, created = models.Nonce.objects.get_or_create(nonce = nonce_str)
    if not created:
      raise oauth.OAuthError("Nonce already exists")


"""
Thin wrapper around OAuthServer to handle the case where a SMArt Connect
app has made a SMArt Connect request.  In this case, we should verify 
the signature as though the consumer's secret were blank ("") -- but
whenasked to return the consumer, we should return the real thing. 
"""
class SMArtConnectOAuthServer(oauth.OAuthServer):
  def check_resource_access(self, oauth_request):      
    # First, make sure the request is valid for consumer=ChromeApp, token=SMArtUser
#    print "verifying scr", oauth_request.consumer.secret, oauth_request.token.secret
    if not oauth_request.verify(self.store):
      oauth.report_error("signature mismatch")

    try:    
        # Then, make sure the access scope matches what we expect from the existing shares.
        c = oauth_request.oauth_parameters
        
        api_base = c['smart_container_api_base']
        assert api_base == settings.SITE_URL_PREFIX, "Received a SMArt Connect Request for %s, not %s"%(
                                                        api_base, settings.SITE_URL_PREFIX)
    
        app_email = c['smart_app_id']
        app = models.PHA.objects.get(email=app_email)
        
        access_token_string = c['smart_oauth_token']    
        access_token =  models.AccessToken.objects.get(token=access_token_string, share__with_app=app)
        
        access_token_secret_string = c['smart_oauth_token_secret']
        
        assert access_token_secret_string == access_token.secret, "access token secret %s doesn't match expected %s"%(
                                                                        access_token_secret_string, access_token.secret)
                
        user_id = c['smart_user_id']
        assert user_id == oauth_request.token.user.email, "smart user id %s doesn't match session user %s"%(
                                                                        user_id, oauth_request.token.user.email)
        
        assert user_id == access_token.share.authorized_by.email, "smart user_id %s to match share's user %s"%(
                                                                        user_id, access_token.share.authorized_by.email)
        
        record_id = c['smart_record_id']
        assert record_id == access_token.share.record_id, "Expected record_id %s to match share's user %s"%(
                                                                        record_id, access_token.share.record_id)
    
        assert access_token.smart_connect_p == True, "%s Not a SMArt Connect Request -- don't treat as one!"%access_token
        
        # grant access
        oauth_request.consumer = app
        oauth_request.token = access_token
        return oauth_request.consumer, oauth_request.token, oauth_request.oauth_parameters
    except: raise oauth.OAuthError("Not a valid SMArt Connect request")
    
class HelperAppDataStore(UserDataStore):
  def __init__(self, *args, **kwargs):
      super(HelperAppDataStore, self).__init__(*args, **kwargs)
  def _get_app(self, consumer_key):
    try:
      ret = models.HelperApp.objects.get(consumer_key = consumer_key)
      return ret
    except models.HelperApp.DoesNotExist:
      return None

  def _get_token(self, token_str, app=None):
    kwargs = {'token': token_str}
    if app: kwargs['share__with_app'] = app
    try:
      return models.AccessToken.objects.get(**kwargs)
    except models.AccessToken.DoesNotExist:
      return None


class MachineDataStore(oauth.OAuthStore):
  """
  Layer between Python OAuth and Django database.
  """

  def __init__(self, type = None):
    self.type = type

  def _get_machine_app(self, consumer_key):
    try:
      if self.type:
        return models.MachineApp.objects.get(app_type = self.type, consumer_key = consumer_key)
      else:
        # no type, we look at all machine apps
        return models.MachineApp.objects.get(consumer_key = consumer_key)
    except models.MachineApp.DoesNotExist:
      return None

  def lookup_consumer(self, consumer_key):
    return self._get_machine_app(consumer_key)

  def lookup_request_token(self, consumer, request_token_str):
    return None

  def lookup_access_token(self, consumer, access_token_str):
    return None

  def check_and_store_nonce(self, nonce_str):
    """
    store the given nonce in some form to check for later duplicates
    
    IMPORTANT: raises an exception if the nonce has already been stored
    """
    nonce, created = models.Nonce.objects.get_or_create(nonce = nonce_str)
    if not created:
      raise oauth.OAuthError("Nonce already exists")


class SessionDataStore(oauth.OAuthStore):
  """
  Layer between Python OAuth and Django database.

  An oauth-server for in-RAM chrome-app user-specific tokens
  """

  def _get_chrome_app(self, consumer_key):
    try:
      return models.MachineApp.objects.get(consumer_key = consumer_key, app_type='chrome')
    except models.MachineApp.DoesNotExist:
      return None

  def _get_request_token(self, token_str, type=None, pha=None):
    try:
      return models.SessionRequestToken.objects.get(token = token_str)
    except models.SessionRequestToken.DoesNotExist:
      return None

  def _get_token(self, token_str, type=None, pha=None):
    try:
      return models.SessionToken.objects.get(token = token_str)
    except models.SessionToken.DoesNotExist:
      return None

  def lookup_consumer(self, consumer_key):
    """
    looks up a consumer
    """
    return self._get_chrome_app(consumer_key)

  def create_request_token(self, consumer, request_token_str, request_token_secret, verifier, oauth_callback):
    """
    take a RequestToken and store it.

    the only parameter is the user that this token is mapped to.
    """
    
    # we reuse sessiontoken for request and access
    token = models.SessionRequestToken.objects.create(token = request_token_str, secret = request_token_secret)
    return token

  def lookup_request_token(self, consumer, request_token_str):
    """
    token is the token string
    returns a OAuthRequestToken

    consumer may be null.
    """
    return self._get_request_token(token_str = request_token_str)

  def authorize_request_token(self, request_token, user=None):
    """
    Mark a request token as authorized by the given user,
    with the given additional parameters.

    The user is whatever data structure was received by the OAuthServer.
    """
    request_token.user = user
    request_token.authorized_p = True
    request_token.save()

  def mark_request_token_used(self, consumer, request_token):
    """
    Mark that this request token has been used.
    Should fail if it is already used
    """
    if not request_token.authorized_p:
      raise oauth.OAuthError("request token not authorized")

    request_token.delete()

  def create_access_token(self, consumer, request_token, access_token_str, access_token_secret):
    """
    Store the newly created access token that is the exchanged version of this
    request token.
    
    IMPORTANT: does not need to check that the request token is still valid, 
    as the library will ensure that this method is never called twice on the same request token,
    as long as mark_request_token_used appropriately throws an error the second time it's called.
    """

    token = models.SessionToken.objects.create( token   = access_token_str, 
                                                secret  = access_token_secret, 
                                                user    = request_token.user)
    return token

  def lookup_access_token(self, consumer, access_token_str):
    """
    token is the token string
    returns a OAuthAccessToken
    """
    return self._get_token(access_token_str)

  def check_and_store_nonce(self, nonce_str):
    """
    store the given nonce in some form to check for later duplicates
    
    IMPORTANT: raises an exception if the nonce has already been stored
    """
    pass


ADMIN_OAUTH_SERVER = oauth.OAuthServer(store = MachineDataStore())
SESSION_OAUTH_SERVER = oauth.OAuthServer(store = SessionDataStore())
OAUTH_SERVER = oauth.OAuthServer(store = UserDataStore())
SMART_CONNECT_OAUTH_SERVER = SMArtConnectOAuthServer(store = SessionDataStore())
HELPER_APP_SERVER = oauth.OAuthServer(store = HelperAppDataStore())
