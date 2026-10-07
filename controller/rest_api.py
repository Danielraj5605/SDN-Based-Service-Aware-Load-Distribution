"""REST API served by ryu-manager (default http://127.0.0.1:8080).

    GET  /lb/status    mode, per-server metrics and current scores
    GET  /lb/flows     active load-balanced flows and the server each one went to
    POST /lb/mode      {"mode": "service_aware" | "round_robin"}
    POST /lb/weights   {"service": "voip", "weights": {"latency": 0.6, ...}}
"""
import json

from ryu.app.wsgi import ControllerBase, route
from webob import Response

from config_loader import ConfigError

APP_KEY = 'sdn_lb_app'


def _json(data, status=200):
    return Response(status=status, content_type='application/json',
                    body=json.dumps(data, indent=2).encode('utf-8'))


def _body(req):
    try:
        return json.loads(req.body.decode('utf-8') or '{}')
    except ValueError:
        raise ConfigError('request body must be JSON')


class LBRestController(ControllerBase):
    def __init__(self, req, link, data, **config):
        super(LBRestController, self).__init__(req, link, data, **config)
        self.app = data[APP_KEY]

    @route('lb', '/lb/status', methods=['GET'])
    def status(self, req, **kwargs):
        return _json(self.app.get_status())

    @route('lb', '/lb/flows', methods=['GET'])
    def flows(self, req, **kwargs):
        return _json(self.app.get_flows())

    @route('lb', '/lb/mode', methods=['POST', 'PUT'])
    def set_mode(self, req, **kwargs):
        try:
            mode = self.app.set_mode(_body(req).get('mode', ''))
        except ConfigError as e:
            return _json({'error': str(e)}, 400)
        return _json({'mode': mode})

    @route('lb', '/lb/weights', methods=['POST', 'PUT'])
    def set_weights(self, req, **kwargs):
        try:
            body = _body(req)
            weights = self.app.set_weights(body.get('service', ''), body.get('weights') or {})
        except ConfigError as e:
            return _json({'error': str(e)}, 400)
        return _json({'service': body['service'], 'weights': weights})
