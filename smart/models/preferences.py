import datetime

from django.db import models
from django.conf import settings

from base import APP_LABEL, Object

class Preferences(Object):

  account = models.ForeignKey('Account', null=True)
  pha = models.ForeignKey('PHA', null=True)
  last_updated = models.DateTimeField(null=False, blank=False, auto_now=True, auto_now_add=True)
  data = models.TextField(null=True)
  
  class Meta:
    app_label = APP_LABEL
    unique_together = ('account', 'pha')