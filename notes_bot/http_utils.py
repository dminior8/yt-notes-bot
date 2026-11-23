"""Drobne narzędzia HTTP."""

import json
import urllib.request

def http_json(url, data=None, headers=None, method=None):
    req = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    with urllib.request.urlopen(req) as response:
        return json.loads(response.read().decode('utf-8'))

def http_error_body(error):
    return error.read().decode('utf-8', errors='ignore')
