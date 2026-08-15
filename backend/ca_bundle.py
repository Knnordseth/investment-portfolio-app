"""Fixes 'SSL: CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate' on this
machine: some certificate (a corporate/antivirus SSL-inspection root) is trusted by Windows
but missing from Python's bundled certifi list, so requests/yfinance/curl_cffi reject every
HTTPS call. certs/windows_ca_bundle.pem is certifi's list plus everything Windows already
trusts (see certs/generate_ca_bundle.ps1 to regenerate it).

Import this — for its side effect — before anything that makes an HTTPS call (requests,
yfinance). Must run before those libraries build their first session/SSL context.
"""

import os
from pathlib import Path

_BUNDLE = Path(__file__).parent / "certs" / "windows_ca_bundle.pem"

if _BUNDLE.exists():
    bundle_path = str(_BUNDLE)
    # SSL_CERT_FILE: stdlib ssl / urllib3. REQUESTS_CA_BUNDLE: requests. CURL_CA_BUNDLE:
    # curl_cffi, which yfinance uses and which ignores the first two.
    os.environ.setdefault("SSL_CERT_FILE", bundle_path)
    os.environ.setdefault("REQUESTS_CA_BUNDLE", bundle_path)
    os.environ.setdefault("CURL_CA_BUNDLE", bundle_path)
