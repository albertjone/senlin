# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

from oslo_log import log as logging
from oslo_serialization import jsonutils
import six

from senlin.common import context
from senlin.common import exception as exc
from senlin.common.i18n import _
from senlin.common import utils
from senlin.common import wsgi
from senlin.drivers.openstack import keystone_v3
from senlin.engine import webhook as webhook_mod

LOG = logging.getLogger(__name__)


class WebhookMiddleware(wsgi.Middleware):
    """Middleware for authenticating webhook triggering requests.

    This middleware authenticates the webhook trigger requests and then
    rebuild the request header so that the request will successfully pass
    the verification of keystone auth_token middleware.
    """
    def process_request(self, req):
        # We only handle POST requests
        if req.method != 'POST':
            return

        # Extract webhook ID
        webhook_id = self._extract_webhook_id(req.url)
        if not webhook_id:
            return

        # The request must have a 'key' parameter
        if 'key' not in req.params:
            return
        key = req.params['key']

        credential = self._get_credential(webhook_id, key)
        if not credential:
            return

        # Get token based on credential and fill it into the request header
        token = self._get_token(credential)
        req.headers['X-Auth-Token'] = token

    def _extract_webhook_id(self, url):
        """Extract webhook ID from the request URL.

        :param url: The URL from which the request is received.
        """
        if 'webhooks' not in url:
            return None

        # TODO(Qiming): use urlparse to process the URL
        url_bottom = url.split('webhooks')[1]
        if 'trigger' not in url_bottom:
            return None

        # /<webhook_id>/trigger?key=value
        parts = url_bottom.split('/')
        if len(parts) < 3:
            return None

        webhook_id = parts[1]
        if not parts[2].startswith('trigger'):
            return

        return webhook_id

    def _get_credential(self, webhook_id, key):
        """Get credential for the given webhook using the provided key.

        :param webhook_id: ID of the webhook.
        :param key: The key string to be used for decryption.
        """
        # Build a RequestContext from service context for DB APIs
        ctx = context.RequestContext.from_dict(context.get_service_context())
        webhook_obj = webhook_mod.Webhook.load(ctx, webhook_id)
        credential = webhook_obj.credential

        # Decrypt the credential using provided key
        try:
            cdata = utils.decrypt(credential, key)
            credential = jsonutils.loads(cdata)
        except Exception as ex:
            LOG.exception(six.text_type(ex))
            raise exc.Forbidden()

        if 'auth_url' not in credential:
            # Default to auth_url from service context if not provided
            credential['auth_url'] = ctx.auth_url

        return credential

    def _get_token(self, cred):
        """Get a valid token based on the credential provided.

        :param cred: Rebuilt credential dictionary for authentication.
        """
        try:
            token = keystone_v3.get_token(**cred)
        except Exception as ex:
            LOG.exception(_('Webhook failed authentication: %s.'),
                          six.text_type(ex))
            raise exc.Forbidden()

        return token
