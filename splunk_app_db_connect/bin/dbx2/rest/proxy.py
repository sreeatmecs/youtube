from __future__ import absolute_import
import splunk.rest
import json
import requests
import urllib
from dbx2.dbx_logger import logger
from dbx2.rest.settings import Settings

class ProxyManager(splunk.rest.BaseRestHandler):
    taskserverPort = Settings.read_taskserver_port()

    # the max timeout is 5*60=300 seconds.  Here set the value to 310 is to give some flexibility such that
    # we can distinguish a slow connection and a request timeout.
    # The maxWaitMillis in the backend is 300000(300 seconds) tops.
    # Any connection that fails to establish within maxWaitMillis will get an 'Internal Server Error'
    timeout = 310

    exception_code_map = {
        'Timeout': (requests.codes.gateway_timeout,
                    'DBX Server did not respond within %s seconds, '
                    'please make sure it is started and listening on %s port '
                    'or consult documentation for details.' % (timeout, taskserverPort)),
        'ConnectionError': (requests.codes.service_unavailable,
                            'DBX Server is not available, '
                            'please make sure it is started and listening on %s port '
                            'or consult documentation for details.' % taskserverPort),
        'SSLError': (requests.codes.service_unavailable,
                     'Unable to establish a secure connection to DBX Server, '
                     'please make sure it is started '
                     'and listening on %s port or consult documentation for details' % taskserverPort)
    }

    def buildUrl(self):
        url_path = "http://127.0.0.1:" + str(self.taskserverPort) + "/api/{}"
        return url_path.format('/'.join(map(lambda p: urllib.quote(p, safe=""), self.pathParts[3:])))

    def forwardRequest(self, method, url, params=None, data=None):
        headers = {
            'content-type': 'application/json',
            'X-DBX-SESSION_KEY': self.sessionKey,
            'X-DBX-OWNER': self.userName
        }

        resp_status = ()
        resp_body = {}

        if data is not None:
            data = data.encode('utf-8')

        try:
            logger.debug("action=api_forwarding_request method=%s url=%s params=%s timeout=%s", method, url, params, self.timeout)

            response = requests.request(
                method=method,
                url=url,
                data=data,
                params=params,
                headers=headers,
                timeout=self.timeout
            )
            resp_status = (response.status_code, '')
            resp_body = response.content

            resp_status, resp_body = self.check_response_integrity(response.headers, resp_status, resp_body)
        except Exception as e:
            resp_status = self.handle_exception(e)

            resp_body = json.dumps({
                'code': resp_status[0],
                'message': resp_status[1],
                'detail': str(e)
            })
            logger.debug("action=api_forwarding_request_error error=%s", e)
        finally:
            # Make sure a JSON response is returned
            logger.debug("action=api_forwarding_request_writing_response status=%s", resp_status[0])
            self.response.setHeader('content-type', 'application/json')
            self.response.status = resp_status[0]
            self.response.write(resp_body)

    def handle_exception(self, exception):
        exception_type = type(exception).__name__
        resp_status = self.exception_code_map.get(exception_type, (requests.codes.internal_server_error, 'Internal server error'))
        return resp_status

    def check_response_integrity(self, headers, resp_status, resp_body):
        # just in case, others respond to the request
        if 'Server' not in headers or headers['Server'] != 'DBX Server':
            resp_status = (requests.codes.bad_gateway, 'Response was not generated by DBX Server, '
                                                       'please make sure it is started and listening on %s port '
                                                       'or consult documentation for details' % self.taskserverPort)
            logger.debug("action=check_response_integrity error=%s", resp_status[1])
            resp_body = json.dumps({
                'code': resp_status[0],
                'message': 'Bad Gateway',
                'detail': resp_status[1]
            })
        return resp_status, resp_body

    def handle_GET(self):
        url = self.buildUrl()
        self.forwardRequest('GET', url, params=self.request.get('query', None))

    def handle_POST(self):
        url = self.buildUrl()
        self.forwardRequest('POST', url, params=self.request.get('query', None), data=self.request['payload'])

    def handle_PUT(self):
        url = self.buildUrl()
        self.forwardRequest('PUT', url, params=self.request.get('query', None), data=self.request['payload'])

    def handle_DELETE(self):
        url = self.buildUrl()
        self.forwardRequest('DELETE', url, params=self.request.get('query', None), data=self.request['payload'])

    @property
    def userName(self):
        return self.request["userName"]

    @property
    def hostPath(self):
        return self.request["headers"]["host"]

    @property
    def host(self):
        return self.hostPath.split(":")[0]